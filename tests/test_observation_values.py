"""Value tests for game/observation.py (task F2): the real numbers in each column.

Most tests use a hand-made state with one or two asteroids, so the right answer can be
worked out on paper. Ship radius 0.03 and asteroid radius 0.05 -> they touch when their
centers are 0.08 apart."""

import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from game import Action, AsteroidGame
from game.observation import AST_COLUMNS, SHIP_COLUMNS, build_observation, state_from_step
from game.recorder import Recorder, load_episode
from game.settings import default_settings
from game.sim import GAME_VERSION

S = default_settings(FIELD_WIDTH=1.6, FIELD_HEIGHT=3.0, SHIP_RADIUS=0.03)
TOUCH = 0.03 + 0.05
A = {name: i for i, name in enumerate(AST_COLUMNS)}
SH = {name: i for i, name in enumerate(SHIP_COLUMNS)}


def rock(id, x, y, vx=0.0, vy=0.0, r=0.05, spent=False):
    return {"id": id, "x": x, "y": y, "vx": vx, "vy": vy, "ax": 0.0, "ay": 0.0,
            "r": r, "spent": spent}


def state(rocks, x=0.8, y=1.0, vx=0.0, vy=0.0, heading=math.pi / 2):
    return {"t": 0.0, "tick": 0,
            "ship": {"x": x, "y": y, "vx": vx, "vy": vy, "heading": heading, "omega": 0.0},
            "fuel": 0.0, "hits": 0, "invulnerable": False, "asteroids": rocks}


def row(rocks, horizon=2.5, **ship):
    obs = build_observation(state(rocks, **ship), S, K=5, horizon=horizon)
    return obs.ast[0]


# --- ship row -------------------------------------------------------------------------

def test_ship_row():
    obs = build_observation(state([], x=0.5, y=1.0, vx=0.1, vy=-0.2, heading=0.0), S, K=3)
    s = obs.ship
    assert s[SH["vx"]] == pytest.approx(0.1) and s[SH["vy"]] == pytest.approx(-0.2)
    assert s[SH["cos_h"]] == pytest.approx(1.0) and s[SH["sin_h"]] == pytest.approx(0.0)
    assert s[SH["gap_left"]] == pytest.approx(0.5 - 0.03)
    assert s[SH["gap_right"]] == pytest.approx(1.6 - 0.5 - 0.03)
    assert s[SH["gap_bottom"]] == pytest.approx(1.0 - 0.03)
    assert s[SH["gap_top"]] == pytest.approx(3.0 - 1.0 - 0.03)


def test_heading_is_a_unit_vector():
    obs = build_observation(state([], heading=math.radians(135)), S, K=1)
    assert obs.ship[SH["cos_h"]] == pytest.approx(-math.sqrt(0.5), abs=1e-6)
    assert obs.ship[SH["sin_h"]] == pytest.approx(math.sqrt(0.5), abs=1e-6)


def test_no_asteroids_gives_empty_slots():
    obs = build_observation(state([]), S, K=3)
    assert obs.mask.tolist() == [0, 0, 0] and obs.ids.tolist() == [-1, -1, -1]
    assert np.all(obs.ast == 0)


# --- one asteroid: t* and d_min worked out by hand ------------------------------------

def test_head_on():
    # 1.0 above the ship, falling at 0.5 wu/s -> centers meet at t = 2 s
    r = row([rock(7, 0.8, 2.0, vy=-0.5)])
    assert r[A["dx"]] == pytest.approx(0.0) and r[A["dy"]] == pytest.approx(1.0)
    assert r[A["dvy"]] == pytest.approx(-0.5)
    assert r[A["r"]] == pytest.approx(0.05)
    assert r[A["gap"]] == pytest.approx(1.0 - TOUCH)
    assert r[A["t_star"]] == pytest.approx(2.0)
    assert r[A["d_min"]] == pytest.approx(-TOUCH)          # < 0: will hit


