import sqlite3
import sys
sys.path.insert(0, "src")
from datetime import date
from pathlib import Path

from plant_copilot.minutes import STOPPED_PLANNED, UNKNOWN, classify_minutes
from plant_copilot.runs import find_runs
from plant_copilot.tenant import TenantDB, resolve_tenant
from plant_copilot.timeutil import fmt_ts, plant_day_bounds

DB = "data/factory.db"
MACHINE = 102
DAY = date(2026, 11, 3)
LIVE = "0000-00-00 00:00:00"

db = TenantDB(resolve_tenant(DB, "Kalpa Appliances"))
start, end = plant_day_bounds(DAY)
grid = classify_minutes(db.minute_rows(MACHINE, fmt_ts(start), fmt_ts(end)), start, end)
runs = find_runs(grid)
long_runs = [r for r in runs if r["minutes"] >= 30]
idx = {t: i for i, (t, _s) in enumerate(grid)}

# Profiling-only raw read of stop entries (company_id = 1 hard-coded here only).
con = sqlite3.connect(Path(DB).resolve().as_uri() + "?mode=ro", uri=True)
entries = con.execute(
    "SELECT DISTINCT reason_date || ' ' || hour_start, reason, minutes, COALESCE(remark, ''), "
    "COALESCE(entered_by, ''), created_at FROM stop_reasons "
    "WHERE company_id = 1 AND machine_id = ? AND deleted_at = ? "
    "AND reason_date || ' ' || hour_start >= ? AND reason_date || ' ' || hour_start < ? "
    "ORDER BY 1, 2",
    (MACHINE, LIVE, fmt_ts(start), fmt_ts(end)),
).fetchall()
con.close()

di = {}
other = {}
for hour_ts, reason, minutes, _remark, _by, _created in entries:
    target = di if reason == "Data Issue" else other
    target[hour_ts] = target.get(hour_ts, 0) + minutes

hours = []
for i in range(24):
    block = grid[i * 60:(i + 1) * 60]
    text = block[0][0]
    hours.append({
        "hour": text,
        "stopped": sum(1 for _t, s in block if s == STOPPED_PLANNED),
        "unknown": sum(1 for _t, s in block if s == UNKNOWN),
        "di": di.get(text, 0),
        "other": other.get(text, 0),
    })

print("window:", fmt_ts(start), "to", fmt_ts(end), "(exclusive)")
print("live deduplicated stop entries for machine", MACHINE, "in window:", len(entries))
print("Data Issue entries:", sum(1 for e in entries if e[1] == "Data Issue"))

print("\nData Issue entries (hour | minutes | remark | entered_by | created_at):")
for e in entries:
    if e[1] == "Data Issue":
        print(e[0], "|", e[2], "|", e[3], "|", e[4], "|", e[5])

print("\nhours with a Data Issue entry:")
print("hour | stopped | unknown | DI_entered | other_entered | DI exceeds stopped?")
for h in hours:
    if h["di"] > 0:
        print(h["hour"], "|", h["stopped"], "|", h["unknown"], "|", h["di"], "|", h["other"], "|", h["di"] > h["stopped"])

a = hours[:12]
a_stopped = sum(h["stopped"] for h in a)
a_unknown = sum(h["unknown"] for h in a)
a_di = sum(h["di"] for h in a)
a_di_capped = sum(min(h["di"], h["stopped"]) for h in a)
print("\nshift A: stopped", a_stopped, "| unknown", a_unknown, "| DI entered", a_di, "| DI capped per hour", a_di_capped)
print("RAW q2 range (unknown as not stopped .. as stopped):", a_stopped, "..", a_stopped + a_unknown)
print("CORRECTED q2 candidate, capped:", a_stopped - a_di_capped)
print("CORRECTED q2 candidate, uncapped:", a_stopped - a_di)

print("\nlong runs vs Data Issue minutes entered in the hours they touch:")
for r in long_runs:
    i0, i1 = idx[r["start"]], idx[r["last_minute"]]
    touched = range(i0 // 60, i1 // 60 + 1)
    di_touch = sum(hours[k]["di"] for k in touched)
    worst = max(0, r["minutes"] - di_touch)
    print(r["start"], "| minutes", r["minutes"], "| hours touched", len(touched),
          "| DI in those hours", di_touch, "| worst-case length", worst, "| could drop below 30:", worst < 30)

upper = [(t, STOPPED_PLANNED if s == UNKNOWN else s) for t, s in grid]
upper_long = [r for r in find_runs(upper) if r["minutes"] >= 30]
print("\nq1 sensitivity to UNKNOWN minutes: raw", len(long_runs), "| if every UNKNOWN minute were a planned stop:", len(upper_long))
print("runs touching an UNKNOWN minute (start | minutes | before | after):")
for r in runs:
    if r["before"] == UNKNOWN or r["after"] == UNKNOWN:
        print(r["start"], "|", r["minutes"], "|", r["before"], "|", r["after"])
