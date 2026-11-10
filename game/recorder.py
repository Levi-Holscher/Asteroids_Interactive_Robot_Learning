"""
Records games to a SQLite database (one file per player: data/demos_<player>.sqlite).

Per-player files mean teammates never change the same file, so nothing has to be merged.
demo_db_path("Levi") -> data/demos_levi.sqlite; find_demo_dbs() lists every player's file.

Tables
------
episodes : one row per run (player, seed, difficulty, settings, outcome, time, fuel, hits, score)
steps    : one row per tick (ship state, the action taken on that tick, fuel/hits so far,
           and every asteroid's position/velocity/spent flag, compressed)
asteroids: one row per asteroid per run: the values that never change (radius r and
           acceleration ax, ay), so they aren't repeated 20 times a second

Asteroid storage (format 2, ~10x smaller than format 1):
    steps.asteroids_z = zlib-compressed JSON [[id, x, y, vx, vy, spent], ...], numbers
    rounded to config.RECORD_DECIMALS. Format 1 (older files) stored a full-precision
    JSON list of dicts in steps.asteroids_json instead. load_episode() reads both and
    always returns the same thing: one dict per asteroid with
    id, x, y, vx, vy, ax, ay, r, spent.

Each step row stores the state *before* the action and the action taken, i.e. the
(s_t, a_t) pair a learning algorithm wants. The final state after the last action is
stored as an extra row with action NULL.

Open it in Python with sqlite3 or pandas:
    import sqlite3, pandas as pd
    con = sqlite3.connect("data/demos_levi.sqlite")
    eps = pd.read_sql("SELECT * FROM episodes", con)
"""

import glob
import json
import os
import sqlite3
import re
import time
import zlib

import config
from game.seeds import check_demo_seed


def player_slug(player):
    """File-name-safe version of a player name: "Levi H." -> "levi_h"."""
    slug = re.sub(r"[^a-z0-9_-]+", "_", str(player or "").strip().lower()).strip("_")
    return slug or "anonymous"


def demo_db_path(player, data_dir=None):
    """Where `player`'s demos are recorded: data/demos_<player>.sqlite."""
    return os.path.join(data_dir or config.DATA_DIR, f"demos_{player_slug(player)}.sqlite")


def find_demo_dbs(data_dir=None):
    """Every per-player demo file (data/demos_*.sqlite), sorted by name. Bot demos
    (demos_bot.sqlite) are included; the old shared demos.sqlite is not."""
    return sorted(glob.glob(os.path.join(data_dir or config.DATA_DIR, "demos_*.sqlite")))


def resolve_demo_db(db=None, player=None, data_dir=None):
    """Pick a demo file for tools like replay.py: an explicit path wins, then the
    player's own file, then the most recently changed demo file."""
    if db:
        return db
    if player:
        return demo_db_path(player, data_dir)
    files = find_demo_dbs(data_dir)
    legacy = os.path.join(data_dir or config.DATA_DIR, "demos.sqlite")
    if os.path.exists(legacy):
        files.append(legacy)
    return max(files, key=os.path.getmtime) if files else legacy

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    player         TEXT,
    started_at     TEXT,
    game_version   TEXT,
    seed           INTEGER,
    difficulty     TEXT,
    settings_json  TEXT,
    outcome        TEXT,      -- win / out_of_bounds / timeout / quit
    time_s         REAL,
    fuel           REAL,
    fuel_thrust    REAL,
    fuel_rotate    REAL,
    hits           INTEGER,
    score          REAL,      -- lower is better (only meaningful within a hit tier)
    n_ticks        INTEGER,
    notes          TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    episode_id     INTEGER REFERENCES episodes(id),
    tick           INTEGER,
    t              REAL,
    ship_x REAL, ship_y REAL, ship_vx REAL, ship_vy REAL,
    ship_heading   REAL,      -- radians, 0 = right, pi/2 = up
    ship_omega     REAL,
    fuel           REAL,
    hits           INTEGER,
    invulnerable   INTEGER,
    action_turn    INTEGER,   -- -1 right, 0 none, +1 left (NULL on final row)
    action_thrust  INTEGER,   -- 0/1 (NULL on final row)
    key_left       INTEGER,   -- raw keyboard state (humans only)
    key_right      INTEGER,
    key_thrust     INTEGER,
    asteroids_json TEXT,      -- format 1 only (older files): full JSON list of dicts
    asteroids_z    BLOB,      -- format 2: zlib JSON [[id, x, y, vx, vy, spent], ...]
    PRIMARY KEY (episode_id, tick)
);
CREATE TABLE IF NOT EXISTS asteroids (
    episode_id     INTEGER REFERENCES episodes(id),
    id             INTEGER,   -- asteroid id within the run
    r              REAL,      -- radius
    ax             REAL,      -- constant acceleration
    ay             REAL,
    first_tick     INTEGER,   -- first tick it was recorded
    PRIMARY KEY (episode_id, id)
);
"""


STEP_COLUMNS = (
    "episode_id", "tick", "t", "ship_x", "ship_y", "ship_vx", "ship_vy", "ship_heading",
    "ship_omega", "fuel", "hits", "invulnerable", "action_turn", "action_thrust",
    "key_left", "key_right", "key_thrust", "asteroids_json", "asteroids_z",
)


def decode_asteroids(step, static):
    """Rebuild the list of asteroid dicts for one step row (either format).
    `static` maps asteroid id -> (r, ax, ay) for the step's episode (format 2 only)."""
    blob = step.get("asteroids_z")
    if blob is None:                                     # format 1
        out = json.loads(step["asteroids_json"])
        for a in out:
            a.setdefault("spent", False)
        return out
    out = []
    for i, x, y, vx, vy, spent in json.loads(zlib.decompress(blob)):
        r, ax, ay = static[i]
        out.append({"id": i, "x": x, "y": y, "vx": vx, "vy": vy,
                    "ax": ax, "ay": ay, "r": r, "spent": bool(spent)})
    return out


