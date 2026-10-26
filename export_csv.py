"""
Export the demo database to CSV files (for Excel / quick looks).

    python export_csv.py                 # writes data/export/episodes.csv and steps.csv

steps.csv keeps the asteroid list as a JSON string in the asteroids_json column.
"""

import argparse
import csv
import os
import sqlite3

import config


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(config.DB_PATH), "export"))
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    con = sqlite3.connect(args.db)
    for table in ("episodes", "steps"):
        cur = con.execute(f"SELECT * FROM {table}")
        path = os.path.join(args.out, f"{table}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([d[0] for d in cur.description])
            w.writerows(cur)
        print("wrote", path)
    con.close()


if __name__ == "__main__":
    main()
