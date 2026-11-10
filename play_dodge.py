"""
Play DODGE RUN with the keyboard (and record demos).

    python play_dodge.py --player levi
    python play_dodge.py --player levi --difficulty hard --seed 123
    python play_dodge.py --no-record

The ship sits near the bottom and slides left/right. Asteroids fall from the top.
Survive 30 seconds with as few hits as possible (score = hits; movement is tracked too).

In a run:      LEFT/RIGHT move   P pause   ESC abandon run
Between runs:  R retry same field  N new field  1/2/3 difficulty
               M movement mode (direct / momentum)   ESC quit

Runs are saved to data/dodge_demos.sqlite. Watch them with:
    python replay.py --db data/dodge_demos.sqlite --list
"""

import argparse
import random
import sys
from collections import deque

import pygame

import config
import dodge_config
from game.dodge import GAME_VERSION, WIN, DodgeGame, dodge_settings
from game.recorder import Recorder
from game.render import BAD, DIM, GOOD, TEXT, Renderer, interpolate_state
from game.sim import Action

OUTCOME_TEXT = {WIN: ("Survived!", GOOD), "quit": ("Run abandoned", BAD)}
MOVE_MODES = ["direct", "accel"]
MOVE_MODE_LABEL = {"direct": "direct", "accel": "momentum"}


class App:
    def __init__(self, args):
        pygame.init()
        self.args = args
        self.player = args.player
        self.settings = dodge_settings()
        self.difficulty = args.difficulty or self.settings["DEFAULT_DIFFICULTY"]
        self.seed = args.seed if args.seed is not None else random.randrange(1_000_000)
        self.renderer = Renderer(self.settings, caption="Dodge Run")
        self.clock = pygame.time.Clock()
        self.recorder = None if args.no_record else Recorder(args.db, held_out_seeds=False)
        self.new_game()

    # -- game lifecycle ------------------------------------------------------
    def new_game(self):
        self.game = DodgeGame(self.seed, self.difficulty, dict(self.settings))
        self.renderer.set_settings(self.game.s)
        self.mode = "ready"          # ready / playing / paused / over
        self.prev_state = None
        self.cur_state = self.game.get_state()
        self.trail = [(self.game.ship.x, self.game.ship.y)]
        self.taps = deque(maxlen=2)
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
        # a quick tap between ticks still moves for one tick
        turn = held if held else (self.taps[0] if self.taps else 0)
        raw = {"left": int(left), "right": int(right), "thrust": 0}
        return Action(turn, False), raw

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
                    i = MOVE_MODES.index(self.settings["MOVE_MODE"])
                    self.settings["MOVE_MODE"] = MOVE_MODES[(i + 1) % len(MOVE_MODES)]
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

    # -- tick ----------------------------------------------------------------
    def tick(self):
        action, raw = self.current_action()
        before = self.game.get_state()
        if self.recorder:
            self.recorder.log_step(before, action, raw)
        res = self.game.step(action)
        if self.taps:
            self.taps.popleft()
        self.prev_state = before
        self.cur_state = self.game.get_state()
        self.trail.append((self.game.ship.x, self.game.ship.y))
        if res.done:
            self.end_run()

    # -- drawing -------------------------------------------------------------
    def draw(self, alpha):
        r, g, s = self.renderer, self.game, self.game.s
        st = interpolate_state(self.prev_state, self.cur_state, alpha) if self.mode == "playing" else self.cur_state
        r.draw_field()
        r.draw_asteroids(st["asteroids"], config.SHOW_ASTEROID_IDS)
        r.draw_walls()
        r.draw_ship(st["ship"], thrusting=False, invulnerable=st["invulnerable"],
                    t=st["t"], show_vel=False)

        hits_color = GOOD if g.hits == 0 else BAD
        lines = [
            ("DODGE RUN", TEXT),
            (f"Player: {self.player}", TEXT),
            (f"Seed {g.seed}  |  {g.difficulty}", TEXT),
            None,
            (f"Time left  {g.time_left():5.1f} s", TEXT),
        ]
        r.hud(lines)
        r.bar(g.t / s["DURATION"], 24 + 24 * 4 + 10 + 26, GOOD)
        lines = [
            (f"Hits   {g.hits}", hits_color),
            ("(score = hits, lower is better)", DIM),
            (f"Moved  {g.fuel:5.2f} s", TEXT),
            ("(tracked, not scored)", DIM),
            None,
            (f"Movement: {MOVE_MODE_LABEL[s['MOVE_MODE']]}  [M]", TEXT),
            (f"Recording: {'ON' if self.recorder else 'OFF'}", TEXT),
            None,
            ("LEFT/RIGHT  move", DIM),
            ("P pause   ESC abandon/quit", DIM),
            ("R retry   N new field", DIM),
            ("1/2/3  easy/medium/hard", DIM),
        ]
        if self.best:
            p, h, t, f, sc = self.best
            lines += [None, ("Best on this field:", TEXT),
                      (f"{p}: {h} hits, moved {f:.2f} s", DIM)]
        r.hud(lines, y0=24 + 24 * 4 + 10 + 50)

        if self.mode == "ready":
            r.overlay("Ready", ["Press LEFT or RIGHT to start",
                                f"Survive {s['DURATION']:.0f} seconds",
                                "Dodge the falling asteroids"])
        elif self.mode == "paused":
            r.overlay("Paused", ["P or SPACE to resume"])
        elif self.mode == "over":
            title, color = OUTCOME_TEXT.get(self.final_outcome, (self.final_outcome, TEXT))
            lines = [f"Hits {g.hits}   (moved {g.fuel:.2f} s)"]
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
    ap.add_argument("--db", default=dodge_config.DB_PATH, help="database file")
    args = ap.parse_args(argv)
    if not dodge_config.RECORD_BY_DEFAULT:
        args.no_record = True
    if not args.player:
        try:
            args.player = input("Player name: ").strip() or "anonymous"
        except EOFError:
            args.player = "anonymous"
    App(args).run()


if __name__ == "__main__":
    sys.exit(main())
