"""Held-out seeds (task D2): demos can never be recorded on evaluation seeds."""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import play
from game import AsteroidGame
from game.recorder import Recorder
from game.seeds import ReservedSeedError, is_reserved, random_demo_seed
from game.sim import GAME_VERSION


def test_eval_seed_lists_are_reserved_and_separate():
    assert len(config.TEST_SEEDS) == 100 and len(config.VALIDATION_SEEDS) == 100
    assert all(is_reserved(s) for s in config.TEST_SEEDS + config.VALIDATION_SEEDS)
    assert not set(config.TEST_SEEDS) & set(config.VALIDATION_SEEDS)


def test_boundary():
    assert not is_reserved(config.RESERVED_SEED_START - 1)
    assert is_reserved(config.RESERVED_SEED_START)


def test_random_demo_seed_never_reserved():
    rng = random.Random(0)
    assert not any(is_reserved(random_demo_seed(rng)) for _ in range(10_000))


def test_recorder_refuses_reserved_seed(tmp_path):
    rec = Recorder(str(tmp_path / "t.sqlite"))
    with pytest.raises(ReservedSeedError):
        rec.start_episode(AsteroidGame(seed=config.TEST_SEEDS[0]), "tester", GAME_VERSION)
    rec.start_episode(AsteroidGame(seed=123), "tester", GAME_VERSION)   # normal seed is fine
    rec.close()


def test_recorder_guard_can_be_turned_off(tmp_path):
    """Dodge Run isn't part of the experiment, so play_dodge.py turns the guard off."""
    rec = Recorder(str(tmp_path / "t.sqlite"), held_out_seeds=False)
    rec.start_episode(AsteroidGame(seed=config.TEST_SEEDS[0]), "tester", GAME_VERSION)
    rec.close()


def test_play_refuses_reserved_seed_before_opening_window(capsys):
    code = play.main(["--player", "tester", "--seed", str(config.TEST_SEEDS[0])])
    assert code == 2
    assert "held out" in capsys.readouterr().out
