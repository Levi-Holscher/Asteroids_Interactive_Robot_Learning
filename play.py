"""
Play the asteroid-field game with the keyboard (and record demos).

    python play.py --player levi
    python play.py --player levi --difficulty hard --seed 123
    python play.py --no-record

In a run:      LEFT/RIGHT rotate   SPACE thrust   P pause   ESC abandon run
Between runs:  R retry same field  N new field  1/2/3 difficulty  M speed cap on/off
               G cycle goal gate   T cycle rotation mode   ESC quit
"""

import argparse
import math
import random
import sys
from collections import deque

import pygame

import config
from game.recorder import Recorder
from game.render import BAD, DIM, GOOD, TEXT, Renderer, interpolate_state
from game.settings import default_settings
from game.sim import (GAME_VERSION, OUT_OF_BOUNDS, TIMEOUT, WIN, Action,
                      AsteroidGame)

OUTCOME_TEXT = {WIN: ("Goal reached!", GOOD), OUT_OF_BOUNDS: ("Out of bounds", BAD),
                TIMEOUT: ("Time ran out", BAD), "quit": ("Run abandoned", BAD)}
ROTATION_MODES = ["step", "continuous", "momentum"]


def gate_presets(s):
    W = s["FIELD_WIDTH"]
    presets = [config.GOAL_GATE, None, (W / 2, 0.6), (0.72 * W, 0.5)]
    out = []
    for p in presets:
        p = None if p is None else tuple(p)
        if p not in out:
            out.append(p)
    return out


def gate_label(g):
    return "whole top" if g is None else f"gate x={g[0]:.2f} w={g[1]:.2f}"


