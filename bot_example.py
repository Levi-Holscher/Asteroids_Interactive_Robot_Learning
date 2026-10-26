"""
Example of driving the game from code with no window - the starting point for bots.

    python bot_example.py --episodes 50 --difficulty medium

The "bot" here is a dumb hand-written autopilot (point up, burn to cruise speed, coast).
It ignores asteroids entirely, so it's a baseline, not a learner.
"""

import argparse
import math
import time

from game import Action, AsteroidGame


def autopilot(game):
    h = game.ship.heading
    err = (math.pi / 2 - h + math.pi) % (2 * math.pi) - math.pi
    half_step = math.radians(game.s["ROTATE_STEP_DEG"]) / 2
    turn = 0 if abs(err) < half_step else (1 if err > 0 else -1)
    thrust = turn == 0 and game.ship.vy < 0.3
    return Action(turn, thrust)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=50)
    ap.add_argument("--difficulty", default="medium")
    args = ap.parse_args()

    t0, ticks, results = time.time(), 0, []
    for seed in range(args.episodes):
        g = AsteroidGame(seed=seed, difficulty=args.difficulty)
        while not g.done:
            g.step(autopilot(g))
        ticks += g.tick
        results.append(g)
    dt = time.time() - t0
    wins = [g for g in results if g.outcome == "win"]
    print(f"{len(wins)}/{len(results)} reached the goal")
    for h in range(0, 6):
        n = sum(1 for g in wins if g.hits == h)
        if n:
            print(f"  {h} hits: {n}")
    print(f"simulated {ticks} ticks in {dt:.2f} s  ({ticks / dt:,.0f} ticks/s, "
          f"{ticks / dt / 20:,.0f}x real time)")


if __name__ == "__main__":
    main()