class Recorder:
    def __init__(self, path, held_out_seeds=True):
        """held_out_seeds=True refuses to record on seeds reserved for evaluation
        (see game/seeds.py). Only the main asteroid game needs this."""
        self.held_out_seeds = held_out_seeds
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.executescript(SCHEMA)
        cols = [r[1] for r in self.con.execute("PRAGMA table_info(steps)")]
        if "asteroids_z" not in cols:      # file made before format 2: add the column
            self.con.execute("ALTER TABLE steps ADD COLUMN asteroids_z BLOB")
            self.con.commit()
        self.decimals = config.RECORD_DECIMALS
        self.episode_id = None
        self._rows = []
        self._static = {}      # asteroid id -> (r, ax, ay, first_tick) for this run

    def start_episode(self, game, player, game_version, notes=None):
        if self.held_out_seeds:
            check_demo_seed(game.seed)   # never record on held-out evaluation seeds
        cur = self.con.execute(
            "INSERT INTO episodes (player, started_at, game_version, seed, difficulty,"
            " settings_json, outcome, notes) VALUES (?,?,?,?,?,?,?,?)",
            (player, time.strftime("%Y-%m-%d %H:%M:%S"), game_version, game.seed,
             game.difficulty, json.dumps(game.s), "running", notes),
        )
        self.con.commit()
        self.episode_id = cur.lastrowid
        self._rows = []
        self._static = {}
        return self.episode_id

    def log_step(self, state, action=None, keys=None):
        """state = game.get_state() taken BEFORE applying `action`."""
        sh = state["ship"]
        k = keys or {}
        nd = self.decimals
        moving = []
        for a in state["asteroids"]:
            if a["id"] not in self._static:
                self._static[a["id"]] = (a["r"], a["ax"], a["ay"], state["tick"])
            moving.append([a["id"], round(a["x"], nd), round(a["y"], nd),
                           round(a["vx"], nd), round(a["vy"], nd), int(a.get("spent", False))])
        self._rows.append((
            self.episode_id, state["tick"], state["t"],
            sh["x"], sh["y"], sh["vx"], sh["vy"], sh["heading"], sh["omega"],
            state["fuel"], state["hits"], int(state["invulnerable"]),
            None if action is None else int(action.turn),
            None if action is None else int(action.thrust),
            k.get("left"), k.get("right"), k.get("thrust"),
            None,
            zlib.compress(json.dumps(moving, separators=(",", ":")).encode(), 9),
        ))

    def end_episode(self, game, outcome=None):
        self.con.executemany(
            "INSERT INTO steps (" + ", ".join(STEP_COLUMNS) + ") VALUES ("
            + ",".join("?" * len(STEP_COLUMNS)) + ")", self._rows)
        self.con.executemany(
            "INSERT INTO asteroids (episode_id, id, r, ax, ay, first_tick) VALUES (?,?,?,?,?,?)",
            [(self.episode_id, i) + v for i, v in self._static.items()])
        self.con.execute(
            "UPDATE episodes SET outcome=?, time_s=?, fuel=?, fuel_thrust=?, fuel_rotate=?,"
            " hits=?, score=?, n_ticks=? WHERE id=?",
            (outcome or game.outcome, game.t, game.fuel, game.fuel_thrust, game.fuel_rotate,
             game.hits, game.score(), game.tick, self.episode_id),
        )
        self.con.commit()
        self._rows = []
        self._static = {}

    def best_for_seed(self, seed, difficulty):
        """Best successful run on this seed+difficulty: (player, hits, time, fuel, score)."""
        row = self.con.execute(
            "SELECT player, hits, time_s, fuel, score FROM episodes"
            " WHERE seed=? AND difficulty=? AND outcome='win'"
            " ORDER BY hits ASC, score ASC LIMIT 1", (seed, difficulty)).fetchone()
        return row

    def close(self):
        self.con.close()


def load_episode(path, episode_id):
    """Return (episode_row_dict, list_of_step_dicts) for replay or analysis."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    ep = con.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
    if ep is None:
        raise KeyError(f"No episode {episode_id} in {path}")
    steps = [dict(r) for r in con.execute(
        "SELECT * FROM steps WHERE episode_id=? ORDER BY tick", (episode_id,))]
    static = {}
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='asteroids'").fetchone():
        static = {r["id"]: (r["r"], r["ax"], r["ay"]) for r in con.execute(
            "SELECT id, r, ax, ay FROM asteroids WHERE episode_id=?", (episode_id,))}
    for st in steps:
        st["asteroids"] = decode_asteroids(st, static)
        st.pop("asteroids_json", None)
        st.pop("asteroids_z", None)
    con.close()
    ep = dict(ep)
    ep["settings"] = json.loads(ep["settings_json"])
    return ep, steps
