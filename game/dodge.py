"""
DODGE RUN - headless game logic (no pygame), same style as game/sim.py.

    game = DodgeGame(seed=123, difficulty="medium")
    while not game.done:
        game.step(Action(turn=+1))      # +1 = slide left, -1 = slide right, 0 = stay

It uses the same Action type as the main game so recording, replay and learning code
can be shared: Action.turn is the move direction (LEFT key = +1, RIGHT key = -1, just
like rotation in the main game) and Action.thrust is ignored.
The full discrete action set is DODGE_ACTIONS (3 actions).
"""

import copy
import math
import random
from typing import Optional

import dodge_config
from game.sim import Action, AsteroidField, Ship, StepResult

GAME_VERSION = "dodge-0.1.0"

RUNNING = "running"
WIN = "win"          # survived the full duration

DODGE_ACTIONS = [Action(-1, False), Action(0, False), Action(1, False)]

_KEYS = [
    "GAME", "TICK_HZ", "DURATION", "FIELD_WIDTH", "FIELD_HEIGHT", "VIEW_MARGIN_FRAC",
    "SHIP_Y", "START_X", "SHIP_RADIUS",
    "MOVE_MODE", "MOVE_SPEED", "MOVE_ACCEL", "MOVE_MAX_SPEED", "MOVE_DRAG",
    "INVULN_TIME", "FUEL_PER_MOVE_SECOND",
    "DIFFICULTIES", "DEFAULT_DIFFICULTY", "SIDE_DRIFT_FRAC", "START_CLEAR_HEIGHT",
    "ASTEROID_DESPAWN_MARGIN", "ASTEROID_COLLISIONS", "ASTEROID_RESTITUTION",
]


def dodge_settings(**overrides):
    """Settings dict from dodge_config.py, with optional overrides."""
    s = {k: copy.deepcopy(getattr(dodge_config, k)) for k in _KEYS}
    for k, v in overrides.items():
        if k not in s:
            raise KeyError(f"Unknown dodge setting: {k}")
        s[k] = v
    # Keys the shared renderer / asteroid physics expect:
    s["START_POS"] = (s["START_X"], s["SHIP_Y"])
    s["GOAL_GATE"] = None
    s["BOTTOM_IS_WALL"] = False
    s["START_SAFE_RADIUS"] = 0.0
    return s


class DodgeField(AsteroidField):
    """Same asteroid physics as the main game (constant acceleration + bounces),
    but everything falls from the top."""

    def _initial_field(self):
        vm = self.vm
        y_lo = self.s["SHIP_Y"] + self.s["START_CLEAR_HEIGHT"]
        y_hi = self.H + vm
        # n_start = count inside the walls above the clear zone; fill the margins too
        inside_area = self.W * (self.H - y_lo)
        full_area = (self.W + 2 * vm) * (y_hi - y_lo)
        target = int(round(self.d["n_start"] * full_area / max(inside_area, 1e-9)))
        placed, tries = 0, 0
        while placed < target and tries < 40000:
            tries += 1
            r = self._radius()
            x = self.rng.uniform(-vm + r, self.W + vm - r)
            y = self.rng.uniform(y_lo + r, y_hi - r)
            if self._overlaps(x, y, r):
                continue
            self._new(0.0, x, y, *self._fall_motion(), r)
            placed += 1

    def _fall_motion(self):
        sp = self._speed()
        amax = self.d["accel_max"]
        vx = self.rng.uniform(-1, 1) * sp * self.s["SIDE_DRIFT_FRAC"]
        vy = -sp
        ax = self.rng.uniform(-0.5, 0.5) * amax
        ay = -self.rng.uniform(0, 1) * amax
        return vx, vy, ax, ay

    def spawn_tick(self, t):
        lam = self.d["spawn_per_sec"] * self.dt
        n, p, L = 0, 1.0, math.exp(-lam)
        while True:
            p *= self.rng.random()
            if p <= L:
                break
            n += 1
        for _ in range(n):
            r = self._radius()
            x = self.rng.uniform(-0.5 * self.vm, self.W + 0.5 * self.vm)
            self._new(t, x, self.H + self.vm + r, *self._fall_motion(), r)


