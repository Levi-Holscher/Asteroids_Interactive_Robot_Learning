# CLAUDE.md: project context for Claude Code

CS 7648 Interactive Robot Learning (Georgia Tech, Fall 2026) team project.
Team: Levi Holscher, Muktaka Joshipura, Adrian Kalisz. Final deadline: Dec 14, 2026.
Budget: ~10 hours/person/week, including paper and presentation, so keep solutions simple.

## Team and lanes

Work is split into three lanes so all three people can work at once. Lanes not yet claimed
(as of Nov 9, 2026); update this table when they are.

| Lane | Owner | Owns |
|---|---|---|
| Data & humans | TBD | game tweaks, held-out test seeds, demo recording, freeze-frame marking tool, marking sessions |
| Pilot | TBD | Gym environment wrapper, behavior cloning warm-start pilot, GAIL/AIRL if time allows, evaluation script |
| Focus | TBD | feature extractor, focus model, pruning rules (focus / closest / soonest / random) |

- Levi is newer to CS and git: explain commands and changes step by step, with diagrams
  where helpful, before doing them.
- To avoid waiting on each other: agree on the feature extractor's output format first, then
  use stand-ins until real data exists (bot demos for the pilot, rule-based fake marks for
  the focus model).
- Git workflow: never commit straight to `main`. One branch per piece of work, named
  `<name>/<topic>` (e.g. `levi/marking-tool`), merged through a pull request that a
  teammate looks at.

### Subtasks (ID: task — waits on)

"Waits on" = must finish first. "(later: X)" = a stand-in is used until X delivers real data.

Data & humans
- D1: per-person demo files `data/demos_<name>.sqlite` — nothing (done; how to share the
  files between laptops is still open, see Environment)
- D2: held-out test seed list in `config.py`; `play.py` refuses to record on them — nothing
  (done: seeds ≥ 900,000 reserved; `TEST_SEEDS` and `VALIDATION_SEEDS`, 100 each)
- D3: game tweaks the team agrees on — nothing. Proposed (not built yet, needs team OK):
  (a) field thins from ~43 to ~30 asteroids in the first 10 s (start is denser than the
  spawn rate sustains; side spawns skip the bottom 25%): fix with a ~10 s warm-up before
  t = 0, a configurable side-spawn height (~5%), then tune spawn_per_sec;
  (b) remove asteroid acceleration (barely visible; makes t*/d_min exact): accel_max = 0
  in every difficulty, no code change. Do these before recording real demos.
- D4: written recording plan (difficulty, runs per person, practice runs discarded) — nothing
- D5: marking tool v1: pause replay, click asteroids, save
  (episode_id, tick, asteroid_id, relevant) to `data/marks_<name>.sqlite` — nothing
- D6: marking tool v2: auto-jump to frames worth marking, keyboard next/skip — D5
- D7: collect 100 demo runs + 300 marked frames (everyone) — D1, D5
- D8: ~30 frames marked by 2+ people to measure human agreement — D5

Pilot
- P1: Gym environment wrapper (reset(seed), step(action) → features, reward, done) — F1
- P2: bot demo generator → `data/demos_bot.sqlite` — nothing
- P3: demo loader: all demo files → (features, action) arrays — F1
- P4: behavior cloning pilot on masked features — P2, P3 (later: D7)
- P5: evaluation script on the held-out seeds, 95% CIs — P1, D2
- P6: learning curves vs number of demos / training time — P4, P5
- P7 (reach): GAIL / AIRL via the `imitation` library — P1, P4

Focus
- F1: feature contract: function signature, array shapes, docstring, shape-correct stub.
  Do first; the pilot lane codes against it — nothing
- F2: real features (t*, d_min, walls) + tests — F1
- F3: rule-based fake marks (e.g. relevant if d_min < threshold) — F2
- F4: pruning rules (all / closest / soonest-to-hit / random) that set the mask — F1
- F5: focus model (logistic regression first) — F2, F3 (later: D7)
- F6: agreement of focus model with held-out human marks — F5, D7
- F7: focus model plugged into the pruner, sweep k = 1, 2, 3, 5 — F4, F5

