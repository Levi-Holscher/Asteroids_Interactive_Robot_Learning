"""
Held-out seeds: which asteroid fields may be used for demos and which are kept for
evaluation only. The numbers live in config.py.

    from game.seeds import is_reserved, random_demo_seed
    seed = random_demo_seed()          # always safe to record on
    is_reserved(900_042)               # True: never record on this one

The Recorder refuses to record a run on a reserved seed, so this holds for humans
(play.py) and bots alike.
"""

import random

import config


class ReservedSeedError(ValueError):
    """Raised when someone tries to record a demo on a held-out seed."""


def is_reserved(seed) -> bool:
    """True if `seed` is held out for evaluation and must never appear in a demo."""
    return int(seed) >= config.RESERVED_SEED_START


def random_demo_seed(rng=random) -> int:
    """A random seed that is safe to record demos on."""
    return rng.randrange(config.RESERVED_SEED_START)


def check_demo_seed(seed):
    """Raise ReservedSeedError if `seed` is held out."""
    if is_reserved(seed):
        raise ReservedSeedError(
            f"Seed {seed} is held out for evaluation (seeds >= "
            f"{config.RESERVED_SEED_START:,}). Pick a lower seed, or play with --no-record.")
