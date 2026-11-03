"""Dodge Run tests. Run with:  python -m pytest -q"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.dodge import DodgeGame, dodge_settings, WIN, GAME_VERSION
from game.recorder import Recorder, load_episode
from game.sim import Action


def empty_settings(**kw):
    s = dodge_settings(**kw)
    for d in s["DIFFICULTIES"].values():
        d["n_start"] = 0
        d["spawn_per_sec"] = 0.0
    return s


def test_survives_full_duration():
    g = DodgeGame(seed=1, settings=empty_settings())
    while not g.done:
        g.step(Action())
    assert g.outcome == WIN
    assert math.isclose(g.t, g.s["DURATION"], abs_tol=1e-9)
    assert g.hits == 0 and g.fuel == 0


def test_left_right_and_walls():
    s = empty_settings()
    g = DodgeGame(seed=1, settings=s)
    x0 = g.ship.x
    g.step(Action(turn=1))                       # LEFT key = +1 -> moves left
    assert g.ship.x < x0
    for _ in range(200):
        g.step(Action(turn=1))
    assert math.isclose(g.ship.x, s["SHIP_RADIUS"])   # stopped at the wall, not out
    assert not g.done or g.outcome == WIN
    for _ in range(300):
        g.step(Action(turn=-1))
    assert math.isclose(g.ship.x, s["FIELD_WIDTH"] - s["SHIP_RADIUS"])
    assert g.ship.y == s["SHIP_Y"]                # never leaves its lane


def test_direct_mode_has_no_momentum():
    g = DodgeGame(seed=1, settings=empty_settings())
    g.step(Action(turn=1))
    x = g.ship.x
    g.step(Action(turn=0))
    assert g.ship.x == x


def test_accel_mode_has_momentum():
    g = DodgeGame(seed=1, settings=empty_settings(MOVE_MODE="accel"))
    for _ in range(5):
        g.step(Action(turn=1))
    x = g.ship.x
    g.step(Action(turn=0))
    assert g.ship.x < x                           # keeps sliding


def test_fuel_counts_movement_time():
    g = DodgeGame(seed=1, settings=empty_settings())
    for _ in range(20):
        g.step(Action(turn=-1))
    assert math.isclose(g.fuel, 1.0)              # 20 ticks at 20 Hz = 1 s


def test_field_independent_of_player():
    g1, g2 = DodgeGame(seed=9, difficulty="hard"), DodgeGame(seed=9, difficulty="hard")
    for i in range(200):
        g1.step(Action(0))
        g2.step(Action(1 if (i // 10) % 2 else -1))
        assert ([(a.id, a.x, a.y) for a in g1.field.asteroids]
                == [(a.id, a.x, a.y) for a in g2.field.asteroids])


def test_asteroids_fall_and_get_hit():
    g = DodgeGame(seed=3, difficulty="hard")
    hits = 0
    while not g.done:
        g.step(Action())
        hits = g.hits
    assert hits > 0                               # standing still in hard gets hit
    assert all(a.vy < 0.2 for a in g.field.asteroids if not a.spent)


def test_recorder_roundtrip(tmp_path):
    db = str(tmp_path / "d.sqlite")
    rec = Recorder(db)
    g = DodgeGame(seed=5, difficulty="easy")
    eid = rec.start_episode(g, "tester", GAME_VERSION)
    while not g.done:
        a = Action(1 if g.tick % 40 < 20 else -1)
        rec.log_step(g.get_state(), a, {"left": int(a.turn == 1), "right": int(a.turn == -1), "thrust": 0})
        g.step(a)
    rec.log_step(g.get_state(), None)
    rec.end_episode(g)
    rec.close()
    ep, steps = load_episode(db, eid)
    assert ep["settings"]["GAME"] == "dodge"
    assert ep["outcome"] == WIN and len(steps) == g.tick + 1
