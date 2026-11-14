import sqlite3
import sys
from pathlib import Path


def open_ro(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


REJ_H = ("datetime(CASE WHEN length(hour_start) > 8 THEN hour_start "
         "ELSE reject_date || ' ' || hour_start END)")

REJ_BASE = "WITH b AS (SELECT *, " + REJ_H + " AS h FROM rejections) "

REJ_LIVE_DEDUP = (
    "WITH l AS (SELECT DISTINCT company_id, machine_id, reject_date, hour_start, qty, "
    "COALESCE(defect,'') AS defect, created_at, " + REJ_H + " AS h "
    "FROM rejections WHERE deleted_at = LIVE_TS) "
)

QUERIES = [
    ("rejections: sample rows",
     "SELECT * FROM rejections ORDER BY id LIMIT 6"),

    ("rejections: live vs deleted per company",
     "SELECT company_id, (deleted_at = LIVE_TS) AS is_live, COUNT(*) AS n FROM rejections GROUP BY 1, 2 ORDER BY 1, 2"),

    ("rejections: text formats and ranges",
     "SELECT length(reject_date) AS l_date, length(hour_start) AS l_hour, length(created_at) AS l_created, length(deleted_at) AS l_deleted, "
     "COUNT(*) AS n, MIN(reject_date) AS min_date, MAX(reject_date) AS max_date, MIN(hour_start) AS min_hour, MAX(hour_start) AS max_hour, "
     "MIN(created_at) AS min_created, MAX(created_at) AS max_created FROM rejections GROUP BY 1, 2, 3, 4"),

    ("rejections: defect spellings (raw)",
     "SELECT quote(defect) AS defect_raw, COUNT(*) AS n, SUM(deleted_at = LIVE_TS) AS live, SUM(qty) AS total_qty "
     "FROM rejections GROUP BY defect ORDER BY n DESC"),

    ("rejections: qty sanity",
     "SELECT COUNT(*) AS n, MIN(qty) AS min_q, MAX(qty) AS max_q, SUM(qty IS NULL) AS null_q, SUM(qty <= 0) AS nonpos_q FROM rejections"),

    ("rejections: orphan machines / company mismatch",
     "SELECT SUM(m.machine_id IS NULL) AS orphan_machine, SUM(m.machine_id IS NOT NULL AND r.company_id <> m.company_id) AS company_mismatch "
     "FROM rejections r LEFT JOIN machines m ON m.machine_id = r.machine_id"),

    ("rejections: reject_date hypothesis by hour (impossible = created before the hour it describes)",
     REJ_BASE + "SELECT substr(time(h), 1, 2) AS hh, COUNT(*) AS n, SUM(reject_date <> date(h)) AS date_col_differs_from_h, "
     "SUM(created_at < h) AS cal_created_before_start, "
     "SUM(CASE WHEN time(h) < '08:00:00' THEN created_at < datetime(h, '+1 day') ELSE created_at < h END) AS plant_created_before_start "
     "FROM b GROUP BY hh ORDER BY hh"),

    ("rejections: duplicate patterns",
     "WITH k AS (SELECT company_id, machine_id, reject_date, hour_start, qty, COALESCE(defect,'') AS d, COUNT(*) AS n_rows, "
     "COUNT(DISTINCT created_at) AS n_created, SUM(deleted_at = LIVE_TS) AS n_live FROM rejections GROUP BY 1,2,3,4,5,6 HAVING COUNT(*) > 1) "
     "SELECT n_rows, n_created, n_live, COUNT(*) AS groups FROM k GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"),

    ("rejections: sample duplicate rows",
     "SELECT id, machine_id, reject_date, hour_start, qty, defect, created_at, deleted_at FROM rejections "
     "WHERE (company_id, machine_id, reject_date, hour_start, qty) IN "
     "(SELECT company_id, machine_id, reject_date, hour_start, qty FROM rejections GROUP BY 1,2,3,4,5 HAVING COUNT(*) > 1 LIMIT 4) "
     "ORDER BY machine_id, reject_date, hour_start, id"),

    ("rejections: live dedup groups with more than one row for same machine+date+hour+defect",
     REJ_LIVE_DEDUP + "SELECT COUNT(*) AS groups FROM (SELECT 1 FROM l GROUP BY company_id, machine_id, reject_date, hour_start, defect HAVING COUNT(*) > 1)"),

    ("Kalpa live rejections per reject_date: raw vs deduplicated (profiling view, not an answer)",
     "WITH raw AS (SELECT reject_date, COUNT(*) AS raw_rows, SUM(qty) AS raw_qty FROM rejections "
     "WHERE company_id = 1 AND deleted_at = LIVE_TS GROUP BY reject_date), "
     "dd AS (SELECT reject_date, COUNT(*) AS dedup_rows, SUM(qty) AS dedup_qty FROM "
     "(SELECT DISTINCT company_id, machine_id, reject_date, hour_start, qty, COALESCE(defect,'') AS defect, created_at "
     "FROM rejections WHERE company_id = 1 AND deleted_at = LIVE_TS) GROUP BY reject_date) "
     "SELECT raw.reject_date, raw_rows, raw_qty, dedup_rows, dedup_qty FROM raw JOIN dd USING (reject_date) ORDER BY 1"),

    ("Kalpa live dedup rejections around 2 Nov: before vs after 08:00 (profiling view)",
     REJ_LIVE_DEDUP + "SELECT reject_date, (time(h) < '08:00:00') AS before_0800, COUNT(*) AS n_rows, SUM(qty) AS qty FROM l "
     "WHERE company_id = 1 AND reject_date BETWEEN '2026-10-31' AND '2026-11-04' GROUP BY 1, 2 ORDER BY 1, 2"),

    ("data watermarks: latest timestamp per source per company",
     "SELECT 'machine_minutes.minute_start' AS source, company_id, MAX(minute_start) AS latest FROM machine_minutes GROUP BY company_id "
     "UNION ALL SELECT 'stop_reasons.created_at', company_id, MAX(created_at) FROM stop_reasons GROUP BY company_id "
     "UNION ALL SELECT 'stop_reasons.reason_date', company_id, MAX(reason_date) FROM stop_reasons GROUP BY company_id "
     "UNION ALL SELECT 'rejections.created_at', company_id, MAX(created_at) FROM rejections GROUP BY company_id "
     "UNION ALL SELECT 'energy_hourly.end_time', em.company_id, MAX(eh.end_time) FROM energy_hourly eh "
     "JOIN energy_meters em ON em.meter_id = eh.meter_id GROUP BY em.company_id "
     "UNION ALL SELECT 'plan.updated_at', company_id, MAX(updated_at) FROM plan GROUP BY company_id "
     "ORDER BY 2, 1"),

    ("q10 peek: Kalpa machines at Kalpa's latest minute (profiling view)",
     "WITH t AS (SELECT MAX(minute_start) AS now_min FROM machine_minutes WHERE company_id = 1) "
     "SELECT m.machine_id, m.name, t.now_min, mm.planned, mm.running FROM machines m CROSS JOIN t "
     "LEFT JOIN machine_minutes mm ON mm.machine_id = m.machine_id AND mm.minute_start = t.now_min "
     "WHERE m.company_id = 1 ORDER BY m.machine_id"),

    ("q10 peek: Kalpa running flags over the last 5 minutes (HH:MM=running)",
     "WITH t AS (SELECT MAX(minute_start) AS now_min FROM machine_minutes WHERE company_id = 1) "
     "SELECT machine_id, group_concat(substr(minute_start, 12, 5) || '=' || running, '  ') AS last_5 FROM "
     "(SELECT mm.machine_id, mm.minute_start, mm.running FROM machine_minutes mm, t "
     "WHERE mm.company_id = 1 AND mm.minute_start > datetime(t.now_min, '-5 minutes') ORDER BY mm.machine_id, mm.minute_start) "
     "GROUP BY machine_id ORDER BY machine_id"),

    ("Kalpa: operator-entered minutes vs planned-and-not-running minutes per machine-hour",
     "WITH live AS (SELECT DISTINCT machine_id, reason_date, hour_start, reason, minutes, COALESCE(remark,'') AS remark, "
     "COALESCE(entered_by,'') AS entered_by, created_at FROM stop_reasons WHERE company_id = 1 AND deleted_at = LIVE_TS), "
     "eh AS (SELECT machine_id, datetime(reason_date || ' ' || hour_start) AS h, SUM(minutes) AS entered, "
     "SUM(CASE WHEN reason = 'Data Issue' THEN minutes ELSE 0 END) AS di_minutes FROM live GROUP BY 1, 2), "
     "mm AS (SELECT machine_id, strftime('%Y-%m-%d %H:00:00', minute_start) AS h, "
     "SUM(planned = 1 AND running = 0) AS stopped_planned, COUNT(*) AS rows_present FROM machine_minutes GROUP BY 1, 2) "
     "SELECT CASE WHEN eh.di_minutes > 0 THEN 'hour has Data Issue entry' ELSE 'no Data Issue entry' END AS kind, "
     "COUNT(*) AS machine_hours, SUM(eh.entered = mm.stopped_planned) AS entered_equals_stopped, "
     "SUM(eh.entered < mm.stopped_planned) AS entered_less, SUM(eh.entered > mm.stopped_planned) AS entered_more, "
     "SUM(mm.rows_present IS NULL) AS no_minute_rows FROM eh LEFT JOIN mm USING (machine_id, h) GROUP BY 1 ORDER BY 1"),
]


def main(db_path):
    con = open_ro(db_path)
    cur = con.cursor()
    for title, sql in QUERIES:
        sql = sql.replace("LIVE_TS", "'0000-00-00 00:00:00'")
        print(f"\n--- {title} ---")
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        print(" | ".join(cols))
        for row in cur.fetchall():
            print(" | ".join(str(v) for v in row))
    con.close()


if __name__ == "__main__":
    main(sys.argv[1])
