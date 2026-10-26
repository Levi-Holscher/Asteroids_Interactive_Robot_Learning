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


def test_field_is_deterministic_and_independent_of_actions():
    g1 = AsteroidGame(seed=42, difficulty="hard")
    g2 = AsteroidGame(seed=42, difficulty="hard")
    for i in range(150):
        g1.step(Action(0, False))
        g2.step(Action(1 if i % 3 else -1, i % 2 == 0))  # very different play
        p1 = [(a.id, a.x, a.y, a.vx, a.vy) for a in g1.field.asteroids]
        p2 = [(a.id, a.x, a.y, a.vx, a.vy) for a in g2.field.asteroids]
        assert p1 == p2          # hits only mark asteroids "spent"; motion is identical
        if g1.done or g2.done:
            break
    assert math.isclose(AsteroidGame(seed=42).ship.heading, AsteroidGame(seed=42).ship.heading)


def test_asteroids_bounce_elastically_and_do_not_overlap():
    s = empty_settings()
    g = AsteroidGame(seed=1, settings=s)
    a = g.field._new(0.0, 0.5, 2.0, 0.2, 0.0, 0.0, 0.0, 0.05)
    b = g.field._new(0.0, 0.7, 2.0, -0.2, 0.0, 0.0, 0.0, 0.05)
    p0 = a.mass * a.vx + b.mass * b.vx
    e0 = a.mass * a.vx ** 2 + b.mass * b.vx ** 2
    for _ in range(40):
        g.step(Action())
        assert math.hypot(a.x - b.x, a.y - b.y) >= a.r + b.r - 1e-9
    assert a.vx < 0 < b.vx                         # they bounced apart
    assert math.isclose(a.mass * a.vx + b.mass * b.vx, p0, abs_tol=1e-9)
    assert math.isclose(a.mass * a.vx ** 2 + b.mass * b.vx ** 2, e0, rel_tol=1e-9)


def test_no_overlaps_in_a_busy_field():
    g = AsteroidGame(seed=3, difficulty="hard")
    worst = 0.0
    for _ in range(200):
        g.step(Action())
        ast = g.field.asteroids
        for i in range(len(ast)):
            for j in range(i + 1, len(ast)):
                a, b = ast[i], ast[j]
                worst = max(worst, a.r + b.r - math.hypot(a.x - b.x, a.y - b.y))
        if g.done:
            break
    assert worst < 0.01      # at most a hair of overlap in rare 3-way pile-ups


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
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0, GOAL_GATE=(1.35, 0.3))
    g = AsteroidGame(seed=1, settings=s)
    while not g.done:
        g.step(Action(thrust=True))
    assert g.outcome == OUT_OF_BOUNDS
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0, GOAL_GATE=(0.8, 0.3))
    g = AsteroidGame(seed=1, settings=s)
    while not g.done:
        g.step(Action(thrust=True))
    assert g.outcome == WIN


def test_hit_counts_once_with_invulnerability():
    s = empty_settings(START_HEADING_RANDOM=False, START_HEADING_DEG=90.0)
    g = AsteroidGame(seed=1, settings=s)
    # park two overlapping asteroids right on the ship
    g.field._new(0.0, 0.8, 0.12, 0, 0, 0, 0, 0.05)
    g.field._new(0.0, 0.8, 0.22, 0, 0, 0, 0, 0.05)
    g.step(Action())
    assert g.hits == 1 and g.invulnerable()
    assert all(a.spent for a in g.field.active())   # both marked harmless
    g.field._new(g.t, 0.8, 0.15, 0, 0, 0, 0, 0.05)
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
