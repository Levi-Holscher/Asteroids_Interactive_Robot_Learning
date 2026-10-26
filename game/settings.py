"""Snapshot of config.py values as a plain dict, so each episode can record exactly
which settings it was played with and code can override settings without editing config.py."""

import copy

import config

_KEYS = [
    "TICK_HZ", "MAX_EPISODE_TIME",
    "FIELD_WIDTH", "FIELD_HEIGHT", "START_POS", "START_HEADING_RANDOM", "START_HEADING_DEG",
    "GOAL_GATE", "BOTTOM_IS_WALL",
    "SHIP_RADIUS", "THRUST_ACCEL", "SPEED_CAP_ENABLED", "MAX_SPEED", "LINEAR_DRAG",
    "ROTATION_MODE", "ROTATE_STEP_DEG", "ROTATE_STEP_TICKS", "ROTATE_REPEAT_TICKS",
    "ROTATE_RATE_DEG", "ROTATE_ACCEL_DEG", "ROTATE_MAX_RATE_DEG",
    "FUEL_PER_THRUST_SECOND", "FUEL_PER_ROTATE_STEP", "FUEL_PER_ROTATE_SECOND",
    "INVULN_TIME", "DESTROY_ASTEROID_ON_HIT",
    "W_TIME", "W_FUEL", "REF_TIME", "REF_FUEL",
    "DIFFICULTIES", "DEFAULT_DIFFICULTY", "START_SAFE_RADIUS", "VERTICAL_SPEED_FRAC",
    "ASTEROID_DESPAWN_MARGIN",
]


def default_settings(**overrides):
    """Return a dict of game settings from config.py, with optional overrides.

    Example: default_settings(SPEED_CAP_ENABLED=False, GOAL_GATE=(1.0, 0.5))
    """
    s = {k: copy.deepcopy(getattr(config, k)) for k in _KEYS}
    for k, v in overrides.items():
        if k not in s:
            raise KeyError(f"Unknown setting: {k}")
        s[k] = v
    return s
