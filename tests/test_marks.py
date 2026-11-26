"""Freeze-frame marking (task D5): the marks file and the marking logic in mark.py."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mark
from game import Action, AsteroidGame
from game.marks import (MarkStore, asteroid_at, find_marks_dbs, live_asteroid_ids,
                        load_marks, marks_db_path)
from game.recorder import Recorder, load_episode
from game.sim import GAME_VERSION


def rock(i, x, y, r=0.05, spent=False):
    return {"id": i, "x": x, "y": y, "vx": 0.0, "vy": 0.0, "ax": 0.0, "ay": 0.0,
            "r": r, "spent": spent}


# -- the marks file -------------------------------------------------------------------

def test_marks_db_path_and_find(tmp_path):
    d = str(tmp_path)
    assert marks_db_path("Adrian K.", d) == os.path.join(d, "marks_adrian_k.sqlite")
    for name in ("marks_levi.sqlite", "marks_adrian.sqlite", "demos_levi.sqlite"):
        (tmp_path / name).write_bytes(b"")
    assert [os.path.basename(p) for p in find_marks_dbs(d)] == \
        ["marks_adrian.sqlite", "marks_levi.sqlite"]


def test_save_stores_every_asteroid_with_0_or_1(tmp_path):
    path = str(tmp_path / "marks_a.sqlite")
    s = MarkStore(path)
    assert s.save_frame("demos_levi.sqlite", 3, 40, [1, 2, 5], {2}, "adrian") == 3
    assert s.load_frame("demos_levi.sqlite", 3, 40) == {1: 0, 2: 1, 5: 0}
    s.close()
    rows = load_marks(path)
    assert [(r["asteroid_id"], r["relevant"]) for r in rows] == [(1, 0), (2, 1), (5, 0)]
    assert all(r["demo_file"] == "demos_levi.sqlite" and r["episode_id"] == 3
               and r["tick"] == 40 and r["marker"] == "adrian" for r in rows)


def test_saving_again_replaces_the_frame(tmp_path):
    s = MarkStore(str(tmp_path / "m.sqlite"))
    s.save_frame("d.sqlite", 1, 10, [1, 2, 3], {1, 2}, "a")
    s.save_frame("d.sqlite", 1, 10, [1, 2], set(), "a")
    assert s.load_frame("d.sqlite", 1, 10) == {1: 0, 2: 0}
    assert s.count_frames() == 1


def test_frames_are_kept_apart_by_demo_file_episode_and_tick(tmp_path):
    s = MarkStore(str(tmp_path / "m.sqlite"))
    s.save_frame("demos_levi.sqlite", 1, 10, [1], {1}, "a")
    s.save_frame("demos_adrian.sqlite", 1, 10, [1], set(), "a")   # same episode id, other file
    s.save_frame("demos_levi.sqlite", 1, 11, [1], set(), "a")
    s.save_frame("demos_levi.sqlite", 2, 10, [1], set(), "a")
    assert s.load_frame("demos_levi.sqlite", 1, 10) == {1: 1}
    assert s.load_frame("demos_adrian.sqlite", 1, 10) == {1: 0}
    assert s.marked_ticks("demos_levi.sqlite", 1) == [10, 11]
    assert s.count_frames() == 4


def test_unsaved_frame_is_none_and_delete_works(tmp_path):
    s = MarkStore(str(tmp_path / "m.sqlite"))
    assert s.load_frame("d.sqlite", 1, 5) is None
    s.save_frame("d.sqlite", 1, 5, [1, 2], {1}, "a")
    s.delete_frame("d.sqlite", 1, 5)
    assert s.load_frame("d.sqlite", 1, 5) is None
    assert s.count_frames() == 0


def test_relevant_ids_must_be_in_the_frame(tmp_path):
    s = MarkStore(str(tmp_path / "m.sqlite"))
    with pytest.raises(ValueError):
        s.save_frame("d.sqlite", 1, 5, [1, 2], {7}, "a")
    assert s.load_frame("d.sqlite", 1, 5) is None


# -- clicking -------------------------------------------------------------------------

def test_asteroid_at():
    rocks = [rock(1, 0.5, 0.5), rock(2, 0.58, 0.5), rock(3, 1.0, 1.0, spent=True)]
    assert asteroid_at(rocks, 0.5, 0.5) == 1
    assert asteroid_at(rocks, 0.55, 0.5) == 2         # inside both: the closer center wins
    assert asteroid_at(rocks, 1.0, 1.0) is None       # spent asteroids can't be marked
    assert asteroid_at(rocks, 0.5, 0.56) is None      # just outside the radius ...
    assert asteroid_at(rocks, 0.5, 0.56, pad=0.02) == 1   # ... but within the click pad
    assert live_asteroid_ids(rocks) == [1, 2]


# -- the marking session (mark.py, no window) ---------------------------------------------

@pytest.fixture
def session(tmp_path):
    demo = str(tmp_path / "demos_levi.sqlite")
    rec = Recorder(demo)
    g = AsteroidGame(seed=7, difficulty="medium")
    eid = rec.start_episode(g, "levi", GAME_VERSION)
    for i in range(30):
        rec.log_step(g.get_state(), Action(0, i % 2 == 0))
        g.step(Action(0, i % 2 == 0))
    rec.log_step(g.get_state(), None)
    rec.end_episode(g)
    rec.close()
    ep, steps = load_episode(demo, eid)
    store = MarkStore(str(tmp_path / "marks_adrian.sqlite"))
    yield mark.MarkSession(store, "demos_levi.sqlite", ep, steps, "adrian")
    store.close()


def test_click_save_and_reload(session):
    session.go_to(5)
    a = next(x for x in session.step["asteroids"] if not x["spent"])
    assert session.click(a["x"], a["y"]) == a["id"]
    assert session.selected == {a["id"]} and session.dirty
    assert session.save()
    assert not session.dirty
    saved = session.store.load_frame("demos_levi.sqlite", session.ep["id"], session.tick)
    assert set(saved) == set(session.live_ids())       # every live asteroid has a row
    assert {i for i, r in saved.items() if r} == {a["id"]}
    session.go_to(6)
    assert session.selected == set()
    session.go_to(5)                                    # coming back shows the saved clicks
    assert session.selected == {a["id"]}
    assert session.marked_ticks() == [session.tick]


def test_clicking_twice_unmarks(session):
    a = next(x for x in session.step["asteroids"] if not x["spent"])
    session.click(a["x"], a["y"])
    session.click(a["x"], a["y"])
    assert session.selected == set() and not session.dirty


def test_unsaved_clicks_are_dropped_when_moving(session):
    a = next(x for x in session.step["asteroids"] if not x["spent"])
    session.click(a["x"], a["y"])
    session.go_to(1)
    assert "dropped" in session.status
    session.go_to(0)
    assert session.selected == set()
    assert session.marked_ticks() == []


def test_frame_with_no_clicks_can_be_saved_as_all_irrelevant(session):
    assert session.save()
    saved = session.store.load_frame("demos_levi.sqlite", session.ep["id"], session.tick)
    assert saved and set(saved.values()) == {0}


def test_final_frame_cannot_be_marked(session):
    session.go_to(10 ** 6)                              # clamps to the last step
    assert session.i == session.last
    assert not session.save()
    assert session.marked_ticks() == []


def test_delete_removes_saved_frame(session):
    session.save()
    session.delete()
    assert session.saved is None
    assert session.marked_ticks() == []


def test_mark_main_missing_file(tmp_path):
    assert mark.main(["--marker", "a", "--db", str(tmp_path / "nope.sqlite")]) == 1
    assert not (tmp_path / "nope.sqlite").exists()
