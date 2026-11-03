"""
LATTICE GATE - headless grid game logic (no pygame).

    game = GridGame(seed=123, difficulty="medium")
    while not game.done:
        game.step(UP)           # actions: STAY, UP, DOWN, LEFT, RIGHT  (ints 0-4)

The world is a small deterministic grid MDP:
  * the ship occupies one cell (col, row); row 0 is the bottom
  * each lane row holds asteroids that slide one cell every `period` turns and wrap
  * moving up out of the top row inside the gate = win; walls block movement
  * an asteroid hit doesn't end the run; that asteroid becomes harmless ("spent")

Everything about the field depends only on the seed, and `occupied(col, row, t)` tells
you exactly where asteroids will be at any future turn - useful for planners, value
iteration and inverse RL.
"""

import copy
import json
import os
import random
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List

import grid_config

GAME_VERSION = "grid-0.1.0"

STAY, UP, DOWN, LEFT, RIGHT = range(5)
GRID_ACTIONS = [STAY, UP, DOWN, LEFT, RIGHT]
ACTION_NAMES = ["stay", "up", "down", "left", "right"]
ACTION_DELTA = {STAY: (0, 0), UP: (0, 1), DOWN: (0, -1), LEFT: (-1, 0), RIGHT: (1, 0)}

RUNNING, WIN, TIMEOUT = "running", "win", "timeout"

_KEYS = ["GAME", "COLS", "ROWS", "CELL", "START_COL", "START_ROW", "SAFE_ROWS",
         "LANE_MARGIN", "VIEW_MARGIN_FRAC", "PLAY_MODE", "REALTIME_HZ", "ANIM_TIME",
         "MAX_TURNS", "DIFFICULTIES", "DEFAULT_DIFFICULTY"]


def grid_settings(**overrides):
    """Settings dict from grid_config.py, with optional overrides."""
    s = {k: copy.deepcopy(getattr(grid_config, k)) for k in _KEYS}
    for k, v in overrides.items():
        if k not in s:
            raise KeyError(f"Unknown grid setting: {k}")
        s[k] = v
    # keys the shared renderer expects (world units)
    s["FIELD_WIDTH"] = s["COLS"] * s["CELL"]
    s["FIELD_HEIGHT"] = s["ROWS"] * s["CELL"]
    s["SHIP_RADIUS"] = 0.35 * s["CELL"]
    s["START_POS"] = ((s["START_COL"] + 0.5) * s["CELL"], (s["START_ROW"] + 0.5) * s["CELL"])
    s["BOTTOM_IS_WALL"] = True
    s["GRID_STEP"] = s["CELL"]
    s["GOAL_GATE"] = None          # filled per game (the gate depends on the seed)
    return s


@dataclass
class Lane:
    row: int
    direction: int                  # +1 moves right, -1 moves left
    period: int                     # turns per one-cell move
    starts: List[int]               # lane indices (0..L-1) of asteroids at turn 0
    ids: List[int]


@dataclass
class StepResult:
    turn: int
    done: bool
    outcome: str
    events: List[str] = field(default_factory=list)


