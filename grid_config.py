"""
Settings for LATTICE GATE (play_grid.py), the grid version of the asteroid game.

The ship moves one cell at a time on a grid. Asteroids slide along horizontal lanes at
fixed speeds and wrap around (like Frogger), so the whole game is a small, fully
predictable grid world - the kind of problem classic inverse RL (Abbeel & Ng) can solve
exactly. Reach the gate in the top wall; the gate moves between fields.
"""

GAME = "grid"

# ----------------------------------------------------------------------------
# Grid
# ----------------------------------------------------------------------------
COLS = 9                     # cells across
ROWS = 15                    # cells tall
CELL = 0.2                   # world units per cell (field = 1.8 x 3.0, like the main game)
START_COL = 4                # ship starts bottom-center
START_ROW = 0
SAFE_ROWS = [0, 1, 7, 14]    # rows with no asteroid lanes (start, middle rest row, top)
LANE_MARGIN = 3              # hidden cells on each side of a lane (asteroids wrap out of view)
VIEW_MARGIN_FRAC = 0.20      # visible area outside the walls, fraction of field width

# ----------------------------------------------------------------------------
# Turns
# ----------------------------------------------------------------------------
# "turn"     - each key press is one move; asteroids step once per move (default;
#              clean demos, and the game is an exact grid MDP)
# "realtime" - the world steps REALTIME_HZ times per second with whatever key is held
PLAY_MODE = "turn"
REALTIME_HZ = 4
ANIM_TIME = 0.12             # seconds to animate one step (visual only)
MAX_TURNS = 80               # run ends as a timeout after this many moves

# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------
# Wins beat losses; fewer hits always beat more hits (hit tiers); within a tier, fewer
# turns is better. Score = turns taken (lower is better).
# Hitting an asteroid doesn't end the run; that asteroid turns harmless ("spent").

# ----------------------------------------------------------------------------
# Difficulty
# ----------------------------------------------------------------------------
# density   - fraction of lane cells holding an asteroid
# periods   - a lane moves one cell every `period` turns (1 = fast, 3 = slow)
# gate_width- gate size in cells (its position is random per seed)
DIFFICULTIES = {
    "easy":   dict(density=0.18, periods=[2, 3], gate_width=3),
    "medium": dict(density=0.25, periods=[1, 2, 3], gate_width=2),
    "hard":   dict(density=0.32, periods=[1, 1, 2], gate_width=2),
}
DEFAULT_DIFFICULTY = "medium"

# ----------------------------------------------------------------------------
# Recording
# ----------------------------------------------------------------------------
import os as _os
DB_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "grid_demos.sqlite")
RECORD_BY_DEFAULT = True
