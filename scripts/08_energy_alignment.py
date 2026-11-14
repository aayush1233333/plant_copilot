import calendar
import sqlite3
import statistics
import sys
from datetime import datetime
from pathlib import Path


def open_ro(db_path):
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def to_min(s):
    """'YYYY-MM-DD HH:MM[:SS]' -> whole minutes since 1970 (no timezone or DST involved)."""
    dt = datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
    return calendar.timegm(dt.timetuple()) // 60


OFFSETS = list(range(-90, 91, 15))


def show(cur, title, sql):
    print(f"\n--- {title} ---")
    cur.execute(sql)
    print(" | ".join(c[0] for c in cur.description))
    for row in cur.fetchall():
        print(" | ".join(str(v) for v in row))


def main(db_path):
    con = open_ro(db_path)
    cur = con.cursor()
    meters = cur.execute("SELECT meter_id, machine_id FROM energy_meters ORDER BY meter_id").fetchall()

    per_meter = {}
    for meter_id, machine_id in meters:
        running = {to_min(r[0]) for r in cur.execute(
            "SELECT minute_start FROM machine_minutes WHERE machine_id = ? AND running = 1", (machine_id,))}
        slots = cur.execute(
            "SELECT start_time, counter_end - counter_start FROM energy_hourly "
            "WHERE meter_id = ? ORDER BY start_time", (meter_id,)).fetchall()
        deltas = [d for _, d in slots]
        starts = [to_min(s) for s, _ in slots]
        row = {}
        for off in OFFSETS:
            counts = [sum(1 for t in range(s + off, s + off + 60) if t in running) for s in starts]
            try:
                row[off] = statistics.correlation(counts, deltas)
            except statistics.StatisticsError:
                row[off] = float("nan")
        per_meter[meter_id] = row

    print("\n--- correlation of register delta per slot vs running minutes in a window shifted by OFFSET minutes ---")
    print("offset_min | mean_corr | per meter: " + " ".join(str(m) for m in per_meter))
    for off in OFFSETS:
        vals = [per_meter[m][off] for m in per_meter]
        ok = [v for v in vals if v == v]
        mean = sum(ok) / len(ok) if ok else float("nan")
        print(f"{off:>10} | {mean:.4f} | " + " ".join(f"{v:.3f}" for v in vals))

    print("\n--- best offset per meter ---")
    for m, row in per_meter.items():
        best = max(row, key=lambda o: row[o] if row[o] == row[o] else -2)
        print("meter", m, "best offset (min):", best, "corr:", round(row[best], 4))

    show(cur, "Press 3 (machine 103), 5 Nov 19:00-21:00: running/planned minutes per 15-min block",
         "SELECT substr(minute_start, 12, 2) || ':' || printf('%02d', (CAST(substr(minute_start, 15, 2) AS INTEGER) / 15) * 15) AS block, "
         "COUNT(*) AS rows_present, SUM(running) AS running_min, SUM(planned) AS planned_min "
         "FROM machine_minutes WHERE machine_id = 103 AND minute_start >= '2026-11-05 19:00:00' "
         "AND minute_start < '2026-11-05 21:00:00' GROUP BY block ORDER BY block")

    show(cur, "meter 502 slots 5 Nov evening: register delta per slot",
         "SELECT start_time, end_time, ROUND(counter_end - counter_start, 2) AS reg_delta, pf FROM energy_hourly "
         "WHERE meter_id = 502 AND start_time >= '2026-11-05 17:30:00' AND start_time < '2026-11-05 22:00:00' "
         "ORDER BY start_time")

    con.close()


if __name__ == "__main__":
    main(sys.argv[1])
