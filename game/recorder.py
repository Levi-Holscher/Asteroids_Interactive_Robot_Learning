"""
Records games to a SQLite database (a single file, default data/demos.sqlite).

Tables
------
episodes : one row per run (player, seed, difficulty, settings, outcome, time, fuel, hits, score)
steps    : one row per tick (ship state, the action taken on that tick, fuel/hits so far,
           and a JSON list of every asteroid's raw state)

Each step row stores the state *before* the action and the action taken, i.e. the
(s_t, a_t) pair a learning algorithm wants. The final state after the last action is
stored as an extra row with action NULL.

Open it in Python with sqlite3 or pandas:
    import sqlite3, pandas as pd
    con = sqlite3.connect("data/demos.sqlite")
    eps = pd.read_sql("SELECT * FROM episodes", con)
"""

import json
import os
import sqlite3
import time

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
    asteroids_json TEXT,      -- [{"id","x","y","vx","vy","ax","ay","r"}, ...]
    PRIMARY KEY (episode_id, tick)
);
"""


class Recorder:
    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.executescript(SCHEMA)
        self.episode_id = None
        self._rows = []

    def start_episode(self, game, player, game_version, notes=None):
        cur = self.con.execute(
            "INSERT INTO episodes (player, started_at, game_version, seed, difficulty,"
            " settings_json, outcome, notes) VALUES (?,?,?,?,?,?,?,?)",
            (player, time.strftime("%Y-%m-%d %H:%M:%S"), game_version, game.seed,
             game.difficulty, json.dumps(game.s), "running", notes),
        )
        self.con.commit()
        self.episode_id = cur.lastrowid
        self._rows = []
        return self.episode_id

    def log_step(self, state, action=None, keys=None):
        """state = game.get_state() taken BEFORE applying `action`."""
        sh = state["ship"]
        k = keys or {}
        self._rows.append((
            self.episode_id, state["tick"], state["t"],
            sh["x"], sh["y"], sh["vx"], sh["vy"], sh["heading"], sh["omega"],
            state["fuel"], state["hits"], int(state["invulnerable"]),
            None if action is None else int(action.turn),
            None if action is None else int(action.thrust),
            k.get("left"), k.get("right"), k.get("thrust"),
            json.dumps(state["asteroids"], separators=(",", ":")),
        ))

    def end_episode(self, game, outcome=None):
        self.con.executemany(
            "INSERT INTO steps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self._rows)
        self.con.execute(
            "UPDATE episodes SET outcome=?, time_s=?, fuel=?, fuel_thrust=?, fuel_rotate=?,"
            " hits=?, score=?, n_ticks=? WHERE id=?",
            (outcome or game.outcome, game.t, game.fuel, game.fuel_thrust, game.fuel_rotate,
             game.hits, game.score(), game.tick, self.episode_id),
        )
        self.con.commit()
        self._rows = []

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
    for st in steps:
        st["asteroids"] = json.loads(st.pop("asteroids_json"))
    con.close()
    ep = dict(ep)
    ep["settings"] = json.loads(ep["settings_json"])
    return ep, steps
