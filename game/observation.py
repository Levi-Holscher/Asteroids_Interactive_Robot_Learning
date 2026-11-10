"""
Observation builder: turns a raw game state into the fixed-size arrays the pilot sees.

    from game import AsteroidGame
    from game.observation import build_observation, flatten

    game = AsteroidGame(seed=123)
    obs = build_observation(game.get_state(), game.s)
    obs.ship   # (8,)      the ship's own state
    obs.ast    # (K, 8)    one row per asteroid slot, nearest first
    obs.mask   # (K,)      1 = the pilot sees this slot, 0 = hidden / empty (int8)
    obs.ids    # (K,)      asteroid id in each slot, -1 for empty slots
    x = flatten(obs)       # one 1-D vector for a neural network

We call this an "observation" (the usual RL word for what the agent sees each step)
rather than "features", to avoid confusion with the hand-made reward features used in
inverse RL methods.

THE CONTRACT (other code relies on this; change it only after telling the team)
-------------------------------------------------------------------------------
Input
    state     : dict from AsteroidGame.get_state(), or rebuilt from a recorded step row
    settings  : the game settings dict (field size, ship radius). For recorded runs, pass
                the settings saved with that episode.
    K         : number of asteroid slots (default config.OBS_MAX_ASTEROIDS)
    horizon   : look-ahead time in seconds for t* and d_min (default config.OBS_HORIZON)

Output: an Observation with four numpy arrays

    ship (8,) float32, columns SHIP_COLUMNS:
        vx, vy            ship velocity (wu/s)
        cos_h, sin_h      heading as a unit vector (avoids the 359 deg -> 0 deg jump)
        gap_left          distance from the ship's edge to each wall (wu); the left,
        gap_right         right and bottom walls end the run, the top is the goal
        gap_bottom
        gap_top

    ast (K, 8) float32, columns AST_COLUMNS, one row per slot, nearest asteroid first:
        dx, dy            asteroid center minus ship center (wu)
        dvx, dvy          asteroid velocity minus ship velocity (wu/s)
        r                 asteroid radius (wu)
        t_star            time of closest approach (s), clipped to [0, horizon]
        d_min             edge-to-edge gap at t_star (wu); <= 0 means "will hit if
                          nobody changes course"
        gap               edge-to-edge gap right now (wu); <= 0 means touching
      Empty slots (fewer than K asteroids) are all zeros.

    mask (K,) int8:      1 = real asteroid the pilot may use, 0 = empty or pruned
    ids  (K,) int64:     asteroid id per slot, -1 for empty slots

Rules
    - Spent asteroids (already hit the ship, now harmless) are left out.
    - Asteroids outside the walls are included: the player can see them coming.
    - Slots are filled nearest-first by `gap`; if there are more than K asteroids, the
      farthest are dropped.
    - t_star and d_min assume straight-line motion at the current relative velocity
      (asteroid acceleration and bounces are ignored; fine over a ~2.5 s horizon).
    - Pruning (focus model / closest / soonest / random) ONLY sets entries of `mask` to 0
      via `with_mask()`. It never reorders or removes rows, so the pilot code is identical
      in every experiment condition.
    - Everything is computed from the raw recorded state, so old demos can be
      re-processed whenever this file changes.
"""

from typing import NamedTuple, Optional

import numpy as np

import config

SHIP_COLUMNS = ("vx", "vy", "cos_h", "sin_h",
                "gap_left", "gap_right", "gap_bottom", "gap_top")
AST_COLUMNS = ("dx", "dy", "dvx", "dvy", "r", "t_star", "d_min", "gap")

SHIP_DIM = len(SHIP_COLUMNS)
AST_DIM = len(AST_COLUMNS)


class Observation(NamedTuple):
    ship: np.ndarray   # (SHIP_DIM,) float32
    ast: np.ndarray    # (K, AST_DIM) float32
    mask: np.ndarray   # (K,) int8, 1 = visible to the pilot
    ids: np.ndarray    # (K,) int64, -1 = empty slot

    @property
    def K(self):
        return self.mask.shape[0]


def build_observation(state, settings, K: Optional[int] = None,
                      horizon: Optional[float] = None) -> Observation:
    """Build the pilot's observation from a raw game state. See the module docstring
    for the exact contract.

    STUB (task F1): returns arrays of the right shapes and types with every slot empty,
    so the pilot lane can start coding against it. Task F2 fills in the real numbers.
    """
    K = config.OBS_MAX_ASTEROIDS if K is None else int(K)
    horizon = config.OBS_HORIZON if horizon is None else float(horizon)
    if K < 1:
        raise ValueError(f"K must be at least 1, got {K}")

    ship = np.zeros(SHIP_DIM, dtype=np.float32)
    ast = np.zeros((K, AST_DIM), dtype=np.float32)
    mask = np.zeros(K, dtype=np.int8)
    ids = np.full(K, -1, dtype=np.int64)
    # TODO (F2): fill ship, ast, mask, ids from state, settings and horizon.
    return Observation(ship, ast, mask, ids)


def with_mask(obs: Observation, keep) -> Observation:
    """Return a copy of `obs` where only slots with keep[i] true stay visible.

    Used by every pruning rule. Empty slots stay hidden no matter what `keep` says."""
    keep = np.asarray(keep, dtype=bool)
    if keep.shape != obs.mask.shape:
        raise ValueError(f"keep has shape {keep.shape}, expected {obs.mask.shape}")
    return obs._replace(mask=obs.mask * keep.astype(np.int8))


def flatten(obs: Observation) -> np.ndarray:
    """One 1-D float32 vector for the pilot: ship, then masked asteroid rows, then mask.

    Hidden slots become zeros, and the mask is appended so the network can tell
    "hidden" apart from "an asteroid that happens to be at zero". Length is
    flat_size(K)."""
    visible = obs.ast * obs.mask[:, None]
    return np.concatenate([obs.ship, visible.ravel(), obs.mask.astype(np.float32)]).astype(np.float32)


def flat_size(K: Optional[int] = None) -> int:
    """Length of flatten(obs) for K slots."""
    K = config.OBS_MAX_ASTEROIDS if K is None else int(K)
    return SHIP_DIM + K * AST_DIM + K
