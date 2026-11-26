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

    # recorded demos: same function, via state_from_step()
    ep, steps = load_episode(path, episode_id)
    obs = build_observation(state_from_step(steps[i]), ep["settings"])

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
    for the exact contract. For a recorded step, use build_observation(state_from_step(step),
    episode["settings"])."""
    K = config.OBS_MAX_ASTEROIDS if K is None else int(K)
    horizon = config.OBS_HORIZON if horizon is None else float(horizon)
    if K < 1:
        raise ValueError(f"K must be at least 1, got {K}")

    W, H = settings["FIELD_WIDTH"], settings["FIELD_HEIGHT"]
    ship_r = settings["SHIP_RADIUS"]
    sh = state["ship"]
    x, y = sh["x"], sh["y"]

    # --- ship row: velocity, heading, gap from the ship's edge to each wall ---
    ship = np.array([sh["vx"], sh["vy"],
                     np.cos(sh["heading"]), np.sin(sh["heading"]),
                     x - ship_r,            # gap_left
                     W - x - ship_r,        # gap_right
                     y - ship_r,            # gap_bottom
                     H - y - ship_r],       # gap_top
                    dtype=np.float32)

    ast = np.zeros((K, AST_DIM), dtype=np.float32)
    mask = np.zeros(K, dtype=np.int8)
    ids = np.full(K, -1, dtype=np.int64)

    rocks = [a for a in state["asteroids"] if not a.get("spent", False)]
    if not rocks:
        return Observation(ship, ast, mask, ids)

    # --- asteroid rows, one numpy column per quantity (n = number of live rocks) ---
    a_id = np.array([a["id"] for a in rocks], dtype=np.int64)
    dx = np.array([a["x"] for a in rocks]) - x
    dy = np.array([a["y"] for a in rocks]) - y
    dvx = np.array([a["vx"] for a in rocks]) - sh["vx"]
    dvy = np.array([a["vy"] for a in rocks]) - sh["vy"]
    r = np.array([a["r"] for a in rocks])
    touch = r + ship_r                      # center distance at which they touch

    gap = np.hypot(dx, dy) - touch

    # Time of closest approach for straight-line relative motion p(t) = d + v t:
    # |p(t)|^2 is smallest at t* = -(d . v) / |v|^2. Clip to [0, horizon]: a rock that
    # is moving away has t* = 0 (closest right now). |v| ~ 0 means the gap never changes.
    v2 = dvx ** 2 + dvy ** 2
    moving = v2 > 1e-12
    t_star = np.zeros_like(dx)
    t_star[moving] = -(dx[moving] * dvx[moving] + dy[moving] * dvy[moving]) / v2[moving]
    t_star = np.clip(t_star, 0.0, horizon)
    d_min = np.hypot(dx + dvx * t_star, dy + dvy * t_star) - touch

    # Nearest first by edge-to-edge gap; ties broken by id so the order is reproducible.
    order = np.lexsort((a_id, gap))[:K]
    n = len(order)
    ast[:n] = np.stack([dx, dy, dvx, dvy, r, t_star, d_min, gap], axis=1)[order]
    mask[:n] = 1
    ids[:n] = a_id[order]
    return Observation(ship, ast, mask, ids)


def state_from_step(step) -> dict:
    """Rebuild a get_state()-style dict from one recorded step (from load_episode()),
    so build_observation() works the same on live games and on recorded demos."""
    return {
        "t": step["t"],
        "tick": step["tick"],
        "ship": {"x": step["ship_x"], "y": step["ship_y"],
                 "vx": step["ship_vx"], "vy": step["ship_vy"],
                 "heading": step["ship_heading"], "omega": step["ship_omega"]},
        "fuel": step["fuel"],
        "hits": step["hits"],
        "invulnerable": bool(step["invulnerable"]),
        "asteroids": step["asteroids"],
    }


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
