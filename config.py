"""
All tunable game settings live here.

Units: the field is measured in "world units" (wu). Default field is 1.6 wide x 3.0 tall,
(0, 0) is the bottom-left corner, +y is up. Time is in seconds. Angles are in degrees
in this file (0 deg = pointing right, 90 deg = pointing up, counter-clockwise positive).

Change a value here and restart the game; nothing else needs to be edited.
"""

# ----------------------------------------------------------------------------
# Timing
# ----------------------------------------------------------------------------
TICK_HZ = 20                 # game logic / decision / recording rate (ticks per second)
RENDER_FPS = 60              # screen refresh rate; positions are interpolated between ticks
MAX_EPISODE_TIME = 60.0      # seconds before the run ends as a timeout (loss)

# ----------------------------------------------------------------------------
# Field
# ----------------------------------------------------------------------------
FIELD_WIDTH = 1.6
FIELD_HEIGHT = 3.0
START_POS = (0.8, 0.15)      # ship always starts here (x, y)
START_HEADING_RANDOM = True  # random 0-360 deg start heading
START_HEADING_DEG = 90.0     # used when START_HEADING_RANDOM is False

# Goal at the top edge.
#   None            -> the whole top edge is the goal
#   (center_x, w)   -> only a gate of width w centered at center_x is the goal;
#                      touching the top edge outside the gate counts as out of bounds
GOAL_GATE = None
# GOAL_GATE = (0.8, 0.5)     # example: centered gate, 0.5 wu wide
# GOAL_GATE = (1.15, 0.4)    # example: offset gate

# Edges that end the run as "out of bounds" when touched
BOTTOM_IS_WALL = True        # left and right are always walls

# ----------------------------------------------------------------------------
# Ship
# ----------------------------------------------------------------------------
SHIP_RADIUS = 0.030          # collision radius (wu)
THRUST_ACCEL = 0.35          # wu/s^2 while thrust is held
SPEED_CAP_ENABLED = True     # toggle in-game with M (between runs)
MAX_SPEED = 0.42             # wu/s; ~7.3 s straight shot bottom->top at full speed
LINEAR_DRAG = 0.0            # per-second velocity damping (0 = none, 0.3 = noticeable)

# Rotation mode:
#   "step"       - each tap rotates a fixed angle using a two-burst impulse (start spin,
#                  stop spin), so there is no leftover rotational momentum. Holding the
#                  key repeats steps.
#   "continuous" - rotates at a constant rate while held, stops instantly on release
#   "momentum"   - angular acceleration while held, keeps spinning after release
#                  (needs counter-thrust to stop; hard!)
ROTATION_MODE = "step"
ROTATE_STEP_DEG = 22.5       # step mode: degrees per tap (22.5 -> 16 headings)
ROTATE_STEP_TICKS = 2        # step mode: ticks a step takes to complete (the two bursts)
ROTATE_REPEAT_TICKS = 4      # step mode: when held, a new step every N ticks
ROTATE_RATE_DEG = 180.0      # continuous mode: deg/s
ROTATE_ACCEL_DEG = 360.0     # momentum mode: deg/s^2
ROTATE_MAX_RATE_DEG = 360.0  # momentum mode: spin-rate cap

# ----------------------------------------------------------------------------
# Fuel (measured in "seconds of main-thruster burn")
# ----------------------------------------------------------------------------
FUEL_PER_THRUST_SECOND = 1.0
FUEL_PER_ROTATE_STEP = 0.05  # step mode: cost of the two-burst impulse
FUEL_PER_ROTATE_SECOND = 0.25  # continuous / momentum modes: cost while a rotate key is held

# ----------------------------------------------------------------------------
# Hits and scoring
# ----------------------------------------------------------------------------
INVULN_TIME = 1.0            # seconds of invulnerability after an asteroid hit
# An asteroid that hits the ship becomes "spent": harmless and drawn dim, but it keeps
# moving and bouncing so the field plays out the same for everyone on a seed.

# Ranking: successful runs always beat failed runs. Among successes, fewer hits is always
# better (hit "tiers"). Within a tier, lower score is better:
#   score = W_TIME * time / REF_TIME + W_FUEL * fuel / REF_FUEL
# REF_* are "typical" values so the two terms are about the same size; tune later.
# Note: with the speed cap on, a fuel-efficient run is "burn to cruise speed, then coast",
# so typical fuel is ~1-3 while typical time is ~8-12 s.
W_TIME = 0.5
W_FUEL = 0.5
REF_TIME = 10.0
REF_FUEL = 2.0

# ----------------------------------------------------------------------------
# Asteroids / difficulty
# ----------------------------------------------------------------------------
# Each asteroid moves with constant acceleration: p(t) = p0 + v0*t + 0.5*a*t^2.
# They spawn from the left/right edges (crossing traffic) and some from the top.
# The field depends only on the seed - never on what the player does - so the same
# seed always produces the same asteroids.
DIFFICULTIES = {
    "easy": dict(
        n_start=20, spawn_per_sec=1.6,
        speed_min=0.08, speed_max=0.20, accel_max=0.02,
        radius_min=0.025, radius_max=0.050, top_spawn_frac=0.15,
    ),
    "medium": dict(
        n_start=32, spawn_per_sec=2.8,
        speed_min=0.10, speed_max=0.28, accel_max=0.03,
        radius_min=0.022, radius_max=0.055, top_spawn_frac=0.2,
    ),
    "hard": dict(
        n_start=48, spawn_per_sec=4.5,
        speed_min=0.12, speed_max=0.36, accel_max=0.04,
        radius_min=0.020, radius_max=0.060, top_spawn_frac=0.25,
    ),
}
DEFAULT_DIFFICULTY = "medium"
START_SAFE_RADIUS = 0.35     # no asteroid starts within this distance of START_POS
VERTICAL_SPEED_FRAC = 0.35   # side spawns: max vertical speed as a fraction of horizontal
ASTEROID_DESPAWN_MARGIN = 0.3  # removed once this far outside the field
ASTEROID_COLLISIONS = True   # asteroids bounce off each other
ASTEROID_RESTITUTION = 1.0   # 1.0 = perfectly elastic bounce, 0.5 = loses energy

# ----------------------------------------------------------------------------
# Display
# ----------------------------------------------------------------------------
PIXELS_PER_UNIT = 260        # window field size = FIELD * this (lower it if the window is too tall)
HUD_WIDTH = 260              # px panel on the right
SHOW_ASTEROID_IDS = False
SHOW_VELOCITY_VECTOR = True

# ----------------------------------------------------------------------------
# Recording
# ----------------------------------------------------------------------------
import os as _os
DB_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "demos.sqlite")
RECORD_BY_DEFAULT = True
