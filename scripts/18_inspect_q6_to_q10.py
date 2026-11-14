import sqlite3
from pathlib import Path

DB = Path("data/factory.db").resolve().as_uri() + "?mode=ro"
con = sqlite3.connect(DB, uri=True)
con.row_factory = sqlite3.Row

print("=== Q6: Top stop reason by minutes (1-7 Nov) ===")
sql_q6 = """
WITH live AS (
    SELECT DISTINCT company_id, machine_id, reason_date, hour_start, reason, minutes,
           COALESCE(remark, '') AS remark, COALESCE(entered_by, '') AS entered_by, created_at
    FROM stop_reasons
    WHERE company_id = 1 AND deleted_at = '0000-00-00 00:00:00'
      AND reason_date BETWEEN '2026-11-01' AND '2026-11-07'
)
SELECT reason, COUNT(*) AS n_entries, SUM(minutes) AS total_minutes
FROM live
GROUP BY reason
ORDER BY total_minutes DESC;
"""
for r in con.execute(sql_q6):
    print(f"  {r['reason']:25} | {r['total_minutes']:4} min | {r['n_entries']} entries")

print("\n=== Q7: Checking for any cost/rate columns in factory.db ===")
cost_cols = con.execute(
    "SELECT m.name AS tbl, p.name AS col "
    "FROM sqlite_master m JOIN pragma_table_info(m.name) p "
    "WHERE p.name LIKE '%cost%' OR p.name LIKE '%rate%' OR p.name LIKE '%price%' OR p.name LIKE '%rupee%' OR p.name LIKE '%inr%'"
).fetchall()
print(f"Matching cost columns found: {len(cost_cols)}")
for r in cost_cols:
    print(f"  {r['tbl']}.{r['col']}")

print("\n=== Q8: Late entries (> 24h after described hour end, 1-7 Nov) ===")
sql_q8 = """
WITH live AS (
    SELECT DISTINCT company_id, machine_id, reason_date, hour_start, reason, minutes,
           COALESCE(remark, '') AS remark, COALESCE(entered_by, '') AS entered_by, created_at
    FROM stop_reasons
    WHERE company_id = 1 AND deleted_at = '0000-00-00 00:00:00'
      AND reason_date BETWEEN '2026-11-01' AND '2026-11-07'
)
SELECT COUNT(*) AS total_entries,
       SUM(strftime('%s', created_at) - strftime('%s', datetime(reason_date || ' ' || hour_start, '+1 hour')) > 86400) AS late_entries
FROM live;
"""
r_q8 = con.execute(sql_q8).fetchone()
print(f"Total entries: {r_q8['total_entries']}, Late entries (> 24h): {r_q8['late_entries']}")

print("\n=== Q9: Rejections on 2 Nov (Calendar vs Plant Day) ===")
sql_q9_cal = """
WITH live AS (
    SELECT DISTINCT company_id, machine_id, reject_date, hour_start, qty, defect, created_at
    FROM rejections
    WHERE company_id = 1 AND deleted_at = '0000-00-00 00:00:00' AND reject_date = '2026-11-02'
)
SELECT SUM(qty) AS cal_qty, COUNT(*) AS cal_entries FROM live;
"""
print("Calendar date (reject_date = '2026-11-02'):", dict(con.execute(sql_q9_cal).fetchone()))

sql_q9_pd = """
WITH live AS (
    SELECT DISTINCT company_id, machine_id, reject_date, hour_start, qty, defect, created_at,
           date(datetime(reject_date || ' ' || hour_start, '-8 hours')) AS plant_day
    FROM rejections
    WHERE company_id = 1 AND deleted_at = '0000-00-00 00:00:00'
)
SELECT SUM(qty) AS pd_qty, COUNT(*) AS pd_entries FROM live WHERE plant_day = '2026-11-02';
"""
print("Plant day (2 Nov 08:00 to 3 Nov 08:00):", dict(con.execute(sql_q9_pd).fetchone()))

print("\n=== Q10: Kalpa machines running right now at snapshot watermark ===")
watermark = "2026-11-07 14:36:00"
sql_q10 = """
SELECT m.name, mm.planned, mm.running, mm.pieces
FROM machines m
LEFT JOIN machine_minutes mm
  ON m.company_id = mm.company_id AND m.machine_id = mm.machine_id AND mm.minute_start = ?
WHERE m.company_id = 1
ORDER BY m.machine_id;
"""
for r in con.execute(sql_q10, (watermark,)):
    state = "RUNNING" if r["running"] == 1 else "STOPPED"
    print(f"  {r['name']:12} | planned={r['planned']} running={r['running']} ({state}) | pieces={r['pieces']}")

con.close()
