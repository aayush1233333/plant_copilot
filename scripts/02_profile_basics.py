import sqlite3
import sys
from pathlib import Path


def open_ro(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


QUERIES = [
    ("companies", "SELECT * FROM companies"),
    ("machines", "SELECT machine_id, company_id, plant, name, shop FROM machines ORDER BY company_id, machine_id"),
    ("machine name collisions", "SELECT name, COUNT(*) AS n, COUNT(DISTINCT company_id) AS n_companies FROM machines GROUP BY name HAVING COUNT(*) > 1"),
    ("energy_meters", "SELECT * FROM energy_meters ORDER BY company_id, meter_id"),
    ("machine_minutes: per company", "SELECT company_id, COUNT(*) AS n_rows, COUNT(DISTINCT machine_id) AS n_machines, MIN(minute_start) AS first_min, MAX(minute_start) AS last_min FROM machine_minutes GROUP BY company_id"),
    ("machine_minutes: sample rows", "SELECT * FROM machine_minutes ORDER BY id LIMIT 5"),
    ("machine_minutes: minute_start string lengths", "SELECT length(minute_start) AS len, COUNT(*) AS n, MIN(minute_start) AS example FROM machine_minutes GROUP BY len"),
    ("machine_minutes: shift/planned/running values", "SELECT shift, planned, running, COUNT(*) AS n FROM machine_minutes GROUP BY shift, planned, running ORDER BY shift, planned, running"),
    ("machine_minutes: company_id disagrees with machines table", "SELECT COUNT(*) AS mismatched_rows FROM machine_minutes mm JOIN machines m ON m.machine_id = mm.machine_id WHERE mm.company_id <> m.company_id"),
]


def main(db_path):
    con = open_ro(db_path)
    cur = con.cursor()
    for title, sql in QUERIES:
        print(f"\n--- {title} ---")
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        print(" | ".join(cols))
        for row in cur.fetchall():
            print(" | ".join(str(v) for v in row))
    con.close()


if __name__ == "__main__":
    main(sys.argv[1])
