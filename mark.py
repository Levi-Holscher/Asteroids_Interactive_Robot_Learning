"""
Freeze-frame marking tool (task D5): pause a recorded run and click the asteroids that
matter for the ship's next move.

    python mark.py --marker adrian --player levi --list       # levi's episodes
    python mark.py --marker adrian --player levi --episode 3  # mark levi's episode 3
    python mark.py --marker adrian --db data/demos.sqlite --episode 5

--marker is YOU (the person marking); --player / --db picks whose demo to mark.
Marks are saved to data/marks_<marker>.sqlite (see game/marks.py).

Controls
    SPACE        play / pause                 LEFT/RIGHT   step 1 tick (SHIFT: 10 ticks)
    UP/DOWN      speed x2 / x0.5              HOME         back to the start
    CLICK        (paused) mark / unmark an asteroid as relevant
    ENTER        save this frame: clicked = relevant, every other live asteroid = not relevant
    C            clear your clicks on this frame
    DELETE/BACKSPACE   remove this frame's saved marks
    ESC          quit

Clicks that are not saved with ENTER are dropped when you move to another tick.
"""

import argparse
import os
import sqlite3
import sys

import pygame

import config
from game.marks import MarkStore, asteroid_at, live_asteroid_ids, marks_db_path
from game.recorder import load_episode, resolve_demo_db
from game.render import BAD, DIM, GOOD, TEXT, Renderer, interpolate_state
from replay import list_episodes, to_state


class MarkSession:
    """Marking logic for one episode, without any drawing (so it can be tested).

    `i` is the index of the current step; `selected` holds the asteroid ids clicked as
    relevant on that step; `saved` is what is stored for that step ({id: 0/1} or None)."""

    def __init__(self, store, demo_file, episode, steps, marker):
        self.store = store
        self.demo_file = demo_file
        self.ep = episode
        self.steps = steps
        self.marker = marker
        self.last = len(steps) - 1
        self.i = 0
        self.selected = set()
        self.saved = None
        self.status = ""
        self._load()

    # -- where we are ---------------------------------------------------------
    @property
    def step(self):
        return self.steps[self.i]

    @property
    def tick(self):
        return self.step["tick"]

    def live_ids(self):
        return live_asteroid_ids(self.step["asteroids"])

    def can_mark(self):
        """The final recorded state has no next move, so it can't be marked."""
        return self.i < self.last

    @property
    def saved_relevant(self):
        return {i for i, r in (self.saved or {}).items() if r}

    @property
    def dirty(self):
        """True if the clicks on this frame differ from what is saved."""
        if self.saved is None:
            return bool(self.selected)
        return self.selected != self.saved_relevant

    def marked_ticks(self):
        return self.store.marked_ticks(self.demo_file, self.ep["id"])

    # -- moving around --------------------------------------------------------
    def go_to(self, i):
        i = max(0, min(self.last, i))
        if i == self.i:
            return
        if self.dirty:
            self.status = f"Unsaved clicks on tick {self.tick} dropped"
        self.i = i
        self._load()

    def _load(self):
        self.saved = self.store.load_frame(self.demo_file, self.ep["id"], self.tick)
        self.selected = set(self.saved_relevant)

    # -- marking --------------------------------------------------------------
    def toggle(self, asteroid_id):
        if not self.can_mark():
            self.status = "The final frame can't be marked"
            return
        if asteroid_id not in self.live_ids():
            return
        self.selected ^= {asteroid_id}
        self.status = ""

    def click(self, x, y, pad=0.0):
        """Toggle the asteroid under world point (x, y). Returns its id or None."""
        a_id = asteroid_at(self.step["asteroids"], x, y, pad)
        if a_id is not None:
            self.toggle(a_id)
        return a_id

    def clear(self):
        self.selected = set()
        self.status = "Clicks cleared (press ENTER to save)"

    def save(self):
        if not self.can_mark():
            self.status = "The final frame can't be marked"
            return False
        ids = self.live_ids()
        if not ids:
            self.status = "No live asteroids on this frame"
            return False
        self.store.save_frame(self.demo_file, self.ep["id"], self.tick, ids,
                              self.selected, self.marker)
        self._load()
        self.status = f"Saved tick {self.tick}: {len(self.selected)} of {len(ids)} relevant"
        return True

    def delete(self):
        if self.saved is None:
            self.status = "Nothing saved on this frame"
            return
        self.store.delete_frame(self.demo_file, self.ep["id"], self.tick)
        self._load()
        self.status = f"Removed the marks on tick {self.tick}"


