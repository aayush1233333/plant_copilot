import sqlite3
import sys
sys.path.insert(0, "src")
from datetime import date
from pathlib import Path

from plant_copilot.minutes import UNKNOWN, classify_minutes
from plant_copilot.tenant import TenantDB, resolve_tenant
from plant_copilot.timeutil import fmt_ts, plant_day_bounds

DB = "data/factory.db"
DAY = date(2026, 10, 31)

db = TenantDB(resolve_tenant(DB, "Kalpa Appliances"))
start, end = plant_day_bounds(DAY)
s, e = fmt_ts(start), fmt_ts(end)
print("window:", s, "to", e, "(exclusive)")
print("machine_id | name | rows | missing | pieces_sum | running_min | pieces_when_not_running")

tot_rows = tot_missing = tot_pieces = 0
for m in db.machines():
    rows = db.minute_rows(m["machine_id"], s, e)
    grid = classify_minutes(rows, start, end)
    missing = sum(1 for _t, st in grid if st == UNKNOWN)
    pieces = sum(r["pieces"] for r in rows)
    running = sum(1 for r in rows if r["running"] == 1)
    odd = sum(r["pieces"] for r in rows if r["running"] == 0)
    tot_rows += len(rows)
    tot_missing += missing
    tot_pieces += pieces
    print(m["machine_id"], "|", m["name"], "|", len(rows), "|", missing, "|", pieces, "|", running, "|", odd)

print("TOTAL rows:", tot_rows, "| missing minutes:", tot_missing, "| pieces:", tot_pieces)

con = sqlite3.connect(Path(DB).resolve().as_uri() + "?mode=ro", uri=True)
n, p = con.execute(
    "SELECT COUNT(*), SUM(pieces) FROM machine_minutes "
    "WHERE company_id = 1 AND minute_start >= ? AND minute_start < ?", (s, e)
).fetchone()
con.close()
print("independent SQL cross-check: rows", n, "| pieces", p)
