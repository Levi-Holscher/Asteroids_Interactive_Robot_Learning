"""
Headless game logic. No pygame in here, so a bot can run this as fast as the CPU allows.

    game = AsteroidGame(seed=123, difficulty="medium")
    while not game.done:
        result = game.step(Action(turn=0, thrust=True))

An Action is what the player (human or bot) does for one tick:
    turn   : -1 = rotate right (clockwise), 0 = none, +1 = rotate left (counter-clockwise)
    thrust : True/False
"""

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional

from game.settings import default_settings

GAME_VERSION = "0.1.0"

# Outcomes
RUNNING = "running"
WIN = "win"
OUT_OF_BOUNDS = "out_of_bounds"
TIMEOUT = "timeout"


@dataclass(frozen=True)
class Action:
    turn: int = 0        # -1 right, 0 none, +1 left
    thrust: bool = False


# The full discrete action set (6 actions) - handy for learning code later.
ACTIONS = [Action(t, th) for th in (False, True) for t in (-1, 0, 1)]


# ----------------------------------------------------------------------------
# Asteroids
# ----------------------------------------------------------------------------
@dataclass
class Asteroid:
    id: int
    t0: float            # time created (s)
    x0: float
    y0: float
    vx: float
    vy: float
    ax: float
    ay: float
    r: float
    alive: bool = True

    def pos(self, t):
        dt = t - self.t0
        return (self.x0 + self.vx * dt + 0.5 * self.ax * dt * dt,
                self.y0 + self.vy * dt + 0.5 * self.ay * dt * dt)

    def vel(self, t):
        dt = t - self.t0
        return (self.vx + self.ax * dt, self.vy + self.ay * dt)


class AsteroidField:
    """Generates asteroids from a seed. The sequence depends only on the seed and
    difficulty - never on what the ship does (hits remove asteroids but never touch
    the random number generator)."""

    def __init__(self, seed, diff, s):
        self.rng = random.Random(seed)
        self.d = diff
        self.s = s
        self.W = s["FIELD_WIDTH"]
        self.H = s["FIELD_HEIGHT"]
        self.dt = 1.0 / s["TICK_HZ"]
        self.next_id = 1
        self.asteroids: List[Asteroid] = []
        self._initial_field()

    def _new(self, t, x, y, vx, vy, ax, ay, r):
        a = Asteroid(self.next_id, t, x, y, vx, vy, ax, ay, r)
        self.next_id += 1
        self.asteroids.append(a)
        return a

    def _radius(self):
        return self.rng.uniform(self.d["radius_min"], self.d["radius_max"])

    def _speed(self):
        return self.rng.uniform(self.d["speed_min"], self.d["speed_max"])

    def _initial_field(self):
        sx, sy = self.s["START_POS"]
        safe = self.s["START_SAFE_RADIUS"]
        placed, tries = 0, 0
        while placed < self.d["n_start"] and tries < 10000:
            tries += 1
            r = self._radius()
            x = self.rng.uniform(r, self.W - r)
            y = self.rng.uniform(r, self.H - r)
            if math.hypot(x - sx, y - sy) < safe + r:
                continue
            vx, vy, ax, ay = self._side_motion(self.rng.choice((-1, 1)))
            self._new(0.0, x, y, vx, vy, ax, ay, r)
            placed += 1

    def _side_motion(self, direction):
        """Mostly-horizontal motion. direction=+1 moves right, -1 moves left."""
        sp = self._speed()
        amax = self.d["accel_max"]
        vx = direction * sp
        vy = self.rng.uniform(-1, 1) * sp * self.s["VERTICAL_SPEED_FRAC"]
        # Mostly accelerate along the direction of travel so rocks rarely reverse.
        ax = direction * self.rng.uniform(-0.5 * amax, amax)
        ay = self.rng.uniform(-0.5, 0.5) * amax
        return vx, vy, ax, ay

    def spawn_tick(self, t):
        """Called once per tick with the new time. Poisson spawns from the edges."""
        lam = self.d["spawn_per_sec"] * self.dt
        # Poisson sample (Knuth) - fine for small lambda
        n, p, L = 0, 1.0, math.exp(-lam)
        while True:
            p *= self.rng.random()
            if p <= L:
                break
            n += 1
        for _ in range(n):
            r = self._radius()
            if self.rng.random() < self.d["top_spawn_frac"]:
                x = self.rng.uniform(r, self.W - r)
                sp = self._speed()
                vx = self.rng.uniform(-0.3, 0.3) * sp
                vy = -0.7 * sp
                ax = self.rng.uniform(-0.5, 0.5) * self.d["accel_max"]
                ay = -self.rng.uniform(0, 0.5) * self.d["accel_max"]
                self._new(t, x, self.H + r, vx, vy, ax, ay, r)
            else:
                side = self.rng.choice((-1, 1))   # -1 = from left edge, +1 = from right edge
                x = -r if side == -1 else self.W + r
                y = self.rng.uniform(0.3 * self.H, self.H - r)
                vx, vy, ax, ay = self._side_motion(-side)  # move into the field
                self._new(t, x, y, vx, vy, ax, ay, r)

    def despawn(self, t):
        m = self.s["ASTEROID_DESPAWN_MARGIN"]
        keep = []
        for a in self.asteroids:
            if not a.alive:
                continue
            x, y = a.pos(t)
            if -m - a.r <= x <= self.W + m + a.r and -m - a.r <= y <= self.H + m + a.r:
                keep.append(a)
        self.asteroids = keep

    def active(self):
        return [a for a in self.asteroids if a.alive]


