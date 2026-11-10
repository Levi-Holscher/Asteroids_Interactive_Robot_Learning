"""Per-person demo files (task D1): each player records into data/demos_<player>.sqlite."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import replay
from game.recorder import demo_db_path, find_demo_dbs, player_slug, resolve_demo_db


def test_player_slug():
    assert player_slug("levi") == "levi"
    assert player_slug("  Levi H. ") == "levi_h"
    assert player_slug("Muktaka Joshipura") == "muktaka_joshipura"
    assert player_slug("") == "anonymous"
    assert player_slug(None) == "anonymous"
    assert player_slug("../../etc") == "etc"            # can't escape the data folder


def test_demo_db_path(tmp_path):
    assert demo_db_path("Levi", str(tmp_path)) == os.path.join(str(tmp_path), "demos_levi.sqlite")


def test_find_demo_dbs_skips_other_games_and_old_shared_file(tmp_path):
    for name in ("demos_levi.sqlite", "demos_bot.sqlite", "demos.sqlite",
                 "dodge_demos.sqlite", "grid_demos.sqlite", "marks_levi.sqlite"):
        (tmp_path / name).write_bytes(b"")
    found = [os.path.basename(p) for p in find_demo_dbs(str(tmp_path))]
    assert found == ["demos_bot.sqlite", "demos_levi.sqlite"]


def test_resolve_demo_db_order(tmp_path):
    d = str(tmp_path)
    assert resolve_demo_db("x.sqlite", "levi", d) == "x.sqlite"            # explicit path wins
    assert resolve_demo_db(None, "Levi", d) == demo_db_path("levi", d)    # then the player
    old = tmp_path / "demos_adrian.sqlite"
    new = tmp_path / "demos_levi.sqlite"
    old.write_bytes(b"")
    new.write_bytes(b"")
    os.utime(old, (time.time() - 100, time.time() - 100))
    assert resolve_demo_db(None, None, d) == str(new)                     # then the newest


def test_replay_missing_file_does_not_create_it(tmp_path):
    db = tmp_path / "demos_nobody.sqlite"
    assert replay.main(["--db", str(db), "--list"]) == 1
    assert not db.exists()
