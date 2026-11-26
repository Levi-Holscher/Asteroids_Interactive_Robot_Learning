"""
Freeze-frame marks: which asteroids a person said matter for the ship's next move.

One file per person who marks: marks_db_path("Adrian") -> data/marks_adrian.sqlite,
so teammates never change the same file (same idea as the per-player demo files).

Table
-----
marks : one row per asteroid per marked frame
    demo_file    name of the demo file the frame comes from (e.g. "demos_levi.sqlite").
                 Needed because every demo file numbers its episodes from 1.
    episode_id   episode in that demo file
    tick         tick of the frame (the state BEFORE that tick's action)
    asteroid_id  asteroid id within the episode
    relevant     1 = the person clicked it ("matters"), 0 = it was there but not clicked
    marker       who marked it
    marked_at    when

When a frame is saved, EVERY live (not spent) asteroid in it gets a row: the clicked ones
with relevant = 1, all others with relevant = 0. So "not relevant" is stored explicitly,
and a frame that was never saved has no rows at all (it was skipped, not "all irrelevant").
Saving a frame again replaces its old rows.

Read all marks for training:
    from game.marks import find_marks_dbs, load_marks
    rows = [r for path in find_marks_dbs() for r in load_marks(path)]
"""

import glob
import os
import sqlite3
import time

import config
from game.recorder import player_slug

SCHEMA = """
CREATE TABLE IF NOT EXISTS marks (
    demo_file    TEXT,
    episode_id   INTEGER,
    tick         INTEGER,
    asteroid_id  INTEGER,
    relevant     INTEGER,   -- 1 = clicked as relevant, 0 = present but not clicked
    marker       TEXT,
    marked_at    TEXT,
    PRIMARY KEY (demo_file, episode_id, tick, asteroid_id)
);
"""

MARK_COLUMNS = ("demo_file", "episode_id", "tick", "asteroid_id", "relevant", "marker", "marked_at")


def marks_db_path(marker, data_dir=None):
    """Where `marker`'s marks are saved: data/marks_<marker>.sqlite."""
    return os.path.join(data_dir or config.DATA_DIR, f"marks_{player_slug(marker)}.sqlite")


def find_marks_dbs(data_dir=None):
    """Every per-person marks file (data/marks_*.sqlite), sorted by name."""
    return sorted(glob.glob(os.path.join(data_dir or config.DATA_DIR, "marks_*.sqlite")))


def live_asteroid_ids(asteroids):
    """Ids of the asteroids that can still be marked (spent ones are harmless)."""
    return [a["id"] for a in asteroids if not a.get("spent", False)]


def asteroid_at(asteroids, x, y, pad=0.0):
    """Id of the live asteroid under the world point (x, y), or None.

    A click counts if it lands within the asteroid's radius plus `pad` (world units, so
    tiny asteroids stay clickable). If several overlap, the one whose center is closest wins."""
    best, best_d = None, None
    for a in asteroids:
        if a.get("spent", False):
            continue
        d = ((a["x"] - x) ** 2 + (a["y"] - y) ** 2) ** 0.5
        if d <= a["r"] + pad and (best_d is None or d < best_d):
            best, best_d = a["id"], d
    return best


class MarkStore:
    """Read and write one marks file."""

    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.path = path
        self.con = sqlite3.connect(path)
        self.con.executescript(SCHEMA)

    def save_frame(self, demo_file, episode_id, tick, all_ids, relevant_ids, marker):
        """Save one frame: every id in `all_ids` gets a row, relevant = (id in relevant_ids).
        Replaces anything saved for this frame before. Returns the number of rows written."""
        relevant_ids = set(relevant_ids)
        unknown = relevant_ids - set(all_ids)
        if unknown:
            raise ValueError(f"relevant ids {sorted(unknown)} are not in the frame")
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        rows = [(demo_file, episode_id, tick, int(i), int(i in relevant_ids), marker, now)
                for i in all_ids]
        with self.con:                      # one transaction: old rows out, new rows in
            self._delete(demo_file, episode_id, tick)
            self.con.executemany(
                "INSERT INTO marks (" + ", ".join(MARK_COLUMNS) + ") VALUES ("
                + ",".join("?" * len(MARK_COLUMNS)) + ")", rows)
        return len(rows)

    def delete_frame(self, demo_file, episode_id, tick):
        with self.con:
            self._delete(demo_file, episode_id, tick)

    def _delete(self, demo_file, episode_id, tick):
        self.con.execute("DELETE FROM marks WHERE demo_file=? AND episode_id=? AND tick=?",
                         (demo_file, episode_id, tick))

    def load_frame(self, demo_file, episode_id, tick):
        """{asteroid_id: relevant} for a saved frame, or None if it was never saved."""
        rows = self.con.execute(
            "SELECT asteroid_id, relevant FROM marks WHERE demo_file=? AND episode_id=? AND tick=?",
            (demo_file, episode_id, tick)).fetchall()
        return {i: r for i, r in rows} if rows else None

    def marked_ticks(self, demo_file, episode_id):
        """Sorted list of the ticks of this episode that have been saved."""
        rows = self.con.execute(
            "SELECT DISTINCT tick FROM marks WHERE demo_file=? AND episode_id=? ORDER BY tick",
            (demo_file, episode_id)).fetchall()
        return [r[0] for r in rows]

    def count_frames(self):
        """Number of saved frames in this file (all episodes)."""
        return self.con.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT demo_file, episode_id, tick FROM marks)").fetchone()[0]

    def close(self):
        self.con.close()


def load_marks(path):
    """Every row of a marks file as a list of dicts (keys = MARK_COLUMNS)."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM marks ORDER BY demo_file, episode_id, tick, asteroid_id")]
    con.close()
    return rows
