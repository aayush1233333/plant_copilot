import sys
sys.path.insert(0, "src")
from datetime import date

from plant_copilot.minutes import classify_minutes
from plant_copilot.tenant import TenantDB, resolve_tenant
from plant_copilot.timeutil import fmt_ts, plant_day_bounds

db = TenantDB(resolve_tenant("data/factory.db", "Kalpa Appliances"))
start, end = plant_day_bounds(date(2026, 11, 3))
rows = db.minute_rows(102, fmt_ts(start), fmt_ts(end))
grid = classify_minutes(rows, start, end)
counts = {}
for _, state in grid:
    counts[state] = counts.get(state, 0) + 1
print("rows in db:", len(rows), "| grid minutes:", len(grid))
print(counts)
