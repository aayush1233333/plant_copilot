import sqlite3
import sys
sys.path.insert(0, "src")
from datetime import date
from pathlib import Path

from plant_copilot.minutes import STOPPED_PLANNED, UNKNOWN, classify_minutes
from plant_copilot.runs import count_state, find_runs
from plant_copilot.tenant import TenantDB, resolve_tenant
from plant_copilot.timeutil import fmt_ts, plant_day_bounds, shift_bounds

DB = "data/factory.db"
MACHINE = 102
DAY = date(2026, 11, 3)

db = TenantDB(resolve_tenant(DB, "Kalpa Appliances"))
start, end = plant_day_bounds(DAY)
rows = db.minute_rows(MACHINE, fmt_ts(start), fmt_ts(end))
grid = classify_minutes(rows, start, end)
runs = find_runs(grid)
long_runs = [r for r in runs if r["minutes"] >= 30]

print("window:", fmt_ts(start), "to", fmt_ts(end), "(exclusive)")
print("all stop runs:", len(runs), "| runs >= 30 min:", len(long_runs))
print("run length distribution (minutes -> count):")
dist = {}
for r in runs:
    dist[r["minutes"]] = dist.get(r["minutes"], 0) + 1
print(dict(sorted(dist.items())))

print("\nruns >= 30 min:")
for r in long_runs:
    print(r)

uri = Path(DB).resolve().as_uri() + "?mode=ro"
con = sqlite3.connect(uri, uri=True)
print("\nindependent SQL cross-check (rows, rows planned and not running) per long run:")
for r in long_runs:
    n, s = con.execute(
        "SELECT COUNT(*), SUM(planned = 1 AND running = 0) FROM machine_minutes "
        "WHERE company_id = 1 AND machine_id = ? AND minute_start >= ? AND minute_start <= ?",
        (MACHINE, r["start"], r["last_minute"]),
    ).fetchone()
    print(r["start"], "->", r["last_minute"], "| claimed", r["minutes"], "| sql rows", n, "| sql stopped", s)
con.close()

a_lo, a_hi = shift_bounds(DAY, "A")
a_lo, a_hi = fmt_ts(a_lo), fmt_ts(a_hi)
print("\nshift A window:", a_lo, "to", a_hi, "(exclusive)")
print("RAW q2 candidate (planned stopped minutes in shift A):", count_state(grid, STOPPED_PLANNED, a_lo, a_hi))
print("UNKNOWN minutes inside shift A:", count_state(grid, UNKNOWN, a_lo, a_hi))
print("RAW q1 candidate (stops >= 30 min):", len(long_runs))
