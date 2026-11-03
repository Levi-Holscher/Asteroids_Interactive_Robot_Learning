"""
Play LATTICE GATE (the grid version) with the keyboard, record demos, and replay them.

    python play_grid.py --player levi
    python play_grid.py --player levi --difficulty hard --seed 123
    python play_grid.py --no-record
    python play_grid.py --list                 # list recorded runs
    python play_grid.py --replay 3             # watch run 3

The ship moves one cell per turn. Asteroids slide along their lanes and wrap around.
Reach the green gate in the top wall. Light rows are safe (no asteroids).

Turn mode (default): each key press is one move and the asteroids step once.
Real-time mode (T): the world steps 4 times per second with whatever key you hold.

In a run:      ARROWS move   SPACE wait one turn   P pause (real-time)   ESC abandon
Between runs:  R retry same field  N new field  1/2/3 difficulty
               T turn / real-time mode   ESC quit

Runs are saved to data/grid_demos.sqlite.
"""

import argparse
import math
import random
import sqlite3
import sys

import pygame

import config
import grid_config
from game.grid import (ACTION_NAMES, DOWN, LEFT, RIGHT, STAY, TIMEOUT, UP, WIN,
                       GridGame, GridRecorder, grid_settings, load_grid_episode)
from game.render import BAD, DIM, GOOD, TEXT, Renderer, lerp

SAFE_ROW = (28, 33, 52)
HEADING_ANGLE = {UP: math.pi / 2, DOWN: -math.pi / 2, LEFT: math.pi, RIGHT: 0.0, STAY: math.pi / 2}
KEY_ACTION = {pygame.K_UP: UP, pygame.K_DOWN: DOWN, pygame.K_LEFT: LEFT,
              pygame.K_RIGHT: RIGHT, pygame.K_SPACE: STAY}
OUTCOME_TEXT = {WIN: ("Through the gate!", GOOD), TIMEOUT: ("Out of turns", BAD),
                "quit": ("Run abandoned", BAD)}
MODES = ["turn", "realtime"]


# ----------------------------------------------------------------------------
# grid state -> world coordinates for the shared renderer
# ----------------------------------------------------------------------------
def to_world(state, s):
    cell = s["CELL"]
    sh = state["ship"]
    ship = {"x": (sh["col"] + 0.5) * cell, "y": (sh["row"] + 0.5) * cell,
            "heading": HEADING_ANGLE[sh["heading"]], "vx": 0.0, "vy": 0.0}
    asts = []
    for a in state["asteroids"]:
        # stable, slightly varied size per asteroid (purely cosmetic)
        r = cell * (0.33 + 0.08 * ((a["id"] * 7919) % 5) / 4)
        asts.append({"id": a["id"], "x": (a["col"] + 0.5) * cell, "y": (a["row"] + 0.5) * cell,
                     "r": r, "spent": a["spent"]})
    return {"ship": ship, "asteroids": asts}


def blend(prev, cur, alpha, cell):
    """Animate between two world states; asteroids that wrapped around don't slide."""
    if prev is None or alpha >= 1:
        return cur
    p, c = prev["ship"], cur["ship"]
    ship = dict(c)
    ship["x"], ship["y"] = lerp(p["x"], c["x"], alpha), lerp(p["y"], c["y"], alpha)
    pa = {a["id"]: a for a in prev["asteroids"]}
    asts = []
    for a in cur["asteroids"]:
        b = pa.get(a["id"])
        if b is not None and abs(b["x"] - a["x"]) <= 1.01 * cell:
            a = dict(a, x=lerp(b["x"], a["x"], alpha))
        asts.append(a)
    return {"ship": ship, "asteroids": asts}


