"""Lattice Gate tests. Run with:  python -m pytest -q"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.grid import (DOWN, LEFT, RIGHT, STAY, TIMEOUT, UP, WIN, GridGame,
                       GridRecorder, grid_settings, load_grid_episode)


def empty(**kw):
    s = grid_settings(**kw)
    for d in s["DIFFICULTIES"].values():
        d["density"] = 0.0
    return s


def test_walk_to_gate_and_win():
    g = GridGame(seed=1, settings=empty())
    g0, gw = g.gate
    while g.col < g0:
        g.step(RIGHT)
    while g.col >= g0 + gw:
        g.step(LEFT)
    while not g.done:
        g.step(UP)
    assert g.outcome == WIN and g.hits == 0
    assert g.turn == g.s["ROWS"] + abs(g.s["START_COL"] - g.col)


def test_walls_block_and_top_wall_outside_gate_blocks():
    g = GridGame(seed=1, settings=empty())
    g.step(DOWN)
    assert (g.col, g.row) == (g.s["START_COL"], 0)        # bottom wall blocks
    for _ in range(20):
        g.step(LEFT)
    assert g.col == 0                                      # side wall blocks
    g0, gw = g.gate
    if g0 > 0:                                             # col 0 is outside the gate
        for _ in range(30):
            g.step(UP)
        assert g.row == g.s["ROWS"] - 1 and not g.done


def test_timeout():
    g = GridGame(seed=1, settings=empty(MAX_TURNS=5))
    while not g.done:
        g.step(STAY)
    assert g.outcome == TIMEOUT and g.turn == 5


def test_lanes_move_predictably_and_wrap():
    g = GridGame(seed=4, difficulty="hard")
    lane = g.lanes[0]
    st = lane.starts[0]
    c0 = g.lane_col(lane, st, 0)
    c_after = g.lane_col(lane, st, lane.period)
    assert (c_after - c0) % g.L == lane.direction % g.L
    assert g.lane_col(lane, st, lane.period * g.L) == c0  # full wrap


def test_field_independent_of_player():
    a, b = GridGame(seed=8), GridGame(seed=8)
    for t in range(30):
        a.step(STAY)
        b.step([UP, LEFT, RIGHT, DOWN][t % 4])
        assert a.asteroids_at(a.turn) == b.asteroids_at(b.turn)


def test_hit_counts_and_spends_asteroid():
    g = GridGame(seed=1, settings=empty())
    from game.grid import Lane
    g.lanes = [Lane(row=1, direction=1, period=1, starts=[g.s["START_COL"] + g.M - 1], ids=[99])]
    g.step(UP)                      # asteroid slides into the ship's new cell
    assert g.hits == 1 and 99 in g.spent
    g.step(STAY)
    assert g.hits == 1              # spent asteroid is harmless


def test_swap_counts_as_hit():
    g = GridGame(seed=1, settings=empty(START_ROW=2, SAFE_ROWS=[]))
    from game.grid import Lane
    c = g.s["START_COL"]
    # asteroid directly right of the ship, moving left; ship moves right -> they swap
    g.lanes = [Lane(row=2, direction=-1, period=1, starts=[c + 1 + g.M], ids=[7])]
    g.step(RIGHT)
    assert g.hits == 1


def test_oracle_finds_hit_free_paths_and_they_work():
    solved = 0
    for seed in range(30):
        for diff in ("easy", "medium", "hard"):
            g = GridGame(seed=seed, difficulty=diff)
            path = g.shortest_safe_path()
            if path is None:
                continue
            solved += 1
            for a in path:
                g.step(a)
            assert g.outcome == WIN and g.hits == 0, (seed, diff)
    assert solved >= 80             # nearly every field has a hit-free route


def test_recorder_roundtrip(tmp_path):
    db = str(tmp_path / "g.sqlite")
    rec = GridRecorder(db)
    g = GridGame(seed=2, difficulty="easy")
    rec.start_episode(g, "tester")
    path = g.shortest_safe_path() or [UP] * 20
    for a in path:
        rec.log_step(g.get_state(), a)
        g.step(a)
        if g.done:
            break
    rec.log_step(g.get_state(), None)
    rec.end_episode(g)
    rec.close()
    ep, steps = load_grid_episode(db, 1)
    assert ep["outcome"] == g.outcome and len(steps) == g.turn + 1
    assert ep["settings"]["GAME"] == "grid"
