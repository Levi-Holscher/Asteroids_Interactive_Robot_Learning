# Asteroid Field — CS 7648 Interactive Robot Learning

Fly a ship from the bottom of a 2D asteroid field to the goal at the top. Humans play
it to record demonstrations, and bots later learn from those demos and play the same game.

## Setup (once)

```bash
conda create -n irl_asteroids python=3.10 -y
conda activate irl_asteroids
pip install -r requirements.txt
```
(Plain `python -m venv .venv` + `pip install -r requirements.txt` works too.)

## Play

```bash
python play.py --player levi                  # medium, random field, recording ON
python play.py --player levi --difficulty hard --seed 123
python play.py --no-record                    # just practise
```

| Key | In a run | Between runs |
|---|---|---|
| ← / → | rotate (tap = one fixed step, hold = repeat) | start the run |
| SPACE | thrust | start the run |
| P | pause | |
| ESC | abandon the run | quit |
| R | | retry the **same** field |
| N | | new random field |
| 1 / 2 / 3 | | easy / medium / hard |
| M | | speed cap on/off |
| G | | cycle goal: whole top edge → centered gate → offset gate |
| T | | cycle rotation mode: step → continuous → momentum |

## Rules

- You start at the same spot near the bottom with a random heading (fixed per seed).
- **Win:** cross the green goal at the top (the whole top edge, or a gate if one is set).
- **Out of bounds (loss):** touching the left, right, or bottom wall, or the top wall outside a gate.
- **Timeout (loss):** 60 s.
- **Asteroid hit:** doesn't end the run. Your hit count goes up, you get 1 s of
  invulnerability (the ship blinks yellow), and that asteroid turns dark and harmless. It
  keeps moving and bouncing, so the rest of the field plays out the same for everyone.
- **Ranking:** wins beat losses → fewer hits always beat more hits (hit "tiers") → lower score.
  `score = 0.5·time/10 + 0.5·fuel/2` (weights and reference values are in `config.py`).
- **Fuel** = seconds of main-thruster burn, plus a small cost per rotation step.
- **Field:** 1.6 wide × 3.0 tall, plus a visible margin outside the walls (20% of the
  width on every side) so you can see asteroids coming before they enter. Asteroids
  spawn beyond that margin.
- **Physics:** constant thrust, no gravity, no ship mass, optional drag. The speed cap is
  on by default; a straight full-speed crossing takes about 7.3 s. Asteroids move with
  constant acceleration, keep streaming in from the sides and the top, and **bounce off
  each other** (elastic collisions, mass ∝ area). The ship doesn't push asteroids.
- **Same seed = same asteroids**, regardless of what the player does, so humans and bots
  can be compared on identical fields. Asteroid motion doesn't depend on the ship at all.

## Tuning

Everything is in **`config.py`**: tick rate (`TICK_HZ = 20`), field size, start
position, goal gate, thrust, speed cap, drag, rotation mode and step size, fuel costs,
scoring weights, difficulty presets (asteroid count, spawn rate, speeds, sizes), and
display sizes.

## Recorded data

Runs are saved to `data/demos.sqlite`. SQLite is a single-file database built into
Python, with no server to install.

- `episodes` table: player, seed, difficulty, the full settings used, outcome, time, fuel, hits, score
- `steps` table: one row per tick with the ship state, the action taken that tick
  (`action_turn` −1/0/+1, `action_thrust` 0/1), the raw keys, and every asteroid's
  position, velocity, acceleration, radius and `spent` flag (JSON)

```bash
python replay.py --list          # list recorded runs
python replay.py --episode 3     # watch one (SPACE pause, ←/→ step, ↑/↓ speed)
python export_csv.py             # dump to data/export/*.csv
```

```python
import sqlite3, pandas as pd
con = sqlite3.connect("data/demos.sqlite")
episodes = pd.read_sql("SELECT * FROM episodes", con)
```

Raw states are stored rather than hand-picked features, so you can design state
features later and recompute them from old demos.

## Code layout

```
config.py            all tunable settings
play.py              keyboard game + recording
replay.py            watch recorded runs
export_csv.py        database -> CSV
bot_example.py       run the game headless from code (baseline autopilot)
game/sim.py          game logic, no graphics (AsteroidGame, Action) - bots use this
game/recorder.py     SQLite recording / loading
game/render.py       pygame drawing
game/settings.py     settings snapshot / overrides
tests/test_sim.py    python -m pytest -q
```

Driving the game from code (roughly 300–1000× real time with no window, depending on difficulty):

```python
from game import AsteroidGame, Action, ACTIONS, default_settings
g = AsteroidGame(seed=1, difficulty="medium",
                 settings=default_settings(GOAL_GATE=(0.8, 0.5)))
while not g.done:
    g.step(Action(turn=0, thrust=True))     # turn: +1 left, -1 right, 0 none
print(g.outcome, g.hits, g.t, g.fuel, g.score())
```

## Version history

- **0.3.0**: visible margin around the walls (asteroids are seen before they enter);
  about 30% more asteroids at every difficulty.
- **0.2.0**: field 1.6 × 3.0 (taller, narrower); more, smaller asteroids; asteroids bounce
  off each other; hit asteroids become harmless "spent" rocks instead of disappearing.
- **0.1.0**: first playable version.
