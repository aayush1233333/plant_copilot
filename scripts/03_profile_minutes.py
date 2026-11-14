import sqlite3
import sys
from pathlib import Path


def open_ro(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


VARIANT = "quote(planned)||'|'||quote(running)||'|'||quote(pieces)||'|'||quote(shift)||'|'||quote(shift_date)||'|'||quote(company_id)"

DERIVED = """
WITH d AS (
  SELECT *,
    CASE WHEN CAST(strftime('%H', minute_start) AS INTEGER) BETWEEN 8 AND 19 THEN 'A' ELSE 'B' END AS derived_shift,
    date(minute_start, '-8 hours') AS derived_date
  FROM machine_minutes
)
"""

QUERIES = [
    ("duplicate keys (machine_id, minute_start)",
     "SELECT COUNT(*) AS dup_keys, COALESCE(SUM(n-1),0) AS extra_rows FROM "
     "(SELECT machine_id, minute_start, COUNT(*) AS n FROM machine_minutes GROUP BY machine_id, minute_start HAVING n > 1)"),

    ("duplicates: rows per key vs distinct variants (1 variant = exact dup, >1 = conflict)",
     "SELECT n_rows, n_variants, COUNT(*) AS keys FROM ("
     "SELECT machine_id, minute_start, COUNT(*) AS n_rows, COUNT(DISTINCT " + VARIANT + ") AS n_variants "
     "FROM machine_minutes GROUP BY machine_id, minute_start HAVING COUNT(*) > 1) "
     "GROUP BY n_rows, n_variants ORDER BY n_rows, n_variants"),

    ("duplicates: sample of conflicting keys",
     "SELECT mm.id, mm.company_id, mm.machine_id, mm.minute_start, mm.shift_date, mm.shift, mm.planned, mm.running, mm.pieces "
     "FROM machine_minutes mm JOIN ("
     "SELECT machine_id, minute_start FROM machine_minutes GROUP BY machine_id, minute_start "
     "HAVING COUNT(DISTINCT " + VARIANT + ") > 1 LIMIT 5) k "
     "ON k.machine_id = mm.machine_id AND k.minute_start = mm.minute_start "
     "ORDER BY mm.machine_id, mm.minute_start, mm.id"),

    ("per machine: span, rows, distinct minutes, expected, missing",
     "SELECT machine_id, MIN(minute_start) AS first_min, MAX(minute_start) AS last_min, COUNT(*) AS n_rows, "
     "COUNT(DISTINCT minute_start) AS distinct_min, "
     "CAST(ROUND((julianday(MAX(minute_start)) - julianday(MIN(minute_start))) * 1440) + 1 AS INTEGER) AS expected, "
     "CAST(ROUND((julianday(MAX(minute_start)) - julianday(MIN(minute_start))) * 1440) + 1 AS INTEGER) - COUNT(DISTINCT minute_start) AS missing "
     "FROM machine_minutes GROUP BY machine_id ORDER BY machine_id"),

    ("stored vs derived shift / shift_date: totals",
     DERIVED + "SELECT COUNT(*) AS total, SUM(shift <> derived_shift) AS shift_mismatch, "
     "SUM(shift_date <> derived_date) AS date_mismatch, SUM(shift_date IS NULL) AS null_shift_date FROM d"),

    ("stored vs derived: mismatches by hour",
     DERIVED + "SELECT strftime('%H', minute_start) AS hh, shift AS stored_shift, derived_shift, "
     "(shift_date = derived_date) AS date_ok, COUNT(*) AS n FROM d "
     "WHERE shift <> derived_shift OR shift_date <> derived_date GROUP BY 1, 2, 3, 4 ORDER BY 1"),

    ("pieces by planned/running",
     "SELECT planned, running, COUNT(*) AS n, MIN(pieces) AS min_p, MAX(pieces) AS max_p, ROUND(AVG(pieces), 2) AS avg_p, "
     "SUM(pieces IS NULL) AS null_p, SUM(pieces = 0) AS zero_p, SUM(pieces < 0) AS neg_p "
     "FROM machine_minutes GROUP BY planned, running ORDER BY planned, running"),

    ("pieces: cumulative or per-minute? (compare with previous row, same machine)",
     "WITH o AS (SELECT pieces, LAG(pieces) OVER (PARTITION BY machine_id ORDER BY minute_start, id) AS prev FROM machine_minutes) "
     "SELECT COUNT(*) AS pairs, SUM(pieces > prev) AS increases, SUM(pieces < prev) AS decreases, SUM(pieces = prev) AS equal "
     "FROM o WHERE prev IS NOT NULL"),
]


def main(db_path):
    con = open_ro(db_path)
    cur = con.cursor()
    for title, sql in QUERIES:
        print(f"\n--- {title} ---")
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        print(" | ".join(cols))
        for row in cur.fetchall():
            print(" | ".join(str(v) for v in row))
    con.close()


if __name__ == "__main__":
    main(sys.argv[1])