class DodgeGame:
    def __init__(self, seed=None, difficulty=None, settings=None):
        self.s = settings if settings is not None else dodge_settings()
        self.difficulty = difficulty or self.s["DEFAULT_DIFFICULTY"]
        if self.difficulty not in self.s["DIFFICULTIES"]:
            raise ValueError(f"Unknown difficulty {self.difficulty!r}")
        self.seed = seed if seed is not None else random.randrange(1_000_000)
        self.reset()

    def reset(self, seed=None):
        if seed is not None:
            self.seed = seed
        s = self.s
        self.dt = 1.0 / s["TICK_HZ"]
        self.W, self.H = s["FIELD_WIDTH"], s["FIELD_HEIGHT"]
        self.field = DodgeField(self.seed, s["DIFFICULTIES"][self.difficulty], s)
        self.ship = Ship(s["START_X"], s["SHIP_Y"], math.pi / 2)
        self.t = 0.0
        self.tick = 0
        self.fuel = 0.0
        self.fuel_thrust = 0.0     # kept for recorder compatibility (= movement fuel)
        self.fuel_rotate = 0.0
        self.hits = 0
        self.invuln_until = -1.0
        self.outcome = RUNNING
        self.done = False
        self.last_action = Action()
        return self

    # -- helpers -------------------------------------------------------------
    def invulnerable(self):
        return self.t < self.invuln_until

    def speed(self):
        return abs(self.ship.vx)

    def time_left(self):
        return max(0.0, self.s["DURATION"] - self.t)

    def score(self):
        """Score = hits (lower is better). Movement is tracked separately in self.fuel."""
        return float(self.hits)

    def rank_key(self):
        """Smaller is better: completed runs first, then fewer hits."""
        return (0 if self.outcome == WIN else 1, self.hits)

    # -- main step -----------------------------------------------------------
    def step(self, action: Optional[Action] = None) -> StepResult:
        if self.done:
            return StepResult(self.t, self.tick, True, self.outcome, [])
        action = action or Action()
        self.last_action = action
        s, sh, dt = self.s, self.ship, self.dt
        events = []

        # 1. sideways movement (LEFT = +1 -> negative x)
        direction = -int(action.turn)
        if s["MOVE_MODE"] == "direct":
            sh.vx = direction * s["MOVE_SPEED"]
        elif s["MOVE_MODE"] == "accel":
            if direction:
                sh.vx += direction * s["MOVE_ACCEL"] * dt
            else:
                sh.vx *= max(0.0, 1.0 - s["MOVE_DRAG"] * dt)
            cap = s["MOVE_MAX_SPEED"]
            sh.vx = max(-cap, min(cap, sh.vx))
        else:
            raise ValueError(f"Unknown MOVE_MODE {s['MOVE_MODE']!r}")
        if direction:
            f = s["FUEL_PER_MOVE_SECOND"] * dt
            self.fuel += f
            self.fuel_thrust += f
        sh.x += sh.vx * dt
        r = s["SHIP_RADIUS"]
        if sh.x < r:                        # side walls just stop the ship
            sh.x, sh.vx = r, 0.0
        elif sh.x > self.W - r:
            sh.x, sh.vx = self.W - r, 0.0

        # 2. time and asteroids
        self.tick += 1
        self.t = self.tick * dt
        self.field.spawn_tick(self.t)
        self.field.move()
        self.field.despawn()

        # 3. collisions
        if not self.invulnerable():
            touching = [a for a in self.field.active()
                        if not a.spent and math.hypot(a.x - sh.x, a.y - sh.y) <= a.r + r]
            if touching:
                self.hits += 1
                self.invuln_until = self.t + s["INVULN_TIME"]
                events.append("hit")
                for a in touching:
                    a.spent = True

        # 4. survived?
        if self.t >= s["DURATION"] - 1e-9:
            self.outcome = WIN
            self.done = True
            events.append(WIN)

        return StepResult(self.t, self.tick, self.done, self.outcome, events)

    # -- state for recording / learning (same format as AsteroidGame) --------
    def get_state(self):
        sh = self.ship
        return {
            "t": self.t,
            "tick": self.tick,
            "ship": {"x": sh.x, "y": sh.y, "vx": sh.vx, "vy": sh.vy,
                     "heading": sh.heading, "omega": 0.0},
            "fuel": self.fuel,
            "hits": self.hits,
            "invulnerable": self.invulnerable(),
            "asteroids": [
                {"id": a.id, "x": a.x, "y": a.y, "vx": a.vx, "vy": a.vy,
                 "ax": a.ax, "ay": a.ay, "r": a.r, "spent": a.spent}
                for a in self.field.active()
            ],
        }
