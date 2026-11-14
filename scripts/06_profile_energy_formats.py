import sqlite3
import sys
from pathlib import Path


def open_ro(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


COLS = "id, meter_id, report_date, shift, start_time, end_time, kwh, counter_start, counter_end, pf"


def day_rows(meter_id, day):
    return ("SELECT " + COLS + " FROM energy_hourly WHERE meter_id = " + str(meter_id)
            + " AND (report_date LIKE '" + day + "%' OR start_time LIKE '" + day + "%') ORDER BY start_time, id")


QUERIES = [
    ("energy_hourly: sample rows",
     "SELECT " + COLS + " FROM energy_hourly ORDER BY id LIMIT 6"),

    ("energy_hourly: text formats and ranges",
     "SELECT length(report_date) AS l_date, length(start_time) AS l_start, length(end_time) AS l_end, COUNT(*) AS n, "
     "MIN(report_date) AS min_date, MAX(report_date) AS max_date, MIN(start_time) AS min_start, MAX(start_time) AS max_start, "
     "MIN(end_time) AS min_end, MAX(end_time) AS max_end FROM energy_hourly GROUP BY 1, 2, 3"),

    ("energy_hourly: shift values",
     "SELECT quote(shift) AS shift_raw, COUNT(*) AS n FROM energy_hourly GROUP BY shift ORDER BY shift"),

    ("energy_hourly: per meter (rows, distinct start_time, span)",
     "SELECT eh.meter_id, em.meter_name, em.company_id, COUNT(*) AS n_rows, COUNT(DISTINCT eh.start_time) AS distinct_start, "
     "MIN(eh.start_time) AS first_start, MAX(eh.end_time) AS last_end FROM energy_hourly eh "
     "LEFT JOIN energy_meters em ON em.meter_id = eh.meter_id GROUP BY 1, 2, 3 ORDER BY 1"),

    ("energy_hourly: meters not in energy_meters (orphans)",
     "SELECT COUNT(*) AS orphan_rows FROM energy_hourly WHERE meter_id NOT IN (SELECT meter_id FROM energy_meters)"),

    ("energy_meters vs machines: company mismatch",
     "SELECT COUNT(*) AS company_mismatch FROM energy_meters em JOIN machines m ON m.machine_id = em.machine_id WHERE em.company_id <> m.company_id"),

    ("cadence: last 5 characters (MM:SS) of start_time and end_time",
     "SELECT substr(start_time, -5) AS start_tail, substr(end_time, -5) AS end_tail, COUNT(*) AS n FROM energy_hourly "
     "GROUP BY 1, 2 ORDER BY n DESC LIMIT 15"),

    ("nulls, negatives, resets, ranges",
     "SELECT COUNT(*) AS n, SUM(kwh IS NULL) AS null_kwh, SUM(counter_start IS NULL) AS null_cs, SUM(counter_end IS NULL) AS null_ce, "
     "SUM(kwh < 0) AS neg_kwh, SUM(kwh = 0) AS zero_kwh, SUM(counter_end < counter_start) AS counter_goes_back, "
     "MIN(kwh) AS min_kwh, MAX(kwh) AS max_kwh, MIN(pf) AS min_pf, MAX(pf) AS max_pf FROM energy_hourly"),

    ("kwh vs (counter_end - counter_start)",
     "WITH d AS (SELECT kwh, counter_end - counter_start AS delta FROM energy_hourly "
     "WHERE kwh IS NOT NULL AND counter_start IS NOT NULL AND counter_end IS NOT NULL) "
     "SELECT CASE WHEN ABS(kwh - delta) <= 0.001 THEN '1: agree (<=0.001)' WHEN ABS(kwh - delta) <= 0.05 THEN '2: <=0.05' "
     "WHEN ABS(kwh - delta) <= 0.5 THEN '3: <=0.5' ELSE '4: more than 0.5' END AS bucket, "
     "COUNT(*) AS n, MIN(kwh - delta) AS min_diff, MAX(kwh - delta) AS max_diff FROM d GROUP BY 1 ORDER BY 1"),

    ("duplicates on (meter_id, start_time): rows vs distinct variants",
     "SELECT n_rows, n_variants, COUNT(*) AS keys FROM (SELECT meter_id, start_time, COUNT(*) AS n_rows, "
     "COUNT(DISTINCT quote(kwh) || '|' || quote(counter_start) || '|' || quote(counter_end) || '|' || quote(end_time)) AS n_variants "
     "FROM energy_hourly GROUP BY 1, 2 HAVING COUNT(*) > 1) GROUP BY 1, 2 ORDER BY 1, 2"),

    ("meter 501 (Press 2): rows touching 4 Nov", day_rows(501, "2026-11-04")),

    ("meter 502 (Press 3): rows touching 5 Nov", day_rows(502, "2026-11-05")),
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
