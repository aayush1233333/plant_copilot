import sqlite3
from pathlib import Path

DB = Path("data/factory.db").resolve().as_uri() + "?mode=ro"
con = sqlite3.connect(DB, uri=True)
con.row_factory = sqlite3.Row

print("=== 1. Meter 501 (Press 2) - 4 Nov Shift A (q3) ===")
rows_501 = con.execute(
    "SELECT id, report_date, shift, start_time, end_time, counter_start, counter_end, "
    "ROUND(counter_end - counter_start, 2) AS reg_delta, kwh "
    "FROM energy_hourly WHERE meter_id = 501 AND report_date = '2026-11-04' AND shift = 'A' "
    "ORDER BY start_time"
).fetchall()

for r in rows_501:
    print(f"{r['start_time']} .. {r['end_time']} | reg: {r['counter_start']} -> {r['counter_end']} (delta {r['reg_delta']}) | kwh: {r['kwh']}")

print(f"Total rows in shift: {len(rows_501)} of 12 expected")
start_reg = rows_501[0]["counter_start"]
end_reg = rows_501[-1]["counter_end"]
sum_kwh = sum(r["kwh"] for r in rows_501)
print(f"Shift start register (07:30:01): {start_reg}")
print(f"Shift end register (19:30:00): {end_reg}")
print(f"Total register delta across shift: {round(end_reg - start_reg, 2)} kWh (1 decimal: {round(end_reg - start_reg, 1)})")
print(f"Raw kwh sum of observed rows: {round(sum_kwh, 2)} kWh")

print("\n=== 2. Meter 502 (Press 3) - 5 Nov Shift A & Neighbors (q4) ===")
rows_502 = con.execute(
    "SELECT id, report_date, shift, start_time, end_time, counter_start, counter_end, "
    "ROUND(counter_end - counter_start, 2) AS reg_delta, kwh "
    "FROM energy_hourly WHERE meter_id = 502 AND ("
    "  (report_date = '2026-11-04' AND shift = 'B' AND end_time >= '2026-11-05 06:30:00') OR "
    "  (report_date = '2026-11-05' AND shift = 'A') OR "
    "  (report_date = '2026-11-05' AND shift = 'B' AND start_time <= '2026-11-05 20:30:00')"
    ") ORDER BY start_time"
).fetchall()

for r in rows_502:
    print(f"[{r['report_date']} {r['shift']}] {r['start_time']} .. {r['end_time']} | reg: {r['counter_start']} -> {r['counter_end']} (delta {r['reg_delta']}) | kwh: {r['kwh']}")

shift_a_502 = [r for r in rows_502 if r["report_date"] == "2026-11-05" and r["shift"] == "A"]
print(f"Total rows directly labeled Shift A: {len(shift_a_502)} of 12 expected")

con.close()
