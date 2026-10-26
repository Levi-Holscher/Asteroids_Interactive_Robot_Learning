"""
Watch a recorded run.

    python replay.py --list              # show recorded episodes
    python replay.py                     # replay the most recent episode
    python replay.py --episode 12

Controls: SPACE pause/play   LEFT/RIGHT step one tick (when paused)
          UP/DOWN speed x2 / x0.5   HOME restart   ESC quit

The replay draws exactly what was recorded (it doesn't re-simulate), so old recordings
still play back correctly after the game code changes.
"""

import argparse
import sqlite3
import sys

import pygame

import config
from game.recorder import load_episode
from game.render import BAD, DIM, GOOD, TEXT, Renderer, interpolate_state


def list_episodes(db):
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT id, started_at, player, difficulty, seed, outcome, hits, time_s, fuel, score"
        " FROM episodes ORDER BY id").fetchall()
    con.close()
    print(f"{'id':>4}  {'started':19}  {'player':12} {'diff':6} {'seed':>7}  {'outcome':14}"
          f" {'hits':>4} {'time':>7} {'fuel':>6} {'score':>6}")
    for r in rows:
        i, st, p, d, sd, o, h, t, f, sc = r
        fmt = lambda v, n: f"{v:{n}.2f}" if v is not None else " " * (n - 1) + "-"
        print(f"{i:>4}  {st:19}  {str(p)[:12]:12} {d:6} {sd:>7}  {str(o):14}"
              f" {h if h is not None else '-':>4} {fmt(t, 7)} {fmt(f, 6)} {fmt(sc, 6)}")


def to_state(step):
    return {
        "t": step["t"], "tick": step["tick"],
        "ship": {"x": step["ship_x"], "y": step["ship_y"], "vx": step["ship_vx"],
                 "vy": step["ship_vy"], "heading": step["ship_heading"], "omega": step["ship_omega"]},
        "fuel": step["fuel"], "hits": step["hits"], "invulnerable": bool(step["invulnerable"]),
        "asteroids": step["asteroids"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--episode", type=int)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)

    if args.list:
        list_episodes(args.db)
        return
    if args.episode is None:
        con = sqlite3.connect(args.db)
        row = con.execute("SELECT MAX(id) FROM episodes").fetchone()
        con.close()
        if not row or row[0] is None:
            print("No recorded episodes yet.")
            return
        args.episode = row[0]

    ep, steps = load_episode(args.db, args.episode)
    if not steps:
        print("That episode has no steps recorded.")
        return
    states = [to_state(s) for s in steps]

    pygame.init()
    r = Renderer(ep["settings"], caption=f"Replay - episode {ep['id']}")
    clock = pygame.time.Clock()
    dt = 1.0 / ep["settings"]["TICK_HZ"]
    i, acc, speed, paused = 0, 0.0, 1.0, False
    last = len(states) - 1

    while True:
        frame = clock.tick(config.RENDER_FPS) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    pygame.quit()
                    return
                if ev.key == pygame.K_SPACE:
                    paused = not paused
                    if i >= last:
                        i, paused = 0, False
                elif ev.key == pygame.K_RIGHT:
                    paused, i, acc = True, min(last, i + 1), 0.0
                elif ev.key == pygame.K_LEFT:
                    paused, i, acc = True, max(0, i - 1), 0.0
                elif ev.key == pygame.K_UP:
                    speed = min(8.0, speed * 2)
                elif ev.key == pygame.K_DOWN:
                    speed = max(0.125, speed / 2)
                elif ev.key == pygame.K_HOME:
                    i, acc = 0, 0.0
        if not paused and i < last:
            acc += min(frame, 0.25) * speed
            while acc >= dt and i < last:
                acc -= dt
                i += 1
        alpha = 0.0 if paused or i >= last else acc / dt
        st = interpolate_state(states[i], states[min(i + 1, last)], alpha)
        step = steps[i]

        r.draw_field()
        r.draw_trail([(s["ship"]["x"], s["ship"]["y"]) for s in states[: i + 1]])
        r.draw_asteroids(st["asteroids"], config.SHOW_ASTEROID_IDS)
        r.draw_walls()
        r.draw_ship(st["ship"], thrusting=bool(step["action_thrust"]),
                    invulnerable=st["invulnerable"], t=st["t"])
        turn = step["action_turn"]
        turn_s = {1: "LEFT", -1: "RIGHT", 0: "-", None: "(end)"}[turn]
        oc_color = GOOD if ep["outcome"] == "win" else BAD
        r.hud([
            (f"Replay  episode {ep['id']}", TEXT),
            (f"{ep['player']}  |  {ep['difficulty']}  |  seed {ep['seed']}", DIM),
            (f"{ep['started_at']}", DIM),
            None,
            (f"Tick {step['tick']} / {steps[-1]['tick']}", TEXT),
            (f"Time  {step['t']:6.2f} s", TEXT),
            (f"Fuel  {step['fuel']:6.2f}", TEXT),
            (f"Hits  {step['hits']}", TEXT),
            None,
            (f"Action: turn {turn_s}", TEXT),
            (f"        thrust {'ON' if step['action_thrust'] else '-'}", TEXT),
            None,
            (f"Result: {ep['outcome']}", oc_color),
            (f"{ep['time_s'] or 0:.2f} s, fuel {ep['fuel'] or 0:.2f}, {ep['hits']} hits", DIM),
            None,
            (f"Speed x{speed:g}  {'PAUSED' if paused else ''}", TEXT),
            ("SPACE play/pause", DIM),
            ("LEFT/RIGHT step  UP/DOWN speed", DIM),
            ("HOME restart  ESC quit", DIM),
        ])
        pygame.display.flip()


if __name__ == "__main__":
    sys.exit(main())
