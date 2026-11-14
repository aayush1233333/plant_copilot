import sqlite3
from pathlib import Path

con = sqlite3.connect(Path("data/factory.db").resolve().as_uri() + "?mode=ro", uri=True)
print("plant_day | rows | planned_min | running_min | pieces")
for row in con.execute(
    "SELECT date(minute_start, '-8 hours'), COUNT(*), SUM(planned), SUM(running), SUM(pieces) "
    "FROM machine_minutes WHERE company_id = 1 AND machine_id = 111 GROUP BY 1 ORDER BY 1"
):
    print(" | ".join(str(v) for v in row))
con.close()
