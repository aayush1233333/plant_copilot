import sys
sys.path.insert(0, "src")
from datetime import date

from plant_copilot.production import q5_total_pieces
from plant_copilot.tenant import TenantDB, resolve_tenant

db = TenantDB(resolve_tenant("data/factory.db", "Kalpa Appliances"))
print(q5_total_pieces(db, date(2026, 10, 31)).model_dump_json(indent=2))
