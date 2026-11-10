"""Contract tests for game/observation.py (task F1): shapes, types, masking.
Value tests for the real numbers come with task F2."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import AsteroidGame
from game.observation import (AST_DIM, SHIP_DIM, AST_COLUMNS, SHIP_COLUMNS, Observation,
                              build_observation, flat_size, flatten, with_mask)


def obs_for(seed=1, **kw):
    g = AsteroidGame(seed=seed, difficulty="medium")
    return build_observation(g.get_state(), g.s, **kw)


@pytest.mark.parametrize("K", [1, 3, 10, 25])
def test_shapes_and_types(K):
    obs = obs_for(K=K)
    assert isinstance(obs, Observation)
    assert obs.ship.shape == (SHIP_DIM,) and obs.ship.dtype == np.float32
    assert obs.ast.shape == (K, AST_DIM) and obs.ast.dtype == np.float32
    assert obs.mask.shape == (K,) and obs.mask.dtype == np.int8
    assert obs.ids.shape == (K,) and obs.ids.dtype == np.int64
    assert obs.K == K


def test_column_names_match_dims():
    assert len(SHIP_COLUMNS) == SHIP_DIM == 8
    assert len(AST_COLUMNS) == AST_DIM == 8


def test_default_K_comes_from_config():
    import config
    assert obs_for().K == config.OBS_MAX_ASTEROIDS


def test_bad_K_rejected():
    with pytest.raises(ValueError):
        obs_for(K=0)


def test_empty_slots_are_consistent():
    obs = obs_for(K=10)
    empty = obs.ids == -1
    assert np.all(obs.mask[empty] == 0)
    assert np.all(obs.ast[empty] == 0)


def test_with_mask_only_changes_mask():
    obs = obs_for(K=5)
    obs = obs._replace(mask=np.ones(5, np.int8))      # pretend all 5 slots are real
    pruned = with_mask(obs, [True, False, True, False, False])
    assert pruned.mask.tolist() == [1, 0, 1, 0, 0]
    assert np.array_equal(pruned.ast, obs.ast)
    assert np.array_equal(pruned.ids, obs.ids)
    assert obs.mask.tolist() == [1, 1, 1, 1, 1]            # original untouched


def test_with_mask_never_reveals_empty_slots():
    obs = obs_for(K=4)                                     # stub: all slots empty
    assert with_mask(obs, [True] * 4).mask.tolist() == [0, 0, 0, 0]


def test_with_mask_wrong_shape_rejected():
    with pytest.raises(ValueError):
        with_mask(obs_for(K=4), [True] * 3)


def test_flatten_length_and_hiding():
    K = 3
    obs = obs_for(K=K)
    obs = obs._replace(ast=np.ones((K, AST_DIM), np.float32),
                       mask=np.array([1, 0, 1], np.int8))
    x = flatten(obs)
    assert x.shape == (flat_size(K),) and x.dtype == np.float32
    rows = x[SHIP_DIM:SHIP_DIM + K * AST_DIM].reshape(K, AST_DIM)
    assert np.all(rows[0] == 1) and np.all(rows[1] == 0) and np.all(rows[2] == 1)
    assert x[-K:].tolist() == [1, 0, 1]