class App:
    def __init__(self, args):
        pygame.init()
        self.args = args
        self.player = args.player
        self.settings = default_settings()
        self.difficulty = args.difficulty or self.settings["DEFAULT_DIFFICULTY"]
        self.seed = args.seed if args.seed is not None else random.randrange(1_000_000)
        self.renderer = Renderer(self.settings)
        self.clock = pygame.time.Clock()
        self.recorder = None if args.no_record else Recorder(args.db)
        self.new_game()

    # -- game lifecycle ------------------------------------------------------
    def new_game(self):
        self.game = AsteroidGame(self.seed, self.difficulty, dict(self.settings))
        self.renderer.set_settings(self.game.s)
        self.mode = "ready"          # ready / playing / paused / over
        self.prev_state = None
        self.cur_state = self.game.get_state()
        self.trail = [(self.game.ship.x, self.game.ship.y)]
        self.taps = deque(maxlen=2)
        self.thrust_tap = False
        self.acc = 0.0
        self.final_outcome = None
        self.best = self.recorder.best_for_seed(self.seed, self.difficulty) if self.recorder else None

    def start_run(self):
        self.mode = "playing"
        self.acc = 0.0
        if self.recorder:
            self.recorder.start_episode(self.game, self.player, GAME_VERSION)

    def end_run(self, outcome=None):
        self.final_outcome = outcome or self.game.outcome
        if self.recorder:
            self.recorder.log_step(self.game.get_state(), None)
            self.recorder.end_episode(self.game, self.final_outcome)
        self.mode = "over"

    # -- input ---------------------------------------------------------------
    def current_action(self):
        keys = pygame.key.get_pressed()
        left, right = keys[pygame.K_LEFT], keys[pygame.K_RIGHT]
        held = 0
        if left and not right:
            held = 1
        elif right and not left:
            held = -1
        turn = held if held else (self.taps[0] if self.taps else 0)
        thrust = bool(keys[pygame.K_SPACE]) or self.thrust_tap
        raw = {"left": int(left), "right": int(right), "thrust": int(keys[pygame.K_SPACE])}
        return Action(turn, thrust), raw

    def handle_events(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return False
            if ev.type != pygame.KEYDOWN:
                continue
            k = ev.key
            if self.mode in ("ready", "over"):
                if k == pygame.K_ESCAPE:
                    return False
                if k == pygame.K_r:
                    self.new_game()
                elif k == pygame.K_n:
                    self.seed = random.randrange(1_000_000)
                    self.new_game()
                elif k in (pygame.K_1, pygame.K_2, pygame.K_3):
                    self.difficulty = ["easy", "medium", "hard"][k - pygame.K_1]
                    self.new_game()
                elif k == pygame.K_m:
                    self.settings["SPEED_CAP_ENABLED"] = not self.settings["SPEED_CAP_ENABLED"]
                    self.new_game()
                elif k == pygame.K_g:
                    pres = gate_presets(self.settings)
                    cur = self.settings["GOAL_GATE"]
                    cur = None if cur is None else tuple(cur)
                    i = pres.index(cur) if cur in pres else -1
                    self.settings["GOAL_GATE"] = pres[(i + 1) % len(pres)]
                    self.new_game()
                elif k == pygame.K_t:
                    i = ROTATION_MODES.index(self.settings["ROTATION_MODE"])
                    self.settings["ROTATION_MODE"] = ROTATION_MODES[(i + 1) % len(ROTATION_MODES)]
                    self.new_game()
                elif self.mode == "ready" and k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_SPACE):
                    self.start_run()
                    self._register_tap(k)
            elif self.mode == "playing":
                if k == pygame.K_ESCAPE:
                    self.end_run("quit")
                elif k == pygame.K_p:
                    self.mode = "paused"
                else:
                    self._register_tap(k)
            elif self.mode == "paused":
                if k in (pygame.K_p, pygame.K_SPACE):
                    self.mode = "playing"
                    self.acc = 0.0
                elif k == pygame.K_ESCAPE:
                    self.end_run("quit")
        return True

    def _register_tap(self, k):
        if k == pygame.K_LEFT:
            self.taps.append(1)
        elif k == pygame.K_RIGHT:
            self.taps.append(-1)
        elif k == pygame.K_SPACE:
            self.thrust_tap = True

    # -- tick ----------------------------------------------------------------
    def tick(self):
        action, raw = self.current_action()
        before = self.game.get_state()
        if self.recorder:
            self.recorder.log_step(before, action, raw)
        res = self.game.step(action)
        self.thrust_tap = False
        if self.taps:
            if self.game.s["ROTATION_MODE"] != "step" or "rotate_step" in res.events:
                self.taps.popleft()
        self.prev_state = before
        self.cur_state = self.game.get_state()
        self.cur_state["thrust"] = action.thrust
        self.trail.append((self.game.ship.x, self.game.ship.y))
        if res.done:
            self.end_run()

    # -- drawing -------------------------------------------------------------
    def draw(self, alpha):
        r, g, s = self.renderer, self.game, self.game.s
        st = interpolate_state(self.prev_state, self.cur_state, alpha) if self.mode == "playing" else self.cur_state
        r.draw_field()
        r.draw_trail(self.trail)
        r.draw_asteroids(st["asteroids"], config.SHOW_ASTEROID_IDS)
        r.draw_walls()
        r.draw_ship(st["ship"], thrusting=st.get("thrust", False) and self.mode == "playing",
                    invulnerable=st["invulnerable"], t=st["t"], show_vel=config.SHOW_VELOCITY_VECTOR)

        hits_color = GOOD if g.hits == 0 else BAD
        lines = [
            (f"Player: {self.player}", TEXT),
            (f"Seed {g.seed}  |  {g.difficulty}", TEXT),
            None,
            (f"Time   {g.t:6.2f} s", TEXT),
            (f"Fuel   {g.fuel:6.2f}", TEXT),
            (f"Hits   {g.hits}", hits_color),
            (f"Speed  {g.speed():5.3f}", TEXT),
            (f"Score  {g.score():5.3f}", TEXT),
            (f"(lower is better)", DIM),
            None,
            (f"Speed cap: {'ON' if s['SPEED_CAP_ENABLED'] else 'OFF'}  [M]", TEXT),
            (f"Rotation: {s['ROTATION_MODE']}  [T]", TEXT),
            (f"Goal: {gate_label(None if s['GOAL_GATE'] is None else tuple(s['GOAL_GATE']))}  [G]", TEXT),
            (f"Recording: {'ON' if self.recorder else 'OFF'}", TEXT),
            None,
            ("LEFT/RIGHT  rotate", DIM),
            ("SPACE  thrust", DIM),
            ("P pause   ESC abandon/quit", DIM),
            ("R retry   N new field", DIM),
            ("1/2/3  easy/medium/hard", DIM),
        ]
        if self.best:
            p, h, t, f, sc = self.best
            lines += [None, ("Best on this field:", TEXT),
                      (f"{p}: {h} hits, {t:.2f} s, fuel {f:.2f}", DIM)]
        r.hud(lines)

        if self.mode == "ready":
            r.overlay("Ready", ["Press an arrow key or SPACE to start",
                                "Reach the green goal at the top",
                                "Don't touch the red walls"])
        elif self.mode == "paused":
            r.overlay("Paused", ["P or SPACE to resume"])
        elif self.mode == "over":
            title, color = OUTCOME_TEXT.get(self.final_outcome, (self.final_outcome, TEXT))
            lines = [f"Time {g.t:.2f} s   Fuel {g.fuel:.2f}   Hits {g.hits}"]
            if self.final_outcome == WIN:
                lines.append(f"Hit tier {g.hits}   Score {g.score():.3f}")
            lines += ["R retry same field   N new field   ESC quit"]
            r.overlay(title, lines, color)
        pygame.display.flip()

    # -- main loop -----------------------------------------------------------
    def run(self):
        dt = 1.0 / self.game.s["TICK_HZ"]
        running = True
        while running:
            frame = self.clock.tick(config.RENDER_FPS) / 1000.0
            running = self.handle_events()
            if not running:
                break
            if self.mode == "playing":
                self.acc += min(frame, 0.25)
                while self.acc >= dt and self.mode == "playing":
                    self.acc -= dt
                    self.tick()
            alpha = self.acc / dt if self.mode == "playing" else 1.0
            self.draw(alpha)
        if self.mode in ("playing", "paused"):
            self.end_run("quit")
        if self.recorder:
            self.recorder.close()
        pygame.quit()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--player", help="your name (saved with each recorded run)")
    ap.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    ap.add_argument("--seed", type=int, help="field seed (same seed = same asteroids)")
    ap.add_argument("--no-record", action="store_true", help="don't save runs to the database")
    ap.add_argument("--db", default=config.DB_PATH, help="database file")
    args = ap.parse_args(argv)
    if not config.RECORD_BY_DEFAULT:
        args.no_record = True
    if not args.player:
        try:
            args.player = input("Player name: ").strip() or "anonymous"
        except EOFError:
            args.player = "anonymous"
    App(args).run()


if __name__ == "__main__":
    sys.exit(main())