Final: X: comparison runs for the paper — P4, P5, F7

### Draft feature contract (F1 owner finalizes)

`extract_features(state, settings, K=10)` returns `ship` (7,), `ast` (K, 8) sorted nearest
first with columns dx, dy, dvx, dvy, r, t*, d_min, distance (all relative to the ship),
`mask` (K,) with 1 = real asteroid, 0 = padding, and `ids` (K,) with -1 for padding. Spent
asteroids are excluded. Pruning only zeroes entries of `mask`, so the same pilot code runs in
every condition.

## The research question (from the revised proposal)

Teach a computer to fly a spaceship through an asteroid field from human demonstrations,
and let humans teach it **what to pay attention to**. People pause ("freeze-frame") recorded
runs and mark which asteroids matter for the next move. A **focus model** (saliency predictor)
learns from those marks, and the **pilot** only sees the asteroids the focus model picks.
Claim to test: human-guided focus makes learning faster and better than seeing everything.

Related work we build on: AGIL (Zhang et al. 2018, human gaze → attention → imitation),
Atari-HEAD dataset, ViSaRL (Liang et al. 2024, human saliency for RL), COACH (Celemin &
Ruiz-del-Solar 2015, corrective human feedback), LIFI (Hedlund-Botti et al., features from
interventions).

### Checkpoints
- **Midterm:** game + freeze-frame marking tool complete; 100 human demo runs; 300
  human-marked frames; a first warm-start pilot and a first focus model trained.
- **Final:** pilots trained on human-pruned inputs compared against (1) unpruned (all
  asteroids), (2) randomly pruned, (3) closest-asteroid rule, on 100 held-out test fields
  each. Metrics: hits, success rate, training time. Paper + presentation.

### Planned pipeline (build in this order)
1. **Feature extractor**: per-asteroid features relative to the ship (relative position,
   relative velocity, radius, time of closest approach t* and miss distance d_min over a
   short horizon ~2-3 s) + ship state (velocity, heading, wall/goal distances).
   Pad to a fixed K slots with an "is real" flag when fewer asteroids exist.
2. **Demo loader**: read `data/demos.sqlite` → (state, action) pairs. Each `steps` row is
   the state BEFORE the action plus the action taken; the final row has NULL action.
3. **Warm-start pilot**: behavior cloning (AGIL-style) on all asteroids = the "sees
   everything" baseline. The proposal also mentions a GAIL-style objective; the team still
   needs to pick ONE name/method and use it consistently.
4. **Freeze-frame marking tool**: reuse `replay.py`; pause, click asteroids → store
   (episode_id, tick, asteroid_id, relevant 0/1) in a new table/database.
5. **Focus model**: predicts per-asteroid relevance from the features, trained on the marks.
   Check agreement with held-out human marks.
6. **Pruned pilots**: pilot sees only the top-k asteroids (k = 1, 2, 3, maybe 5) chosen by:
   focus model / closest / soonest-to-hit / random, plus the see-everything baseline.
7. **Evaluation**: 100 held-out seeds (never used for demos), 95% confidence intervals.
Optional/reach: human-in-the-loop corrections during training; recovering a reward function.

## Code layout

- `config.py`: all settings for the main game (field 1.6 × 3.0 world units, 20 Hz ticks,
  speed cap, rotation mode, scoring, difficulty presets, visible margin around walls).
- `game/sim.py`: headless main game. `AsteroidGame(seed, difficulty, settings)`,
  `.step(Action(turn, thrust))`, `.get_state()`, `.done`, `.outcome`. `ACTIONS` = 6 discrete
  actions. `turn`: +1 = rotate left (CCW), -1 = right, 0 = none. No pygame here.
