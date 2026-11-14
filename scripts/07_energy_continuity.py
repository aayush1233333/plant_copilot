import sqlite3
import sys
from pathlib import Path


def open_ro(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


PAIRS = """
WITH o AS (
  SELECT meter_id, start_time, end_time, counter_start, counter_end, kwh,
    LAG(end_time) OVER (PARTITION BY meter_id ORDER BY start_time) AS p_end,
    LAG(counter_end) OVER (PARTITION BY meter_id ORDER BY start_time) AS p_ce
  FROM energy_hourly
),
p AS (
  SELECT *,
    CAST(strftime('%s', start_time) AS INTEGER) - CAST(strftime('%s', p_end) AS INTEGER) AS gap_secs,
    ROUND(counter_start - p_ce, 3) AS reg_jump
  FROM o WHERE p_end IS NOT NULL
)
"""

QUERIES = [
    ("consecutive pairs: time link vs register link (all meters)",
     PAIRS + "SELECT CASE WHEN gap_secs = 1 THEN 'consecutive slots' ELSE 'missing slot(s) between' END AS time_link, "
     "CASE WHEN ABS(reg_jump) < 0.0005 THEN 'register continuous' WHEN reg_jump > 0 THEN 'register advanced' "
     "ELSE 'register went BACK' END AS reg_link, COUNT(*) AS n_pairs, MIN(reg_jump) AS min_jump, MAX(reg_jump) AS max_jump "
     "FROM p GROUP BY 1, 2 ORDER BY 1, 2"),

    ("gap sizes: seconds beyond the normal 1s link, and slots missing",
     PAIRS + "SELECT gap_secs - 1 AS extra_secs, ROUND((gap_secs - 1) / 3600.0, 2) AS missing_slots, COUNT(*) AS n_pairs "
     "FROM p WHERE gap_secs <> 1 GROUP BY gap_secs ORDER BY gap_secs"),

    ("per meter: register delta range and kwh/delta ratio",
     "SELECT meter_id, COUNT(*) AS n, ROUND(MIN(counter_end - counter_start), 2) AS min_delta, "
     "ROUND(MAX(counter_end - counter_start), 2) AS max_delta, "
     "ROUND(MIN(kwh / (counter_end - counter_start)), 4) AS min_ratio, "
     "ROUND(MAX(kwh / (counter_end - counter_start)), 4) AS max_ratio, "
     "ROUND(AVG(kwh / (counter_end - counter_start)), 4) AS avg_ratio "
     "FROM energy_hourly WHERE counter_end > counter_start GROUP BY meter_id ORDER BY meter_id"),

    ("stored report_date/shift vs derived from start_time",
     "WITH d AS (SELECT *, date(datetime(start_time, '-7 hours', '-30 minutes')) AS d_date, "
     "CASE WHEN time(start_time) >= '07:30:01' AND time(start_time) < '19:30:01' THEN 'A' ELSE 'B' END AS d_shift "
     "FROM energy_hourly) "
     "SELECT COUNT(*) AS total, SUM(report_date <> d_date) AS date_mismatch, SUM(shift <> d_shift) AS shift_mismatch FROM d"),

    ("every gap in Kalpa meters (profiling view; company_id = 1 hard-coded here only)",
     PAIRS + "SELECT p.meter_id, p.p_end AS prev_slot_end, p.start_time AS next_slot_start, "
     "ROUND((p.gap_secs - 1) / 3600.0, 2) AS missing_slots, p.p_ce AS counter_before, p.counter_start AS counter_after, p.reg_jump "
     "FROM p JOIN energy_meters em ON em.meter_id = p.meter_id "
     "WHERE p.gap_secs > 1 AND em.company_id = 1 ORDER BY p.meter_id, p.start_time"),

    ("q3/q4 profiling view: slots labelled shift A on the question days (NOT an answer)",
     "SELECT meter_id, report_date, shift, COUNT(*) AS rows_present, MIN(start_time) AS first_start, MAX(end_time) AS last_end, "
     "MIN(counter_start) AS min_counter_start, MAX(counter_end) AS max_counter_end, "
     "ROUND(MAX(counter_end) - MIN(counter_start), 2) AS register_span, ROUND(SUM(kwh), 2) AS sum_kwh_column "
     "FROM energy_hourly WHERE (meter_id = 501 AND report_date = '2026-11-04' AND shift = 'A') "
     "OR (meter_id = 502 AND report_date = '2026-11-05' AND shift = 'A') GROUP BY meter_id, report_date, shift"),
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
