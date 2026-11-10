"""
Export the demo database to CSV files (for Excel / quick looks).

    python export_csv.py --player levi   # writes data/export/demos_levi/episodes.csv, steps.csv
    python export_csv.py --db data/demos.sqlite

steps.csv has the asteroid list as a JSON string in the asteroids column (decoded from the
compressed recording format, so it's readable).
"""

import argparse
import csv
import json
import os
import sqlite3

import config
from game.recorder import load_episode, resolve_demo_db


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", help="export this player's file, data/demos_<player>.sqlite")
    ap.add_argument("--db", help="database file (overrides --player)")
    ap.add_argument("--out", help="output folder (default: data/export/<file name>)")
    args = ap.parse_args(argv)
    args.db = resolve_demo_db(args.db, args.player)
    if not os.path.exists(args.db):
        print("No such database:", args.db)
        return 1
    if not args.out:
        name = os.path.splitext(os.path.basename(args.db))[0]
        args.out = os.path.join(config.DATA_DIR, "export", name)
    os.makedirs(args.out, exist_ok=True)
    con = sqlite3.connect(args.db)
    cur = con.execute("SELECT * FROM episodes")
    path = os.path.join(args.out, "episodes.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([d[0] for d in cur.description])
        w.writerows(cur)
    print("wrote", path)
    episode_ids = [r[0] for r in con.execute("SELECT id FROM episodes ORDER BY id")]
    con.close()

    path = os.path.join(args.out, "steps.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        header = None
        for eid in episode_ids:
            _, steps = load_episode(args.db, eid)
            for st in steps:
                if header is None:
                    header = [k for k in st if k != "asteroids"] + ["asteroids"]
                    w.writerow(header)
                w.writerow([st[k] for k in header[:-1]]
                           + [json.dumps(st["asteroids"], separators=(",", ":"))])
    print("wrote", path)


if __name__ == "__main__":
    main()
