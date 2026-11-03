"""
Settings for DODGE RUN (play_dodge.py). The original game's settings stay in config.py.

Dodge Run: the ship sits near the bottom and can only slide left/right. Asteroids rain
down from the top. Survive DURATION seconds with as few hits as possible.

Same units as config.py: world units (wu), seconds, (0, 0) = bottom-left, +y up.
"""

GAME = "dodge"

# ----------------------------------------------------------------------------
# Timing
# ----------------------------------------------------------------------------
TICK_HZ = 20                 # logic / decision / recording rate
DURATION = 30.0              # seconds to survive = a completed run

# ----------------------------------------------------------------------------
# Field (same size as the main game so the window looks the same)
# ----------------------------------------------------------------------------
FIELD_WIDTH = 1.6
FIELD_HEIGHT = 3.0
VIEW_MARGIN_FRAC = 0.20      # visible area outside the walls, fraction of width

# ----------------------------------------------------------------------------
# Ship
# ----------------------------------------------------------------------------
SHIP_Y = 0.30                # the ship's fixed height
START_X = 0.8                # starting x (center)
SHIP_RADIUS = 0.030

# Movement mode:
#   "direct" - constant sideways speed while a key is held, stops instantly on release
#              (no momentum: purely reactive, mistakes don't carry over)
#   "accel"  - sideways acceleration with momentum (toggle with M between runs)
MOVE_MODE = "direct"
MOVE_SPEED = 0.70            # wu/s in direct mode (full width in ~2.3 s)
MOVE_ACCEL = 3.0             # wu/s^2 in accel mode
MOVE_MAX_SPEED = 0.70        # wu/s cap in accel mode
MOVE_DRAG = 2.0              # per-second damping in accel mode when no key is held

# Side walls: the ship just stops at them (touching a wall doesn't end the run)

# ----------------------------------------------------------------------------
# Hits, fuel and scoring
# ----------------------------------------------------------------------------
INVULN_TIME = 1.0            # seconds of invulnerability after a hit
FUEL_PER_MOVE_SECOND = 1.0   # "fuel" = seconds spent moving

# Score = number of hits (lower is better). Movement ("fuel") is tracked and recorded
# but not scored: in this game moving is how you dodge, so less isn't necessarily better.

# ----------------------------------------------------------------------------
# Asteroids / difficulty
# ----------------------------------------------------------------------------
# Asteroids spawn above the visible area and fall (with some sideways drift and a
# little downward acceleration). They bounce off each other like in the main game.
# Same seed = same asteroids, regardless of what the player does.
DIFFICULTIES = {
    "easy": dict(
        n_start=14, spawn_per_sec=2.2,
        speed_min=0.35, speed_max=0.55, accel_max=0.03,
        radius_min=0.035, radius_max=0.070,
    ),
    "medium": dict(
        n_start=22, spawn_per_sec=3.5,
        speed_min=0.40, speed_max=0.70, accel_max=0.05,
        radius_min=0.030, radius_max=0.070,
    ),
    "hard": dict(
        n_start=32, spawn_per_sec=5.0,
        speed_min=0.45, speed_max=0.85, accel_max=0.07,
        radius_min=0.030, radius_max=0.075,
    ),
}
DEFAULT_DIFFICULTY = "medium"
SIDE_DRIFT_FRAC = 0.25       # max sideways speed as a fraction of fall speed
START_CLEAR_HEIGHT = 0.9     # no asteroid starts within this height above the ship
ASTEROID_DESPAWN_MARGIN = 0.15
ASTEROID_COLLISIONS = True
ASTEROID_RESTITUTION = 1.0

# ----------------------------------------------------------------------------
# Recording
# ----------------------------------------------------------------------------
import os as _os
DB_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "dodge_demos.sqlite")
RECORD_BY_DEFAULT = True