def draw_scene(r, s, world, invuln=False):
    r.draw_field()
    cell = s["CELL"]
    for row in s["SAFE_ROWS"]:
        x0, y0 = r.to_px(0, (row + 1) * cell)
        x1, y1 = r.to_px(s["FIELD_WIDTH"], row * cell)
        pygame.draw.rect(r.screen, SAFE_ROW, (x0 + 1, y0 + 1, x1 - x0 - 1, y1 - y0 - 1))
    r.draw_asteroids(world["asteroids"], config.SHOW_ASTEROID_IDS)
    r.draw_walls()
    r.draw_ship(world["ship"], thrusting=False, invulnerable=invuln, show_vel=False)


# ----------------------------------------------------------------------------
# play
# ----------------------------------------------------------------------------
class App:
    def __init__(self, args):
        pygame.init()
        self.player = args.player
        self.settings = grid_settings()
        self.difficulty = args.difficulty or self.settings["DEFAULT_DIFFICULTY"]
        self.seed = args.seed if args.seed is not None else random.randrange(1_000_000)
        self.recorder = None if args.no_record else GridRecorder(args.db)
        self.clock = pygame.time.Clock()
        self.renderer = None
        self.new_game()

    def new_game(self):
        self.game = GridGame(self.seed, self.difficulty, dict(self.settings))
        if self.renderer is None:
            self.renderer = Renderer(self.game.s, caption="Lattice Gate")
        self.renderer.set_settings(self.game.s)
        self.mode = "ready"
        self.prev_world = None
        self.cur_world = to_world(self.game.get_state(), self.game.s)
        self.anim = 1.0
        self.acc = 0.0
        self.queued = None
        self.flash = 0.0
        self.final_outcome = None
        self.best = self.recorder.best_for_seed(self.seed, self.difficulty) if self.recorder else None

    def start_run(self):
        self.mode = "playing"
        self.acc = 0.0
        if self.recorder:
            self.recorder.start_episode(self.game, self.player)

    def end_run(self, outcome=None):
        self.final_outcome = outcome or self.game.outcome
        if self.recorder:
            self.recorder.log_step(self.game.get_state(), None)
            self.recorder.end_episode(self.game, self.final_outcome)
        self.mode = "over"

    def do_turn(self, action):
        before = self.game.get_state()
        if self.recorder:
            self.recorder.log_step(before, action)
        res = self.game.step(action)
        self.prev_world = to_world(before, self.game.s)
        self.cur_world = to_world(self.game.get_state(), self.game.s)
        self.anim = 0.0
        if "hit" in res.events:
            self.flash = 0.6
        if res.done:
            self.end_run()

    def held_action(self):
        keys = pygame.key.get_pressed()
        for k, a in ((pygame.K_UP, UP), (pygame.K_DOWN, DOWN),
                     (pygame.K_LEFT, LEFT), (pygame.K_RIGHT, RIGHT)):
            if keys[k]:
                return a
        return STAY

    def handle_events(self):
        realtime = self.game.s["PLAY_MODE"] == "realtime"
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
                elif k == pygame.K_t:
                    i = MODES.index(self.settings["PLAY_MODE"])
                    self.settings["PLAY_MODE"] = MODES[(i + 1) % len(MODES)]
                    self.new_game()
                elif self.mode == "ready" and k in KEY_ACTION:
                    self.start_run()
                    if realtime:
                        self.queued = KEY_ACTION[k]
                    else:
                        self.do_turn(KEY_ACTION[k])
            elif self.mode == "playing":
                if k == pygame.K_ESCAPE:
                    self.end_run("quit")
                elif k == pygame.K_p and realtime:
                    self.mode = "paused"
                elif k in KEY_ACTION:
                    if realtime:
                        self.queued = KEY_ACTION[k]   # a quick tap still counts
                    else:
                        self.do_turn(KEY_ACTION[k])
            elif self.mode == "paused":
                if k in (pygame.K_p, pygame.K_SPACE):
                    self.mode = "playing"
                    self.acc = 0.0
                elif k == pygame.K_ESCAPE:
                    self.end_run("quit")
        return True

    def draw(self):
        r, g, s = self.renderer, self.game, self.game.s
        world = blend(self.prev_world, self.cur_world, self.anim, s["CELL"])
        draw_scene(r, s, world, invuln=self.flash > 0)
        hits_color = GOOD if g.hits == 0 else BAD
        mode_label = "turn-based" if s["PLAY_MODE"] == "turn" else f"real-time ({s['REALTIME_HZ']}/s)"
        lines = [
            ("LATTICE GATE", TEXT),
            (f"Player: {self.player}", TEXT),
            (f"Seed {g.seed}  |  {g.difficulty}", TEXT),
            None,
            (f"Turn   {g.turn} / {s['MAX_TURNS']}", TEXT),
            (f"Hits   {g.hits}", hits_color),
            (f"Score  {g.turn}  (turns)", TEXT),
            ("(fewer hits first, then", DIM),
            (" fewer turns)", DIM),
            None,
            (f"Mode: {mode_label}  [T]", TEXT),
            (f"Gate: cols {g.gate[0]}-{g.gate[0] + g.gate[1] - 1}", TEXT),
            (f"Recording: {'ON' if self.recorder else 'OFF'}", TEXT),
            None,
            ("ARROWS  move one cell", DIM),
            ("SPACE  wait a turn", DIM),
            ("ESC abandon/quit", DIM),
            ("R retry   N new field", DIM),
            ("1/2/3  easy/medium/hard", DIM),
            ("Light rows are safe", DIM),
        ]
        if self.best:
            p, h, t = self.best
            lines += [None, ("Best on this field:", TEXT), (f"{p}: {h} hits, {t} turns", DIM)]
        r.hud(lines)
        if self.mode == "ready":
            r.overlay("Ready", ["Press an arrow key to start",
                                "Reach the green gate at the top",
                                "Asteroids slide along their lanes"])
        elif self.mode == "paused":
            r.overlay("Paused", ["P or SPACE to resume"])
        elif self.mode == "over":
            title, color = OUTCOME_TEXT.get(self.final_outcome, (self.final_outcome, TEXT))
            r.overlay(title, [f"Turns {g.turn}   Hits {g.hits}",
                              "R retry same field   N new field   ESC quit"], color)
        pygame.display.flip()

    def run(self):
        running = True
        while running:
            frame = self.clock.tick(config.RENDER_FPS) / 1000.0
            running = self.handle_events()
            if not running:
                break
            s = self.game.s
            self.anim = min(1.0, self.anim + frame / max(s["ANIM_TIME"], 1e-6))
            self.flash = max(0.0, self.flash - frame)
            if self.mode == "playing" and s["PLAY_MODE"] == "realtime":
                period = 1.0 / s["REALTIME_HZ"]
                self.acc += min(frame, 0.25)
                while self.acc >= period and self.mode == "playing":
                    self.acc -= period
                    held = self.held_action()
                    action = held if held != STAY else (self.queued if self.queued is not None else STAY)
                    self.queued = None
                    self.do_turn(action)
            self.draw()
        if self.mode in ("playing", "paused"):
            self.end_run("quit")
        if self.recorder:
            self.recorder.close()
        pygame.quit()


