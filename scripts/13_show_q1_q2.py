import sys
sys.path.insert(0, "src")
from datetime import date

from plant_copilot.stoppage import q1_long_stops, q2_standstill_shift
from plant_copilot.tenant import TenantDB, resolve_tenant

db = TenantDB(resolve_tenant("data/factory.db", "Kalpa Appliances"))
for r in (q1_long_stops(db, "Press 2", date(2026, 11, 3)), q2_standstill_shift(db, "Press 2", date(2026, 11, 3), "A")):
    print(r.model_dump_json(indent=2))
    print("=" * 60)
