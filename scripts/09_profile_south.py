import sqlite3
import sys
from pathlib import Path


def open_ro(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


GAP = "CAST(ROUND((julianday({c}) - julianday(p)) * 1440) AS INTEGER)"

QUERIES = [
    ("assets", "SELECT * FROM assets ORDER BY asset_code"),

    ("tbl_mc_status: sample rows",
     "SELECT * FROM tbl_mc_status ORDER BY asset_code, stamp LIMIT 8"),

    ("tbl_mc_status: stamp formats and range",
     "SELECT length(stamp) AS len, substr(stamp, 11, 1) AS sep, COUNT(*) AS n, MIN(stamp) AS first, MAX(stamp) AS last, "
     "SUM(stamp LIKE '%Z' OR stamp LIKE '%+%') AS has_tz_marker FROM tbl_mc_status GROUP BY 1, 2"),

    ("tbl_mc_status: per asset",
     "SELECT asset_code, COUNT(*) AS n, COUNT(DISTINCT stamp) AS distinct_stamps, MIN(stamp) AS first, MAX(stamp) AS last "
     "FROM tbl_mc_status GROUP BY asset_code ORDER BY asset_code"),

    ("tbl_mc_status: asset_code not in assets",
     "SELECT COUNT(*) AS orphan_rows FROM tbl_mc_status WHERE asset_code NOT IN (SELECT asset_code FROM assets)"),

    ("tbl_mc_status: run_flag raw values",
     "SELECT quote(run_flag) AS run_flag_raw, COUNT(*) AS n FROM tbl_mc_status GROUP BY run_flag ORDER BY n DESC"),

    ("tbl_mc_status: cadence (minutes between consecutive stamps)",
     "WITH o AS (SELECT asset_code, stamp, LAG(stamp) OVER (PARTITION BY asset_code ORDER BY stamp) AS p FROM tbl_mc_status) "
     "SELECT " + GAP.format(c="stamp") + " AS gap_min, COUNT(*) AS n FROM o WHERE p IS NOT NULL GROUP BY 1 ORDER BY 1"),

    ("tbl_mc_status: duplicates on (asset_code, stamp)",
     "SELECT n_rows, n_variants, COUNT(*) AS keys FROM (SELECT asset_code, stamp, COUNT(*) AS n_rows, "
     "COUNT(DISTINCT quote(run_flag) || '|' || quote(qty_ok) || '|' || quote(qty_ng)) AS n_variants "
     "FROM tbl_mc_status GROUP BY 1, 2 HAVING COUNT(*) > 1) GROUP BY 1, 2 ORDER BY 1, 2"),

    ("tbl_mc_status: qty by run_flag",
     "SELECT quote(run_flag) AS run_flag_raw, COUNT(*) AS n, MIN(qty_ok) AS min_ok, MAX(qty_ok) AS max_ok, ROUND(AVG(qty_ok), 2) AS avg_ok, "
     "SUM(qty_ok IS NULL) AS null_ok, MIN(qty_ng) AS min_ng, MAX(qty_ng) AS max_ng, SUM(qty_ng IS NULL) AS null_ng "
     "FROM tbl_mc_status GROUP BY run_flag"),

    ("tbl_mc_status: qty_ok per-interval or cumulative? (vs previous row)",
     "WITH o AS (SELECT qty_ok, LAG(qty_ok) OVER (PARTITION BY asset_code ORDER BY stamp) AS p FROM tbl_mc_status) "
     "SELECT COUNT(*) AS pairs, SUM(qty_ok > p) AS increases, SUM(qty_ok < p) AS decreases, SUM(qty_ok = p) AS equal FROM o WHERE p IS NOT NULL"),

    ("tbl_downtime: sample rows",
     "SELECT rowid, * FROM tbl_downtime ORDER BY asset_code, dt_from LIMIT 8"),

    ("tbl_downtime: formats and range",
     "SELECT length(dt_from) AS l_from, length(dt_to) AS l_to, COUNT(*) AS n, MIN(dt_from) AS first_from, MAX(dt_to) AS last_to "
     "FROM tbl_downtime GROUP BY 1, 2"),

    ("tbl_downtime: is_void values",
     "SELECT quote(is_void) AS is_void_raw, COUNT(*) AS n FROM tbl_downtime GROUP BY is_void"),

    ("tbl_downtime: interval quality",
     "SELECT COUNT(*) AS n, SUM(dt_from IS NULL) AS null_from, SUM(dt_to IS NULL) AS null_to, SUM(dt_to < dt_from) AS to_before_from, "
     "SUM(dt_to = dt_from) AS zero_length, ROUND(MIN((julianday(dt_to) - julianday(dt_from)) * 1440), 1) AS min_minutes, "
     "ROUND(MAX((julianday(dt_to) - julianday(dt_from)) * 1440), 1) AS max_minutes FROM tbl_downtime"),

    ("tbl_downtime: cause_txt spellings (raw)",
     "SELECT quote(cause_txt) AS cause_raw, COUNT(*) AS n, SUM(is_void = 0) AS non_void FROM tbl_downtime GROUP BY cause_txt ORDER BY n DESC"),

    ("tbl_downtime: overlapping intervals, same asset (any rows)",
     "SELECT COUNT(*) AS overlapping_pairs FROM tbl_downtime a JOIN tbl_downtime b ON a.asset_code = b.asset_code AND a.rowid < b.rowid "
     "AND a.dt_from < b.dt_to AND b.dt_from < a.dt_to"),

    ("tbl_downtime: overlapping intervals, both non-void",
     "SELECT COUNT(*) AS overlapping_pairs FROM tbl_downtime a JOIN tbl_downtime b ON a.asset_code = b.asset_code AND a.rowid < b.rowid "
     "AND a.is_void = 0 AND b.is_void = 0 AND a.dt_from < b.dt_to AND b.dt_from < a.dt_to"),

    ("tbl_downtime: exact duplicate rows",
     "SELECT COUNT(*) AS duplicate_groups FROM (SELECT 1 FROM tbl_downtime GROUP BY asset_code, dt_from, dt_to, cause_txt, is_void HAVING COUNT(*) > 1)"),

    ("downtime vs status: status run_flag inside downtime intervals, by is_void",
     "SELECT d.is_void, quote(s.run_flag) AS run_flag_raw, COUNT(*) AS status_rows FROM tbl_downtime d "
     "JOIN tbl_mc_status s ON s.asset_code = d.asset_code AND s.stamp >= d.dt_from AND s.stamp < d.dt_to "
     "GROUP BY 1, 2 ORDER BY 1, 2"),

    ("tbl_em: sample rows",
     "SELECT * FROM tbl_em ORDER BY asset_code, slot_end LIMIT 6"),

    ("tbl_em: formats and range",
     "SELECT length(slot_end) AS len, COUNT(*) AS n, MIN(slot_end) AS first, MAX(slot_end) AS last, "
     "SUM(kwh_cum IS NULL) AS null_kwh FROM tbl_em GROUP BY 1"),

    ("tbl_em: per asset",
     "SELECT asset_code, COUNT(*) AS n, COUNT(DISTINCT slot_end) AS distinct_slots, MIN(slot_end) AS first, MAX(slot_end) AS last, "
     "MIN(kwh_cum) AS min_kwh_cum, MAX(kwh_cum) AS max_kwh_cum FROM tbl_em GROUP BY asset_code ORDER BY asset_code"),

    ("tbl_em: cadence (minutes between consecutive slots)",
     "WITH o AS (SELECT asset_code, slot_end, LAG(slot_end) OVER (PARTITION BY asset_code ORDER BY slot_end) AS p FROM tbl_em) "
     "SELECT " + GAP.format(c="slot_end") + " AS gap_min, COUNT(*) AS n FROM o WHERE p IS NOT NULL GROUP BY 1 ORDER BY 1"),

    ("tbl_em: register steps (vs previous slot)",
     "WITH o AS (SELECT asset_code, slot_end, kwh_cum, LAG(kwh_cum) OVER (PARTITION BY asset_code ORDER BY slot_end) AS p FROM tbl_em) "
     "SELECT CASE WHEN kwh_cum < p THEN 'decrease (reset?)' WHEN kwh_cum = p THEN 'flat' ELSE 'increase' END AS step, COUNT(*) AS n, "
     "ROUND(MIN(kwh_cum - p), 3) AS min_step, ROUND(MAX(kwh_cum - p), 3) AS max_step FROM o WHERE p IS NOT NULL GROUP BY 1"),

    ("tbl_em: duplicates on (asset_code, slot_end)",
     "SELECT n_rows, n_variants, COUNT(*) AS keys FROM (SELECT asset_code, slot_end, COUNT(*) AS n_rows, COUNT(DISTINCT quote(kwh_cum)) AS n_variants "
     "FROM tbl_em GROUP BY 1, 2 HAVING COUNT(*) > 1) GROUP BY 1, 2 ORDER BY 1, 2"),

    ("time coverage of the three sources",
     "SELECT 'tbl_mc_status' AS source, MIN(stamp) AS first, MAX(stamp) AS last FROM tbl_mc_status "
     "UNION ALL SELECT 'tbl_downtime', MIN(dt_from), MAX(dt_to) FROM tbl_downtime "
     "UNION ALL SELECT 'tbl_em', MIN(slot_end), MAX(slot_end) FROM tbl_em"),
]


def main(db_path):
    con = open_ro(db_path)
    cur = con.cursor()
    for title, sql in QUERIES:
        print(f"\n--- {title} ---")
        cur.execute(sql)
        print(" | ".join(c[0] for c in cur.description))
        for row in cur.fetchall():
            print(" | ".join(str(v) for v in row))
    con.close()


if __name__ == "__main__":
    main(sys.argv[1])