- `game/settings.py`: `default_settings(**overrides)` snapshot of config.py.
- `game/recorder.py`: SQLite recording (`episodes`, `steps` tables) + `load_episode()`.
  One file per player: `demo_db_path(player)` → `data/demos_<player>.sqlite`;
  `find_demo_dbs()` lists them all (the old shared `data/demos.sqlite` = early test runs).
  Always read recordings through `load_episode()`, which decodes both storage formats.
  Refuses to record on held-out seeds (`held_out_seeds=False` turns that off; Dodge Run does).
- `game/seeds.py`: held-out seeds. Every seed ≥ `config.RESERVED_SEED_START` (900,000) is
  for evaluation only; `random_demo_seed()` picks a safe one. Tune on `VALIDATION_SEEDS`;
  use `TEST_SEEDS` once, for the final comparison.
- `game/render.py`: shared pygame drawing (Renderer); `play.py` / `replay.py` use it.
- `play.py --player <name>`: keyboard play + recording (arrows rotate, SPACE thrust).
  `replay.py --player <name> --list` / `--episode N` (or `--db <file>`). `export_csv.py` dumps the DB to CSV. `bot_example.py`: headless loop.
- Second game **Dodge Run**: `dodge_config.py`, `game/dodge.py` (`DodgeGame`, 3 actions,
  same `Action` type: turn +1 = slide left), `play_dodge.py`, DB `data/dodge_demos.sqlite`.
  Score = hits only; movement is tracked but not scored.
- Third game **Lattice Gate** (grid, turn-based): `grid_config.py`, `game/grid.py`
  (`GridGame`, actions STAY/UP/DOWN/LEFT/RIGHT = 0-4, `shortest_safe_path()` oracle,
  `GridRecorder`), `play_grid.py` (`--list`, `--replay N`), DB `data/grid_demos.sqlite`.
- Current project focus is the **main asteroid game**; Dodge Run and Lattice Gate are kept
  but not part of the current proposal.
- `tests/`: `python -m pytest -q` (31 tests at last count). Keep them passing; add tests
  for new code.

## Important behaviors / invariants

- **Same seed = same asteroid field regardless of player actions.** Asteroids are physics
  objects that bounce off each other; an asteroid that hits the ship becomes "spent"
  (harmless, drawn dim) but stays in the physics, so the field never depends on the player.
  Don't break this. It's what makes humans and bots comparable on identical fields.
- Hits don't end a run (1 s invulnerability). Out of bounds (side/bottom walls) or a timeout
  are losses; crossing the top (or a gate) is a win.
- Recorded runs store their full settings JSON, so replays stay valid after code changes.
- Hand-picked features should be computed from recorded raw states (asteroid x, y, vx, vy,
  ax, ay, r, spent), so old demos can be reprocessed when features change.
- The headless sim runs roughly 300-1000× real time, so CPU is enough; no GPU needed.

## Environment

- Windows + PyCharm; Python 3.10-3.12 recommended (3.14 can't install Box2D and may need
  `pygame-ce` instead of `pygame`). `pip install -r requirements.txt`.
- Teammates work on different machines and sync through GitHub
  (Levi-Holscher/Asteroids_Interactive_Robot_Learning). Run `git pull` before starting.
- Demo files use a compact recording format (positions rounded to 3 decimals, compressed,
  radius/acceleration stored once per asteroid): ~0.20 MB per 10 s run, ~10x smaller than
  the old format, which `load_episode()` still reads. They are binary, so git can't merge
  them; per-player files avoid that. GitHub rejects files over 100 MB.
- PowerShell 5 doesn't support `&&`; give commands one per line.

## Working style for this repo

- Keep tunable numbers in config files, not hard-coded.
- Prefer small, readable code over clever frameworks; the team is newer to CS
  (mechanical engineering background).
- When writing math in docs or messages, use Unicode subscripts (t*, d_min is OK in code)
  and plain names for methods rather than piles of acronyms.