def test_passing_by():
    # 1.0 to the left, 0.5 above, moving right at 1 wu/s -> closest at t = 1 s, 0.5 away
    r = row([rock(1, -0.2, 1.5, vx=1.0)])
    assert r[A["t_star"]] == pytest.approx(1.0)
    assert r[A["d_min"]] == pytest.approx(0.5 - TOUCH)


def test_moving_away_is_closest_now():
    r = row([rock(1, 0.8, 1.5, vy=+0.3)])
    assert r[A["t_star"]] == 0.0
    assert r[A["d_min"]] == pytest.approx(r[A["gap"]])


def test_no_relative_motion():
    # asteroid and ship move together -> gap never changes
    r = row([rock(1, 0.8, 1.5, vx=0.2, vy=0.1)], vx=0.2, vy=0.1)
    assert r[A["dvx"]] == pytest.approx(0.0) and r[A["dvy"]] == pytest.approx(0.0)
    assert r[A["t_star"]] == 0.0
    assert r[A["d_min"]] == pytest.approx(r[A["gap"]])


def test_ship_velocity_counts():
    # still asteroid above, ship flying up at 0.5 -> same as the head-on case
    r = row([rock(1, 0.8, 2.0)], vy=0.5)
    assert r[A["dvy"]] == pytest.approx(-0.5)
    assert r[A["t_star"]] == pytest.approx(2.0)
    assert r[A["d_min"]] == pytest.approx(-TOUCH)


def test_horizon_clips_t_star():
    # would meet at t = 4 s, but we only look 2.5 s ahead: closest within the horizon
    # is the position at 2.5 s, 2.0 - 0.5 * 2.5 = 0.75 above the ship
    r = row([rock(1, 0.8, 3.0, vy=-0.5)], horizon=2.5)
    assert r[A["t_star"]] == pytest.approx(2.5)
    assert r[A["d_min"]] == pytest.approx(0.75 - TOUCH)


def test_d_min_never_above_gap():
    rng = np.random.default_rng(0)
    rocks = [rock(i, *rng.uniform([0, 0], [1.6, 3.0]), *rng.uniform(-0.4, 0.4, 2))
             for i in range(30)]
    obs = build_observation(state(rocks), S, K=30)
    assert np.all(obs.ast[:, A["d_min"]] <= obs.ast[:, A["gap"]] + 1e-6)
    assert np.all((obs.ast[:, A["t_star"]] >= 0) & (obs.ast[:, A["t_star"]] <= 2.5))


# --- which asteroids, and in which order ----------------------------------------------

def test_spent_asteroids_left_out():
    obs = build_observation(state([rock(1, 0.8, 1.2, spent=True), rock(2, 0.8, 1.5)]), S, K=3)
    assert obs.ids.tolist() == [2, -1, -1]
    assert obs.mask.tolist() == [1, 0, 0]


def test_sorted_by_edge_gap_not_center_distance():
    # big rock: center 0.40 away, edge gap 0.40 - 0.03 - 0.30 = 0.07
    # small rock: center 0.20 away, edge gap 0.20 - 0.03 - 0.05 = 0.12
    obs = build_observation(state([rock(1, 0.8, 1.2), rock(2, 0.8, 0.6, r=0.30)]), S, K=3)
    assert obs.ids.tolist()[:2] == [2, 1]


def test_more_than_K_drops_the_farthest():
    rocks = [rock(i, 0.8, 1.0 + 0.2 * (i + 1)) for i in range(6)]     # id 0 is nearest
    obs = build_observation(state(rocks[::-1]), S, K=4)                 # input order shuffled
    assert obs.ids.tolist() == [0, 1, 2, 3]
    assert np.all(np.diff(obs.ast[:, A["gap"]]) >= 0)


def test_asteroids_outside_walls_included():
    obs = build_observation(state([rock(1, -0.1, 1.0)]), S, K=2)
    assert obs.ids.tolist() == [1, -1]


