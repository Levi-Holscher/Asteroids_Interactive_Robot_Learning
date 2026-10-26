"""Run with:  python -m pytest -q   (from the asteroid_game folder)"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import Action, AsteroidGame, default_settings
from game.recorder import Recorder, load_episode
from game.sim import GAME_VERSION, OUT_OF_BOUNDS, TIMEOUT, WIN


def empty_settings(**kw):
    s = default_settings(**kw)
    for d in s["DIFFICULTIES"].values():
        d["n_start"] = 0
        d["spawn_per_sec"] = 0.0
    return s


def asteroid_signature(g):
    return [(a.id, round(a.x0, 9), round(a.y0, 9), round(a.t0, 9)) for a in g.field.asteroids]


def test_field_is_deterministic_and_independent_of_actions():
    g1 = AsteroidGame(seed=42, difficulty="hard")
    g2 = AsteroidGame(seed=42, difficulty="hard")
    seen1, seen2 = set(), set()
    for i in range(200):
        g1.step(Action(0, False))
        g2.step(Action(1 if i % 3 else -1, i % 2 == 0))  # very different play
        seen1 |= {(a.id, a.x0, a.y0, a.t0) for a in g1.field.asteroids}
        seen2 |= {(a.id, a.x0, a.y0, a.t0) for a in g2.field.asteroids}
        if g1.done or g2.done:
            break
    # every asteroid that exists in both runs is identical (hits only remove asteroids)
    common = {x[0] for x in seen1} & {x[0] for x in seen2}
    d1 = {x[0]: x for x in seen1}
    d2 = {x[0]: x for x in seen2}
    assert common and all(d1[i] == d2[i] for i in common)
    assert math.isclose(AsteroidGame(seed=42).ship.heading, AsteroidGame(seed=42).ship.heading)


def test_step_rotation_exact_and_no_momentum():
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0)
    g = AsteroidGame(seed=1, settings=s)
    g.step(Action(turn=1))            # one tap
    for _ in range(5):
        g.step(Action(turn=0))
    assert math.isclose(math.degrees(g.ship.heading), 90 + s["ROTATE_STEP_DEG"], abs_tol=1e-9)
    assert g.ship.omega == 0.0
    assert math.isclose(g.fuel, s["FUEL_PER_ROTATE_STEP"])


def test_holding_turn_repeats_steps():
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0)
    g = AsteroidGame(seed=1, settings=s)
    for _ in range(s["ROTATE_REPEAT_TICKS"] * 3):
        g.step(Action(turn=-1))
    assert math.isclose(math.degrees(g.ship.heading), 90 - 3 * s["ROTATE_STEP_DEG"], abs_tol=1e-9)


def test_speed_cap():
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0)
    g = AsteroidGame(seed=1, settings=s)
    while not g.done:
        g.step(Action(thrust=True))
        assert g.speed() <= s["MAX_SPEED"] + 1e-9
    assert g.outcome == WIN


def test_straight_crossing_time_in_target_range():
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0)
    g = AsteroidGame(seed=1, settings=s)
    while not g.done:
        g.step(Action(thrust=True))
    assert g.outcome == WIN
    assert 4.0 <= g.t <= 10.0, g.t


def test_no_cap_reaches_higher_speed():
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0, SPEED_CAP_ENABLED=False)
    g = AsteroidGame(seed=1, settings=s)
    while not g.done:
        g.step(Action(thrust=True))
    assert g.speed() > s["MAX_SPEED"]


def test_side_wall_is_out_of_bounds():
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=0.0)
    g = AsteroidGame(seed=1, settings=s)
    while not g.done:
        g.step(Action(thrust=True))
    assert g.outcome == OUT_OF_BOUNDS


def test_gate_miss_is_out_and_hit_is_win():
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0, GOAL_GATE=(1.6, 0.3))
    g = AsteroidGame(seed=1, settings=s)
    while not g.done:
        g.step(Action(thrust=True))
    assert g.outcome == OUT_OF_BOUNDS
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0, GOAL_GATE=(1.0, 0.3))
    g = AsteroidGame(seed=1, settings=s)
    while not g.done:
        g.step(Action(thrust=True))
    assert g.outcome == WIN


def test_hit_counts_once_with_invulnerability():
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0)
    g = AsteroidGame(seed=1, settings=s)
    # park two overlapping asteroids right on the ship
    g.field._new(0.0, 1.0, 0.15, 0, 0, 0, 0, 0.05)
    g.field._new(0.0, 1.0, 0.20, 0, 0, 0, 0, 0.05)
    g.step(Action())
    assert g.hits == 1 and g.invulnerable()
    assert not g.field.active()          # both destroyed
    g.field._new(g.t, 1.0, 0.15, 0, 0, 0, 0, 0.05)
    g.step(Action())
    assert g.hits == 1                   # still invulnerable


def test_timeout():
    s = empty_settings(MAX_EPISODE_TIME=1.0)
    g = AsteroidGame(seed=1, settings=s)
    while not g.done:
        g.step(Action())
    assert g.outcome == TIMEOUT


def test_rank_key_orders_tiers():
    s = empty_settings()
    a, b = AsteroidGame(seed=1, settings=s), AsteroidGame(seed=1, settings=s)
    a.outcome, a.hits, a.t, a.fuel = WIN, 0, 30.0, 20.0
    b.outcome, b.hits, b.t, b.fuel = WIN, 1, 3.0, 1.0
    assert a.rank_key() < b.rank_key()


def test_recorder_roundtrip(tmp_path):
    db = str(tmp_path / "t.sqlite")
    rec = Recorder(db)
    g = AsteroidGame(seed=7, difficulty="easy")
    eid = rec.start_episode(g, "tester", GAME_VERSION)
    while not g.done:
        a = Action(0, True)
        rec.log_step(g.get_state(), a, {"left": 0, "right": 0, "thrust": 1})
        g.step(a)
    rec.log_step(g.get_state(), None)
    rec.end_episode(g)
    rec.close()
    ep, steps = load_episode(db, eid)
    assert ep["seed"] == 7 and ep["outcome"] == g.outcome
    assert len(steps) == g.tick + 1
    assert steps[-1]["action_turn"] is None
    assert isinstance(steps[0]["asteroids"], list)
