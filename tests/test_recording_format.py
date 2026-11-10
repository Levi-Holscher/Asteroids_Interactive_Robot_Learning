"""Compact recording format (format 2) and backwards compatibility with format 1."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from game import Action, AsteroidGame
from game.recorder import Recorder, load_episode
from game.sim import GAME_VERSION

TOL = 0.6 * 10 ** -config.RECORD_DECIMALS     # rounding error is at most half a digit


def record(db, seed=7, ticks=60):
    """Record a short run; return (episode_id, the true states that were logged)."""
    rec = Recorder(db)
    g = AsteroidGame(seed=seed, difficulty="medium")
    eid = rec.start_episode(g, "tester", GAME_VERSION)
    truth = []
    for i in range(ticks):
        if g.done:
            break
        a = Action(1 if i % 7 == 0 else 0, i % 3 == 0)
        truth.append(g.get_state())
        rec.log_step(truth[-1], a)
        g.step(a)
    truth.append(g.get_state())
    rec.log_step(truth[-1], None)
    rec.end_episode(g)
    rec.close()
    return eid, truth


def test_roundtrip_matches_game_state(tmp_path):
    db = str(tmp_path / "t.sqlite")
    eid, truth = record(db)
    _, steps = load_episode(db, eid)
    assert len(steps) == len(truth)
    for st, tr in zip(steps, truth):
        assert [a["id"] for a in st["asteroids"]] == [a["id"] for a in tr["asteroids"]]
        for a, b in zip(st["asteroids"], tr["asteroids"]):
            assert set(a) == set(b)
            for k in ("x", "y", "vx", "vy"):
                assert abs(a[k] - b[k]) <= TOL
            for k in ("r", "ax", "ay", "spent"):
                assert a[k] == b[k]                  # stored once, exactly
        assert "asteroids_z" not in st and "asteroids_json" not in st


def test_files_are_much_smaller_than_format_1(tmp_path):
    db = str(tmp_path / "t.sqlite")
    _, truth = record(db, ticks=200)
    assert len(truth) > 50
    with sqlite3.connect(db) as con:
        stored = sum(len(b) for (b,) in con.execute("SELECT asteroids_z FROM steps"))
    old = sum(len(json.dumps(s["asteroids"], separators=(",", ":"))) for s in truth)
    assert stored * 6 < old


OLD_SCHEMA = """
CREATE TABLE episodes (id INTEGER PRIMARY KEY AUTOINCREMENT, player TEXT, started_at TEXT,
    game_version TEXT, seed INTEGER, difficulty TEXT, settings_json TEXT, outcome TEXT,
    time_s REAL, fuel REAL, fuel_thrust REAL, fuel_rotate REAL, hits INTEGER, score REAL,
    n_ticks INTEGER, notes TEXT);
CREATE TABLE steps (episode_id INTEGER, tick INTEGER, t REAL, ship_x REAL, ship_y REAL,
    ship_vx REAL, ship_vy REAL, ship_heading REAL, ship_omega REAL, fuel REAL, hits INTEGER,
    invulnerable INTEGER, action_turn INTEGER, action_thrust INTEGER, key_left INTEGER,
    key_right INTEGER, key_thrust INTEGER, asteroids_json TEXT,
    PRIMARY KEY (episode_id, tick));
"""


def make_format_1_file(db):
    ast = [{"id": 3, "x": 0.123456789, "y": 1.5, "vx": -0.2, "vy": 0.01,
            "ax": 0.001, "ay": 0.0, "r": 0.04}]          # old files had no "spent" key
    with sqlite3.connect(db) as con:
        con.executescript(OLD_SCHEMA)
        con.execute("INSERT INTO episodes (player, seed, difficulty, settings_json, outcome)"
                    " VALUES ('old', 5, 'medium', '{}', 'win')")
        con.execute("INSERT INTO steps VALUES (1,0,0,0.8,0.15,0,0,1.57,0,0,0,0,0,1,0,0,1,?)",
                    (json.dumps(ast),))
    return ast


def test_reads_format_1_files(tmp_path):
    db = str(tmp_path / "old.sqlite")
    ast = make_format_1_file(db)
    _, steps = load_episode(db, 1)
    assert steps[0]["asteroids"] == [dict(ast[0], spent=False)]   # full precision kept


def test_recording_into_a_format_1_file_upgrades_it(tmp_path):
    db = str(tmp_path / "old.sqlite")
    make_format_1_file(db)
    eid, truth = record(db, ticks=10)
    _, old_steps = load_episode(db, 1)
    _, new_steps = load_episode(db, eid)
    assert old_steps[0]["asteroids"][0]["x"] == 0.123456789
    assert len(new_steps) == len(truth)
