import sqlite3
import sys
from pathlib import Path


def open_ro(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


LIVE = "'0000-00-00 00:00:00'"

BASE = """
WITH b AS (
  SELECT *,
    datetime(reason_date || ' ' || hour_start) AS hour_start_dt,
    datetime(reason_date || ' ' || hour_start, '+1 hour') AS hour_end_dt,
    CAST(strftime('%s', created_at) AS INTEGER)
      - CAST(strftime('%s', datetime(reason_date || ' ' || hour_start, '+1 hour')) AS INTEGER) AS secs_after_end
  FROM stop_reasons
)
"""

LIVE_DEDUP = (
    "WITH live AS (SELECT DISTINCT company_id, machine_id, reason_date, hour_start, reason, minutes, "
    "COALESCE(remark,'') AS remark, COALESCE(entered_by,'') AS entered_by, created_at "
    "FROM stop_reasons WHERE deleted_at = " + LIVE + ") "
)

GRP = "company_id, machine_id, reason_date, hour_start, reason, minutes, COALESCE(remark,''), COALESCE(entered_by,'')"

QUERIES = [
    ("reason_date hypothesis test by hour (impossible = entry created before the hour it describes)",
     BASE + "SELECT substr(hour_start,1,2) AS hh, COUNT(*) AS n, "
     "SUM(created_at < hour_start_dt) AS cal_created_before_start, "
     "SUM(created_at < hour_end_dt) AS cal_created_before_end, "
     "SUM(CASE WHEN substr(hour_start,1,2) < '08' THEN created_at < datetime(hour_start_dt, '+1 day') ELSE created_at < hour_start_dt END) AS plant_created_before_start, "
     "SUM(CASE WHEN substr(hour_start,1,2) < '08' THEN created_at < datetime(hour_end_dt, '+1 day') ELSE created_at < hour_end_dt END) AS plant_created_before_end "
     "FROM b GROUP BY hh ORDER BY hh"),

    ("lateness vs end of described hour (calendar-date reading)",
     BASE + "SELECT CASE WHEN secs_after_end < 0 THEN '1: before hour end' "
     "WHEN secs_after_end <= 21600 THEN '2: 0-6h' WHEN secs_after_end <= 86400 THEN '3: 6-24h (incl. exactly 24h)' "
     "WHEN secs_after_end <= 172800 THEN '4: 24-48h' WHEN secs_after_end <= 259200 THEN '5: 48-72h' ELSE '6: over 72h' END AS bucket, "
     "COUNT(*) AS n, SUM(deleted_at = " + LIVE + ") AS live, MIN(secs_after_end) AS min_secs, MAX(secs_after_end) AS max_secs "
     "FROM b GROUP BY 1 ORDER BY 1"),

    ("entries exactly 86400s after hour end",
     BASE + "SELECT COUNT(*) AS exactly_24h FROM b WHERE secs_after_end = 86400"),

    ("duplicate patterns on full key incl. reason_date",
     "WITH k AS (SELECT " + GRP + ", COUNT(*) AS n_rows, COUNT(DISTINCT created_at) AS n_created, "
     "SUM(deleted_at = " + LIVE + ") AS n_live, COUNT(DISTINCT deleted_at) AS n_deleted_vals "
     "FROM stop_reasons GROUP BY 1,2,3,4,5,6,7,8 HAVING COUNT(*) > 1) "
     "SELECT n_rows, n_created, n_live, n_deleted_vals, COUNT(*) AS groups FROM k GROUP BY 1,2,3,4 ORDER BY 1,2,3,4"),

    ("sample: duplicate groups whose created_at differs",
     "SELECT s.id, s.machine_id, s.reason_date, s.hour_start, s.minutes, s.reason, s.entered_by, s.created_at, s.deleted_at "
     "FROM stop_reasons s JOIN (SELECT company_id AS c, machine_id AS m, reason_date AS rd, hour_start AS hs, reason AS rs, minutes AS mi, "
     "COALESCE(remark,'') AS r, COALESCE(entered_by,'') AS e FROM stop_reasons GROUP BY 1,2,3,4,5,6,7,8 "
     "HAVING COUNT(*) > 1 AND COUNT(DISTINCT created_at) > 1 LIMIT 3) d "
     "ON s.company_id = d.c AND s.machine_id = d.m AND s.reason_date = d.rd AND s.hour_start = d.hs AND s.reason = d.rs "
     "AND s.minutes = d.mi AND COALESCE(s.remark,'') = d.r AND COALESCE(s.entered_by,'') = d.e "
     "ORDER BY s.machine_id, s.reason_date, s.hour_start, s.id"),

    ("sample: duplicate groups containing a deleted row",
     "SELECT s.id, s.machine_id, s.reason_date, s.hour_start, s.minutes, s.reason, s.entered_by, s.created_at, s.deleted_at "
     "FROM stop_reasons s JOIN (SELECT company_id AS c, machine_id AS m, reason_date AS rd, hour_start AS hs, reason AS rs, minutes AS mi, "
     "COALESCE(remark,'') AS r, COALESCE(entered_by,'') AS e FROM stop_reasons GROUP BY 1,2,3,4,5,6,7,8 "
     "HAVING COUNT(*) > 1 AND SUM(deleted_at <> " + LIVE + ") > 0 LIMIT 3) d "
     "ON s.company_id = d.c AND s.machine_id = d.m AND s.reason_date = d.rd AND s.hour_start = d.hs AND s.reason = d.rs "
     "AND s.minutes = d.mi AND COALESCE(s.remark,'') = d.r AND COALESCE(s.entered_by,'') = d.e "
     "ORDER BY s.machine_id, s.reason_date, s.hour_start, s.id"),

    ("live deduplicated entries per company",
     LIVE_DEDUP + "SELECT company_id, COUNT(*) AS entries, SUM(minutes) AS total_minutes, "
     "SUM(reason = 'Data Issue') AS data_issue_entries, SUM(CASE WHEN reason = 'Data Issue' THEN minutes ELSE 0 END) AS data_issue_minutes "
     "FROM live GROUP BY company_id"),

    ("live dedup: entries per machine-hour",
     LIVE_DEDUP + "SELECT n_entries, COUNT(*) AS machine_hours FROM (SELECT machine_id, reason_date, hour_start, COUNT(*) AS n_entries "
     "FROM live GROUP BY 1,2,3) GROUP BY n_entries ORDER BY n_entries"),

    ("live dedup: machine-hour total minutes",
     LIVE_DEDUP + "SELECT COUNT(*) AS machine_hours, SUM(tot > 60) AS over_60, MAX(tot) AS max_total FROM "
     "(SELECT machine_id, reason_date, hour_start, SUM(minutes) AS tot FROM live GROUP BY 1,2,3)"),

    ("live dedup: same machine+date+hour+reason but different minutes/created_at",
     LIVE_DEDUP + "SELECT COUNT(*) AS groups FROM (SELECT 1 FROM live GROUP BY company_id, machine_id, reason_date, hour_start, reason HAVING COUNT(*) > 1)"),
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