# ----------------------------------------------------------------------------
# Ship
# ----------------------------------------------------------------------------
@dataclass
class Ship:
    x: float
    y: float
    heading: float       # radians, 0 = +x (right), pi/2 = +y (up)
    vx: float = 0.0
    vy: float = 0.0
    omega: float = 0.0   # rad/s (momentum mode; also the current spin in step mode)
    step_ticks_left: int = 0
    step_dir: int = 0


@dataclass
class StepResult:
    t: float
    tick: int
    done: bool
    outcome: str
    events: List[str] = field(default_factory=list)


# ----------------------------------------------------------------------------
# Game
# ----------------------------------------------------------------------------
class AsteroidGame:
    def __init__(self, seed=None, difficulty=None, settings=None):
        self.s = settings if settings is not None else default_settings()
        self.difficulty = difficulty or self.s["DEFAULT_DIFFICULTY"]
        if self.difficulty not in self.s["DIFFICULTIES"]:
            raise ValueError(f"Unknown difficulty {self.difficulty!r}")
        self.seed = seed if seed is not None else random.randrange(1_000_000)
        self.reset()

    # -- setup ---------------------------------------------------------------
    def reset(self, seed=None):
        if seed is not None:
            self.seed = seed
        s = self.s
        self.dt = 1.0 / s["TICK_HZ"]
        self.W, self.H = s["FIELD_WIDTH"], s["FIELD_HEIGHT"]
        self.field = AsteroidField(self.seed, s["DIFFICULTIES"][self.difficulty], s)
        # Start heading comes from its own RNG so it is fixed per seed too.
        hrng = random.Random(f"heading-{self.seed}")
        if s["START_HEADING_RANDOM"]:
            heading = hrng.uniform(0, 2 * math.pi)
        else:
            heading = math.radians(s["START_HEADING_DEG"])
        sx, sy = s["START_POS"]
        self.ship = Ship(sx, sy, heading)
        self.t = 0.0
        self.tick = 0
        self.fuel = 0.0
        self.fuel_thrust = 0.0
        self.fuel_rotate = 0.0
        self.hits = 0
        self.invuln_until = -1.0
        self.outcome = RUNNING
        self.done = False
        self._prev_turn = 0
        self._ticks_since_step = 10 ** 9
        self.last_action = Action()
        return self

    # -- helpers -------------------------------------------------------------
    def in_gate(self, x):
        g = self.s["GOAL_GATE"]
        if g is None:
            return True
        cx, w = g
        return cx - w / 2 <= x <= cx + w / 2

    def invulnerable(self):
        return self.t < self.invuln_until

    def speed(self):
        return math.hypot(self.ship.vx, self.ship.vy)

    def score(self):
        s = self.s
        return (s["W_TIME"] * self.t / s["REF_TIME"]
                + s["W_FUEL"] * self.fuel / s["REF_FUEL"])

    def rank_key(self):
        """Sort key: smaller is better. Wins beat losses, fewer hits beat more hits,
        then lower score."""
        return (0 if self.outcome == WIN else 1, self.hits, self.score())

    # -- rotation ------------------------------------------------------------
    def _rotate(self, turn, events):
        s, sh = self.s, self.ship
        mode = s["ROTATION_MODE"]
        if mode == "step":
            self._ticks_since_step += 1
            if sh.step_ticks_left == 0 and turn != 0:
                newly_pressed = turn != self._prev_turn
                if newly_pressed or self._ticks_since_step >= s["ROTATE_REPEAT_TICKS"]:
                    sh.step_ticks_left = max(1, int(s["ROTATE_STEP_TICKS"]))
                    sh.step_dir = turn
                    self._ticks_since_step = 0
                    self.fuel += s["FUEL_PER_ROTATE_STEP"]
                    self.fuel_rotate += s["FUEL_PER_ROTATE_STEP"]
                    events.append("rotate_step")
            if sh.step_ticks_left > 0:
                n = max(1, int(s["ROTATE_STEP_TICKS"]))
                dtheta = sh.step_dir * math.radians(s["ROTATE_STEP_DEG"]) / n
                sh.heading += dtheta
                sh.omega = dtheta / self.dt
                sh.step_ticks_left -= 1
            else:
                sh.omega = 0.0
        elif mode == "continuous":
            sh.omega = turn * math.radians(s["ROTATE_RATE_DEG"])
            sh.heading += sh.omega * self.dt
            if turn:
                self._burn_rotate()
        elif mode == "momentum":
            sh.omega += turn * math.radians(s["ROTATE_ACCEL_DEG"]) * self.dt
            cap = math.radians(s["ROTATE_MAX_RATE_DEG"])
            sh.omega = max(-cap, min(cap, sh.omega))
            sh.heading += sh.omega * self.dt
            if turn:
                self._burn_rotate()
        else:
            raise ValueError(f"Unknown ROTATION_MODE {mode!r}")
        sh.heading %= 2 * math.pi
        self._prev_turn = turn

    def _burn_rotate(self):
        f = self.s["FUEL_PER_ROTATE_SECOND"] * self.dt
        self.fuel += f
        self.fuel_rotate += f

    # -- main step -----------------------------------------------------------
    def step(self, action: Optional[Action] = None) -> StepResult:
        if self.done:
            return StepResult(self.t, self.tick, True, self.outcome, [])
        action = action or Action()
        self.last_action = action
        s, sh, dt = self.s, self.ship, self.dt
        events = []

        # 1. rotation
        self._rotate(int(action.turn), events)

        # 2. thrust (semi-implicit Euler: update velocity, then position)
        if action.thrust:
            sh.vx += s["THRUST_ACCEL"] * math.cos(sh.heading) * dt
            sh.vy += s["THRUST_ACCEL"] * math.sin(sh.heading) * dt
            f = s["FUEL_PER_THRUST_SECOND"] * dt
            self.fuel += f
            self.fuel_thrust += f
        if s["LINEAR_DRAG"] > 0:
            k = max(0.0, 1.0 - s["LINEAR_DRAG"] * dt)
            sh.vx *= k
            sh.vy *= k
        if s["SPEED_CAP_ENABLED"]:
            sp = math.hypot(sh.vx, sh.vy)
            if sp > s["MAX_SPEED"]:
                sh.vx *= s["MAX_SPEED"] / sp
                sh.vy *= s["MAX_SPEED"] / sp
        sh.x += sh.vx * dt
        sh.y += sh.vy * dt

        # 3. advance time and the asteroid field
        self.tick += 1
        self.t = self.tick * dt
        self.field.spawn_tick(self.t)
        self.field.despawn(self.t)

        # 4. goal / walls
        r = s["SHIP_RADIUS"]
        if sh.y >= self.H and self.in_gate(sh.x):
            self._finish(WIN, events)
        elif (sh.x - r <= 0 or sh.x + r >= self.W
              or (s["BOTTOM_IS_WALL"] and sh.y - r <= 0)
              or (sh.y + r >= self.H and not self.in_gate(sh.x))):
            self._finish(OUT_OF_BOUNDS, events)

        # 5. asteroid collisions (still counted on the final tick)
        if not self.invulnerable():
            touching = []
            for a in self.field.active():
                ax, ay = a.pos(self.t)
                if math.hypot(ax - sh.x, ay - sh.y) <= a.r + r:
                    touching.append(a)
            if touching:
                self.hits += 1
                self.invuln_until = self.t + s["INVULN_TIME"]
                events.append("hit")
                if s["DESTROY_ASTEROID_ON_HIT"]:
                    for a in touching:
                        a.alive = False

        # 6. timeout
        if not self.done and self.t >= s["MAX_EPISODE_TIME"]:
            self._finish(TIMEOUT, events)

        return StepResult(self.t, self.tick, self.done, self.outcome, events)

    def _finish(self, outcome, events):
        self.outcome = outcome
        self.done = True
        events.append(outcome)

    # -- state for recording / learning --------------------------------------
    def get_state(self):
        """Full raw state as plain Python types (JSON-serialisable)."""
        sh = self.ship
        return {
            "t": self.t,
            "tick": self.tick,
            "ship": {"x": sh.x, "y": sh.y, "vx": sh.vx, "vy": sh.vy,
                     "heading": sh.heading, "omega": sh.omega},
            "fuel": self.fuel,
            "hits": self.hits,
            "invulnerable": self.invulnerable(),
            "asteroids": [
                {"id": a.id, "x": p[0], "y": p[1], "vx": v[0], "vy": v[1],
                 "ax": a.ax, "ay": a.ay, "r": a.r}
                for a in self.field.active()
                for p, v in [(a.pos(self.t), a.vel(self.t))]
            ],
        }
