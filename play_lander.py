"""Play the real Gymnasium Lunar Lander with the keyboard (for comparing difficulty).

Run:  python play_lander.py
Keys: W = main engine, A / D = side engines (rotate). ESC closes the window.
Goal: land gently between the flags. One key at a time (no rotate + thrust together).

Your score prints in the terminal after each attempt.
Roughly: crash ~ -100 to -300, hovering until timeout ~ -100 to 0,
sloppy landing ~ 0 to 100, good landing 100-200, "solved" >= 200.
"""

import gymnasium as gym
from gymnasium.utils.play import play

FPS = 20          # lower = slower and easier (the env's normal speed is 50)

total = 0.0
attempt = 0


def show_score(obs_t, obs_tp1, action, rew, terminated, truncated, info):
    global total, attempt
    total += rew
    if terminated or truncated:
        attempt += 1
        if total >= 200:
            verdict = "solved-level landing!"
        elif total >= 100:
            verdict = "landed"
        elif total > 0:
            verdict = "rough landing"
        else:
            verdict = "crashed / failed"
        print(f"Attempt {attempt}: score {total:7.1f}  ({verdict})")
        total = 0.0


env = gym.make("LunarLander-v3", render_mode="rgb_array")
# Actions: 0 = nothing, 1 = left side engine, 2 = main engine, 3 = right side engine.
# The env only allows ONE engine per step, so when you hold W and tap A/D, the side
# engine wins for that moment and the main engine resumes when you let go.
# If A and D feel backwards, swap the 1s and 3s.
KEYS = {
    ("w",): 2,
    ("a",): 1,
    ("d",): 3,
    ("a", "w"): 1,
    ("d", "w"): 3,
}
play(env, keys_to_action=KEYS, noop=0, fps=FPS, zoom=1.5, callback=show_score)
