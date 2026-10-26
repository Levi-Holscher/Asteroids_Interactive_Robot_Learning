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

GAME_VERSION = "0.3.0"

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
    x: float
    y: float
    vx: float
    vy: float
    ax: float            # constant acceleration (wu/s^2)
    ay: float
    r: float
    spent: bool = False  # True once it has hit the ship: harmless, but still bounces

    @property
    def mass(self):
        return self.r * self.r   # disks of equal density -> mass ~ area


class AsteroidField:
    """Generates and moves asteroids from a seed.

    Asteroids move with constant acceleration and bounce off each other (elastic
    collisions, mass ~ area). Everything here depends only on the seed and difficulty -
    never on what the ship does. An asteroid that hits the ship is marked "spent"
    (harmless, drawn dim) but stays in the physics, so the rest of the field still plays
    out identically for every player on the same seed."""

    def __init__(self, seed, diff, s):
        self.rng = random.Random(seed)
        self.d = diff
        self.s = s
        self.W = s["FIELD_WIDTH"]
        self.H = s["FIELD_HEIGHT"]
        self.dt = 1.0 / s["TICK_HZ"]
        self.vm = s["VIEW_MARGIN_FRAC"] * self.W   # visible margin outside the walls
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

    def _overlaps(self, x, y, r, gap=0.01):
        return any(math.hypot(a.x - x, a.y - y) < a.r + r + gap for a in self.asteroids)

    def _initial_field(self):
        sx, sy = self.s["START_POS"]
        safe = self.s["START_SAFE_RADIUS"]
        vm = self.vm
        # n_start is the count inside the walls; fill the visible margin at the same density
        area_ratio = ((self.W + 2 * vm) * (self.H + 2 * vm)) / (self.W * self.H)
        target = int(round(self.d["n_start"] * area_ratio))
        placed, tries = 0, 0
        while placed < target and tries < 40000:
            tries += 1
            r = self._radius()
            x = self.rng.uniform(-vm + r, self.W + vm - r)
            y = self.rng.uniform(-vm + r, self.H + vm - r)
            if math.hypot(x - sx, y - sy) < safe + r or self._overlaps(x, y, r):
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
        """Poisson spawns from the edges (called once per tick)."""
        lam = self.d["spawn_per_sec"] * self.dt
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
                self._new(t, x, self.H + self.vm + r, vx, vy, ax, ay, r)
            else:
                side = self.rng.choice((-1, 1))   # -1 = from left edge, +1 = from right edge
                x = -self.vm - r if side == -1 else self.W + self.vm + r
                y = self.rng.uniform(0.25 * self.H, self.H + self.vm - r)
                vx, vy, ax, ay = self._side_motion(-side)  # move into the field
                self._new(t, x, y, vx, vy, ax, ay, r)

    def move(self):
        """Advance every asteroid one tick (semi-implicit Euler), then resolve bounces."""
        dt = self.dt
        for a in self.asteroids:
            a.vx += a.ax * dt
            a.vy += a.ay * dt
            a.x += a.vx * dt
            a.y += a.vy * dt
        if self.s["ASTEROID_COLLISIONS"]:
            self._collide()

    def _collide(self):
        """Sort-and-sweep along x so we only test nearby pairs, then resolve each
        overlapping pair: push apart (split by inverse mass) and apply an elastic
        impulse if they are moving toward each other."""
        e = self.s["ASTEROID_RESTITUTION"]
        if not self.asteroids:
            return
        rmax = max(a.r for a in self.asteroids)
        for _ in range(3):          # extra passes only if a pass found contacts
            ast = sorted(self.asteroids, key=lambda a: a.x)
            n = len(ast)
            found = False
            for i in range(n):
                a = ast[i]
                reach = a.x + a.r + rmax
                for j in range(i + 1, n):
                    b = ast[j]
                    if b.x > reach:
                        break
                    dx, dy = b.x - a.x, b.y - a.y
                    rr = a.r + b.r
                    if dy > rr or dy < -rr:
                        continue
                    d2 = dx * dx + dy * dy
                    if d2 >= rr * rr:
                        continue
                    found = True
                    d = math.sqrt(d2) or 1e-9
                    nx, ny = dx / d, dy / d
                    ima, imb = 1.0 / a.mass, 1.0 / b.mass
                    k = (rr - d) / (ima + imb)
                    a.x -= nx * k * ima
                    a.y -= ny * k * ima
                    b.x += nx * k * imb
                    b.y += ny * k * imb
                    vrel = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny
                    if vrel > 0:
                        jimp = (1 + e) * vrel / (ima + imb)
                        a.vx -= jimp * ima * nx
                        a.vy -= jimp * ima * ny
                        b.vx += jimp * imb * nx
                        b.vy += jimp * imb * ny
            if not found:
                break

    def despawn(self):
        m = self.vm + self.s["ASTEROID_DESPAWN_MARGIN"]
        self.asteroids = [a for a in self.asteroids
                          if -m - a.r <= a.x <= self.W + m + a.r
                          and -m - a.r <= a.y <= self.H + m + a.r]

    def active(self):
        return self.asteroids


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
        if s["GOAL_GATE"] is not None:
            cx, w = s["GOAL_GATE"]
            if cx - w / 2 < 0 or cx + w / 2 > self.W:
                raise ValueError(f"GOAL_GATE {s['GOAL_GATE']} doesn't fit in a field "
                                 f"{self.W} wide")
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
        self.field.spawn_tick(self.t)   # new rocks enter at the edges...
        self.field.move()               # ...then everything moves and bounces
        self.field.despawn()

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
                if not a.spent and math.hypot(a.x - sh.x, a.y - sh.y) <= a.r + r:
                    touching.append(a)
            if touching:
                self.hits += 1
                self.invuln_until = self.t + s["INVULN_TIME"]
                events.append("hit")
                for a in touching:
                    a.spent = True

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
                {"id": a.id, "x": a.x, "y": a.y, "vx": a.vx, "vy": a.vy,
                 "ax": a.ax, "ay": a.ay, "r": a.r, "spent": a.spent}
                for a in self.field.active()
            ],
        }