# --- real games and recorded demos ----------------------------------------------------

@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_real_game_states(difficulty):
    g = AsteroidGame(seed=3, difficulty=difficulty)
    for _ in range(40):
        g.step(Action(0, True))
    st = g.get_state()
    obs = build_observation(st, g.s)
    live = [a for a in st["asteroids"] if not a["spent"]]
    n = min(obs.K, len(live))
    assert obs.mask.sum() == n
    assert np.all(obs.ids[:n] >= 0) and np.all(obs.ids[n:] == -1)
    assert np.all(np.diff(obs.ast[:n, A["gap"]]) >= 0)
    assert np.all(np.isfinite(obs.ast)) and np.all(np.isfinite(obs.ship))


def test_d_min_predicts_the_sim_without_acceleration():
    # With no asteroid acceleration, bounces or ship thrust, t* and d_min are exact:
    # step the real game forward and measure the closest gap for each tracked rock.
    diffs = {k: dict(v, accel_max=0.0) for k, v in config.DIFFICULTIES.items()}
    s = default_settings(DIFFICULTIES=diffs, ASTEROID_COLLISIONS=False, LINEAR_DRAG=0.0)
    g = AsteroidGame(seed=11, difficulty="medium", settings=s)
    obs = build_observation(g.get_state(), g.s, K=10, horizon=2.0)
    best = {int(i): math.inf for i in obs.ids if i >= 0}
    for _ in range(int(2.0 * s["TICK_HZ"]) + 1):
        st = g.get_state()
        sh = st["ship"]
        for a in st["asteroids"]:
            if a["id"] in best:
                gap = math.hypot(a["x"] - sh["x"], a["y"] - sh["y"]) - a["r"] - s["SHIP_RADIUS"]
                best[a["id"]] = min(best[a["id"]], gap)
        g.step(Action(0, False))
    for slot, i in enumerate(obs.ids):
        if i >= 0:
            # sampled every tick, so allow the distance covered in half a tick
            speed = math.hypot(*obs.ast[slot, [A["dvx"], A["dvy"]]])
            assert best[int(i)] == pytest.approx(obs.ast[slot, A["d_min"]],
                                                 abs=speed / s["TICK_HZ"] / 2 + 1e-3)


def test_recorded_demo_gives_same_observation(tmp_path):
    db = str(tmp_path / "t.sqlite")
    rec = Recorder(db)
    g = AsteroidGame(seed=5, difficulty="medium")
    eid = rec.start_episode(g, "tester", GAME_VERSION)
    live = []
    for i in range(30):
        a = Action(1 if i % 5 == 0 else 0, i % 2 == 0)
        st = g.get_state()
        live.append(build_observation(st, g.s))
        rec.log_step(st, a)
        g.step(a)
    rec.end_episode(g)
    rec.close()

    ep, steps = load_episode(db, eid)
    tol = 10 ** -config.RECORD_DECIMALS * 5   # positions/velocities are rounded on disk
    for st, want in zip(steps, live):
        got = build_observation(state_from_step(st), ep["settings"])
        assert np.allclose(got.ship, want.ship, atol=1e-6)
        n = int(want.mask.sum())
        assert got.mask.sum() == n
        # rounding can swap two rocks at almost the same distance, so compare by id
        assert set(got.ids[:n].tolist()) == set(want.ids[:n].tolist())
        order = {i: k for k, i in enumerate(got.ids[:n].tolist())}
        for k, i in enumerate(want.ids[:n].tolist()):
            g_row = got.ast[order[i]]
            w_row = want.ast[k]
            assert np.allclose(g_row[[A["dx"], A["dy"], A["dvx"], A["dvy"], A["r"], A["gap"]]],
                               w_row[[A["dx"], A["dy"], A["dvx"], A["dvy"], A["r"], A["gap"]]],
                               atol=tol)