# ----------------------------------------------------------------------------
# list / replay
# ----------------------------------------------------------------------------
def list_episodes(db):
    con = sqlite3.connect(db)
    rows = con.execute("SELECT id, started_at, player, difficulty, seed, outcome, hits, turns"
                       " FROM episodes ORDER BY id").fetchall()
    con.close()
    print(f"{'id':>4}  {'started':19}  {'player':12} {'diff':6} {'seed':>7}  {'outcome':10} {'hits':>4} {'turns':>5}")
    for i, st, p, d, sd, o, h, t in rows:
        print(f"{i:>4}  {st:19}  {str(p)[:12]:12} {d:6} {sd:>7}  {str(o):10} "
              f"{h if h is not None else '-':>4} {t if t is not None else '-':>5}")


def replay(db, episode_id):
    ep, steps = load_grid_episode(db, episode_id)
    s = ep["settings"]
    states = [{"turn": st["turn"],
               "ship": {"col": st["ship_col"], "row": st["ship_row"],
                        "heading": st["action"] if st["action"] not in (None, STAY) else UP},
               "asteroids": st["asteroids"]} for st in steps]
    # keep the heading pointing the way the ship last moved
    last = UP
    for i, st in enumerate(steps):
        states[i]["ship"]["heading"] = last
        if st["action"] not in (None, STAY):
            last = st["action"]
    pygame.init()
    r = Renderer(s, caption=f"Lattice Gate replay - episode {episode_id}")
    clock = pygame.time.Clock()
    i, anim, acc, paused, speed = 0, 1.0, 0.0, False, 1.0
    period = 1.0 / s["REALTIME_HZ"]
    worlds = [to_world(st, s) for st in states]
    while True:
        frame = clock.tick(config.RENDER_FPS) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                pygame.quit()
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_SPACE:
                    paused = not paused
                    if i >= len(states) - 1:
                        i, paused = 0, False
                elif ev.key == pygame.K_RIGHT and i < len(states) - 1:
                    paused, i, anim = True, i + 1, 0.0
                elif ev.key == pygame.K_LEFT and i > 0:
                    paused, i, anim = True, i - 1, 1.0
                elif ev.key == pygame.K_UP:
                    speed = min(8.0, speed * 2)
                elif ev.key == pygame.K_DOWN:
                    speed = max(0.25, speed / 2)
                elif ev.key == pygame.K_HOME:
                    i, anim = 0, 1.0
        if not paused and i < len(states) - 1:
            acc += frame * speed
            if acc >= period:
                acc = 0.0
                i += 1
                anim = 0.0
        anim = min(1.0, anim + frame * speed / max(s["ANIM_TIME"], 1e-6))
        world = blend(worlds[i - 1] if i > 0 else None, worlds[i], anim, s["CELL"])
        draw_scene(r, s, world)
        st = steps[i]
        act = "(end)" if st["action"] is None else ACTION_NAMES[st["action"]]
        r.hud([
            (f"Replay  episode {ep['id']}", TEXT),
            (f"{ep['player']}  |  {ep['difficulty']}  |  seed {ep['seed']}", DIM),
            None,
            (f"Turn {st['turn']} / {steps[-1]['turn']}", TEXT),
            (f"Hits  {st['hits']}", TEXT),
            (f"Next action: {act}", TEXT),
            None,
            (f"Result: {ep['outcome']}", GOOD if ep["outcome"] == WIN else BAD),
            (f"{ep['turns']} turns, {ep['hits']} hits", DIM),
            None,
            (f"Speed x{speed:g}  {'PAUSED' if paused else ''}", TEXT),
            ("SPACE play/pause", DIM),
            ("LEFT/RIGHT step  UP/DOWN speed", DIM),
            ("HOME restart  ESC quit", DIM),
        ])
        pygame.display.flip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--player")
    ap.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    ap.add_argument("--seed", type=int)
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--db", default=grid_config.DB_PATH)
    ap.add_argument("--list", action="store_true", help="list recorded runs")
    ap.add_argument("--replay", type=int, metavar="ID", help="replay a recorded run")
    args = ap.parse_args(argv)
    if args.list:
        list_episodes(args.db)
        return
    if args.replay is not None:
        replay(args.db, args.replay)
        return
    if not grid_config.RECORD_BY_DEFAULT:
        args.no_record = True
    if not args.player:
        try:
            args.player = input("Player name: ").strip() or "anonymous"
        except EOFError:
            args.player = "anonymous"
    App(args).run()


if __name__ == "__main__":
    sys.exit(main())
