import json
from datetime import date
from pathlib import Path

from plant_copilot.energy import energy_shift
from plant_copilot.operations import (
    q6_top_stop_reason,
    q7_stop_cost_rupees,
    q8_late_stop_entries,
    q9_rejections,
    q10_running_now,
)
from plant_copilot.production import q5_total_pieces
from plant_copilot.stoppage import q1_long_stops, q2_standstill_shift
from plant_copilot.tenant import TenantDB, resolve_tenant

DB_PATH = "data/factory.db"
TENANT = "Kalpa Appliances"

db = TenantDB(resolve_tenant(DB_PATH, TENANT))

print(f"Generating answers for tenant: {TENANT} (Snapshot Watermark: {db.latest_minute()})")

# 1. Evaluate all metrics
r1 = q1_long_stops(db, "Press 2", date(2026, 11, 3))
r2 = q2_standstill_shift(db, "Press 2", date(2026, 11, 3), "A")
r3 = energy_shift(db, "Press 2", date(2026, 11, 4), "A")
r4 = energy_shift(db, "Press 3", date(2026, 11, 5), "A")
r5 = q5_total_pieces(db, date(2026, 10, 31))
r6 = q6_top_stop_reason(db, "2026-11-01", "2026-11-07")
r7 = q7_stop_cost_rupees(db, date(2026, 11, 3))
r8 = q8_late_stop_entries(db, "2026-11-01", "2026-11-07")
r9 = q9_rejections(db, "2026-11-02")
r10 = q10_running_now(db)

# 2. Extract values for answers.json
answers = {
    "q1": r1.value,
    "q2": r2.value,
    "q3": r3.value,
    "q4": r4.value,
    "q5": r5.value,
    "q6": r6.value,
    "q7": r7.value,
    "q8": r8.value,
    "q9": r9.value,
    "q10": r10.value,
}

# 3. Write answers.json
with open("answers.json", "w", encoding="utf-8") as f:
    json.dump(answers, f, indent=2)

print("\n=== answers.json written successfully ===")
print(json.dumps(answers, indent=2))

# 4. Save full evidence envelopes to answers_evidence.json
evidence = {
    "q1": r1.model_dump(),
    "q2": r2.model_dump(),
    "q3": r3.model_dump(),
    "q4": r4.model_dump(),
    "q5": r5.model_dump(),
    "q6": r6.model_dump(),
    "q7": r7.model_dump(),
    "q8": r8.model_dump(),
    "q9": r9.model_dump(),
    "q10": r10.model_dump(),
}

with open("answers_evidence.json", "w", encoding="utf-8") as f:
    json.dump(evidence, f, indent=2)

print("\n=== Full evidence envelopes saved to answers_evidence.json ===")

db.close()