class GridGame:
    def __init__(self, seed=None, difficulty=None, settings=None):
        self.s = settings if settings is not None else grid_settings()
        self.difficulty = difficulty or self.s["DEFAULT_DIFFICULTY"]
        if self.difficulty not in self.s["DIFFICULTIES"]:
            raise ValueError(f"Unknown difficulty {self.difficulty!r}")
        self.seed = seed if seed is not None else random.randrange(1_000_000)
        self.reset()

    # -- setup ---------------------------------------------------------------
    def reset(self, seed=None):
        if seed is not None:
            self.seed = seed
        s, d = self.s, self.s["DIFFICULTIES"][self.difficulty]
        rng = random.Random(self.seed)
        self.C, self.R, self.M = s["COLS"], s["ROWS"], s["LANE_MARGIN"]
        self.L = self.C + 2 * self.M                     # full lane length incl. hidden cells
        gw = d["gate_width"]
        self.gate = (rng.randrange(0, self.C - gw + 1), gw)   # (first col, width)
        self.s = dict(s)
        self.s["GOAL_GATE"] = ((self.gate[0] + gw / 2) * s["CELL"], gw * s["CELL"])
        self.lanes: List[Lane] = []
        next_id = 1
        for row in range(self.R):
            if row in s["SAFE_ROWS"]:
                continue
            starts = [i for i in range(self.L) if rng.random() < d["density"]]
            if len(starts) == self.L:                    # always leave a gap
                starts.pop()
            ids = list(range(next_id, next_id + len(starts)))
            next_id += len(starts)
            self.lanes.append(Lane(row, rng.choice((-1, 1)), rng.choice(d["periods"]), starts, ids))
        self.col, self.row = s["START_COL"], s["START_ROW"]
        self.heading = UP
        self.turn = 0
        self.hits = 0
        self.spent = set()
        self.outcome = RUNNING
        self.done = False
        self.last_action = STAY
        return self

    # -- asteroid positions (exact, any turn) ---------------------------------
    def lane_col(self, lane, start, t):
        """Visible column (can be <0 or >=COLS when in the hidden part) at turn t."""
        shift = lane.direction * (t // lane.period)
        return (start + shift) % self.L - self.M

    def asteroids_at(self, t):
        """List of (id, col, row) for every asteroid at turn t (including hidden ones)."""
        out = []
        for lane in self.lanes:
            for aid, st in zip(lane.ids, lane.starts):
                out.append((aid, self.lane_col(lane, st, t), lane.row))
        return out

    def occupied(self, col, row, t, ignore_spent=False):
        """True if a (non-spent) asteroid is in this cell at turn t."""
        for lane in self.lanes:
            if lane.row != row:
                continue
            for aid, st in zip(lane.ids, lane.starts):
                if ignore_spent and aid in self.spent:
                    continue
                if self.lane_col(lane, st, t) == col:
                    return True
        return False

    def in_gate(self, col):
        g0, gw = self.gate
        return g0 <= col < g0 + gw

    # -- scoring -------------------------------------------------------------
    def score(self):
        """Turns taken (lower is better) - only compared within the same hit tier."""
        return float(self.turn)

    def rank_key(self):
        return (0 if self.outcome == WIN else 1, self.hits, self.turn)

    # -- main step -----------------------------------------------------------
    def step(self, action=STAY):
        if self.done:
            return StepResult(self.turn, True, self.outcome, [])
        action = int(action)
        self.last_action = action
        events = []
        dc, dr = ACTION_DELTA[action]
        if action != STAY:
            self.heading = action
        old_c, old_r = self.col, self.row
        t0, t1 = self.turn, self.turn + 1

        # 1. move the ship (walls block; up from the top row inside the gate = win)
        nc, nr = old_c + dc, old_r + dr
        won = False
        if nr >= self.R:
            if self.in_gate(old_c):
                won = True
                nc, nr = old_c, self.R      # just outside the top wall
            else:
                nc, nr = old_c, old_r       # blocked by the wall
        if not (0 <= nc < self.C) or nr < 0:
            nc, nr = old_c, old_r
        self.col, self.row = nc, nr
        self.turn = t1

        # 2. hits: an asteroid in the new cell after it moves, or one that swapped
        #    places with the ship this turn
        if not won:
            for lane in self.lanes:
                if lane.row != nr:
                    continue
                for aid, st in zip(lane.ids, lane.starts):
                    if aid in self.spent:
                        continue
                    a0, a1 = self.lane_col(lane, st, t0), self.lane_col(lane, st, t1)
                    if a1 == nc or (nr == old_r and a0 == nc and a1 == old_c):
                        self.hits += 1
                        self.spent.add(aid)
                        events.append("hit")

        # 3. end of run
        if won:
            self.outcome, self.done = WIN, True
            events.append(WIN)
        elif self.turn >= self.s["MAX_TURNS"]:
            self.outcome, self.done = TIMEOUT, True
            events.append(TIMEOUT)
        return StepResult(self.turn, self.done, self.outcome, events)

    # -- state ---------------------------------------------------------------
    def get_state(self):
        vis = self.M  # include the hidden cells so animation can slide in smoothly
        return {
            "turn": self.turn,
            "ship": {"col": self.col, "row": self.row, "heading": self.heading},
            "hits": self.hits,
            "gate": list(self.gate),
            "asteroids": [{"id": aid, "col": c, "row": r, "spent": aid in self.spent}
                          for aid, c, r in self.asteroids_at(self.turn)
                          if -vis <= c < self.C + vis],
        }

    # -- oracle --------------------------------------------------------------
    def shortest_safe_path(self, max_turns=None):
        """Breadth-first search over (col, row, turn): the fewest-turn path to the gate
        that never touches an asteroid (ignores 'spent'). Returns a list of actions, or
        None if no hit-free path exists within max_turns. Starts from the current state."""
        max_turns = max_turns or self.s["MAX_TURNS"]
        start = (self.col, self.row, self.turn)
        prev = {start: None}
        q = deque([start])
        while q:
            c, r, t = q.popleft()
            if t - start[2] >= max_turns:
                continue
            for a in GRID_ACTIONS:
                dc, dr = ACTION_DELTA[a]
                nc, nr = c + dc, r + dr
                if nr >= self.R:
                    if self.in_gate(c):
                        path = [a]
                        node = (c, r, t)
                        while prev[node] is not None:
                            node, act = prev[node]
                            path.append(act)
                        return path[::-1]
                    nc, nr = c, r
                if not (0 <= nc < self.C) or nr < 0:
                    nc, nr = c, r
                if self._cell_hit(c, r, nc, nr, t):
                    continue
                key = (nc, nr, t + 1)
                if key not in prev:
                    prev[key] = ((c, r, t), a)
                    q.append(key)
        return None

    def _cell_hit(self, oc, orow, nc, nr, t):
        for lane in self.lanes:
            if lane.row != nr:
                continue
            for st in lane.starts:
                a0, a1 = self.lane_col(lane, st, t), self.lane_col(lane, st, t + 1)
                if a1 == nc or (nr == orow and a0 == nc and a1 == oc):
                    return True
        return False


# ----------------------------------------------------------------------------
# Recording (own small schema, own database file)
# ----------------------------------------------------------------------------
GRID_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player TEXT, started_at TEXT, game_version TEXT,
    seed INTEGER, difficulty TEXT, settings_json TEXT, gate_json TEXT,
    outcome TEXT, turns INTEGER, hits INTEGER, score REAL, notes TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    episode_id INTEGER REFERENCES episodes(id),
    turn INTEGER,
    ship_col INTEGER, ship_row INTEGER, hits INTEGER,
    action INTEGER,            -- 0 stay, 1 up, 2 down, 3 left, 4 right (NULL on final row)
    asteroids_json TEXT,       -- [{"id","col","row","spent"}, ...]
    PRIMARY KEY (episode_id, turn)
);
"""


class GridRecorder:
    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.executescript(GRID_SCHEMA)
        self.episode_id = None
        self._rows = []

    def start_episode(self, game, player):
        cur = self.con.execute(
            "INSERT INTO episodes (player, started_at, game_version, seed, difficulty,"
            " settings_json, gate_json, outcome) VALUES (?,?,?,?,?,?,?,?)",
            (player, time.strftime("%Y-%m-%d %H:%M:%S"), GAME_VERSION, game.seed,
             game.difficulty, json.dumps(game.s), json.dumps(game.gate), "running"))
        self.con.commit()
        self.episode_id = cur.lastrowid
        self._rows = []

    def log_step(self, state, action):
        sh = state["ship"]
        self._rows.append((self.episode_id, state["turn"], sh["col"], sh["row"], state["hits"],
                           action, json.dumps(state["asteroids"], separators=(",", ":"))))

    def end_episode(self, game, outcome=None):
        self.con.executemany("INSERT INTO steps VALUES (?,?,?,?,?,?,?)", self._rows)
        self.con.execute("UPDATE episodes SET outcome=?, turns=?, hits=?, score=? WHERE id=?",
                         (outcome or game.outcome, game.turn, game.hits, game.score(),
                          self.episode_id))
        self.con.commit()
        self._rows = []

    def best_for_seed(self, seed, difficulty):
        return self.con.execute(
            "SELECT player, hits, turns FROM episodes WHERE seed=? AND difficulty=?"
            " AND outcome='win' ORDER BY hits, turns LIMIT 1", (seed, difficulty)).fetchone()

    def close(self):
        self.con.close()


def load_grid_episode(path, episode_id):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    ep = con.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
    if ep is None:
        raise KeyError(f"No episode {episode_id} in {path}")
    steps = [dict(r) for r in con.execute(
        "SELECT * FROM steps WHERE episode_id=? ORDER BY turn", (episode_id,))]
    con.close()
    for st in steps:
        st["asteroids"] = json.loads(st.pop("asteroids_json"))
    ep = dict(ep)
    ep["settings"] = json.loads(ep["settings_json"])
    return ep, steps