def latest_episode(db):
    con = sqlite3.connect(db)
    row = con.execute("SELECT MAX(id) FROM episodes").fetchone()
    con.close()
    return row[0] if row else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--marker", required=True, help="your name; marks go to data/marks_<marker>.sqlite")
    ap.add_argument("--player", help="mark this player's demos, data/demos_<player>.sqlite")
    ap.add_argument("--db", help="demo file to mark (overrides --player)")
    ap.add_argument("--episode", type=int, help="episode id (default: the most recent)")
    ap.add_argument("--list", action="store_true", help="list the episodes and quit")
    ap.add_argument("--marks-db", help="marks file (default: data/marks_<marker>.sqlite)")
    args = ap.parse_args(argv)

    db = resolve_demo_db(args.db, args.player)
    if not os.path.exists(db):
        print(f"No demo file at {db} (nothing recorded yet?)")
        return 1
    print(f"Reading {db}")
    if args.list:
        list_episodes(db)
        return 0
    episode = args.episode if args.episode is not None else latest_episode(db)
    if episode is None:
        print("No recorded episodes yet.")
        return 1
    ep, steps = load_episode(db, episode)
    if not steps:
        print("That episode has no steps recorded.")
        return 1

    marks_path = args.marks_db or marks_db_path(args.marker)
    print(f"Saving marks to {marks_path}")
    store = MarkStore(marks_path)
    session = MarkSession(store, os.path.basename(db), ep, steps, args.marker)
    try:
        run_window(session)
    finally:
        store.close()
    return 0


def run_window(session):
    ep, steps = session.ep, session.steps
    states = [to_state(s) for s in steps]

    pygame.init()
    r = Renderer(ep["settings"], caption=f"Mark - episode {ep['id']}")
    clock = pygame.time.Clock()
    dt = 1.0 / ep["settings"]["TICK_HZ"]
    pad = config.MARK_CLICK_PAD_PX / r.ppu        # click tolerance in world units
    acc, speed, paused = 0.0, 1.0, True           # start paused: this is a marking tool

    while True:
        frame = clock.tick(config.RENDER_FPS) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not paused:
                    paused, acc = True, 0.0
                    session.status = "Paused - click again to mark"
                elif r.view_rect.collidepoint(ev.pos):
                    session.click(*r.to_world(*ev.pos), pad=pad)
            if ev.type != pygame.KEYDOWN:
                continue
            jump = 10 if ev.mod & pygame.KMOD_SHIFT else 1
            if ev.key == pygame.K_ESCAPE:
                pygame.quit()
                return
            elif ev.key == pygame.K_SPACE:
                paused, acc = not paused, 0.0
                if session.i >= session.last:
                    session.go_to(0)
                    paused = False
            elif ev.key == pygame.K_RIGHT:
                paused, acc = True, 0.0
                session.go_to(session.i + jump)
            elif ev.key == pygame.K_LEFT:
                paused, acc = True, 0.0
                session.go_to(session.i - jump)
            elif ev.key == pygame.K_UP:
                speed = min(8.0, speed * 2)
            elif ev.key == pygame.K_DOWN:
                speed = max(0.125, speed / 2)
            elif ev.key == pygame.K_HOME:
                acc = 0.0
                session.go_to(0)
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                session.save()
            elif ev.key == pygame.K_c:
                session.clear()
            elif ev.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
                session.delete()

        if not paused and session.i < session.last:
            acc += min(frame, 0.25) * speed
            while acc >= dt and session.i < session.last:
                acc -= dt
                session.go_to(session.i + 1)
        i = session.i
        alpha = 0.0 if paused or i >= session.last else acc / dt
        st = interpolate_state(states[i], states[min(i + 1, session.last)], alpha)
        step = steps[i]

        r.draw_field()
        r.draw_trail([(s["ship"]["x"], s["ship"]["y"]) for s in states[: i + 1]])
        r.draw_asteroids(st["asteroids"], config.SHOW_ASTEROID_IDS)
        r.draw_walls()
        r.draw_rings(st["asteroids"], session.selected, GOOD)   # after the walls: always visible
        r.draw_ship(st["ship"], thrusting=bool(step["action_thrust"]),
                    invulnerable=st["invulnerable"], t=st["t"])

        if session.dirty:
            frame_line = ("Frame: NOT SAVED (press ENTER)", BAD)
        elif session.saved is not None:
            frame_line = (f"Frame: saved, {len(session.saved_relevant)} relevant", GOOD)
        else:
            frame_line = ("Frame: not marked", DIM)
        n_marked = len(session.marked_ticks())
        r.hud([
            (f"Marking  episode {ep['id']}", TEXT),
            (f"{ep['player']}  |  {ep['difficulty']}  |  seed {ep['seed']}", DIM),
            (f"marker: {session.marker}", DIM),
            None,
            (f"Tick {step['tick']} / {steps[-1]['tick']}", TEXT),
            (f"Time  {step['t']:6.2f} s", TEXT),
            (f"Speed x{speed:g}  {'PAUSED' if paused else ''}", TEXT),
            None,
            (f"Clicked: {len(session.selected)} of {len(session.live_ids())}", TEXT),
            frame_line,
            (f"Frames marked here: {n_marked}", TEXT),
            (f"All frames in file: {session.store.count_frames()}", DIM),
            (session.status, DIM) if session.status else None,
            None,
            ("SPACE play/pause", DIM),
            ("LEFT/RIGHT step (SHIFT x10)", DIM),
            ("CLICK mark   ENTER save", DIM),
            ("C clear   DEL remove saved", DIM),
            ("UP/DOWN speed  HOME start", DIM),
            ("ESC quit", DIM),
        ])
        pygame.display.flip()


if __name__ == "__main__":
    sys.exit(main())
