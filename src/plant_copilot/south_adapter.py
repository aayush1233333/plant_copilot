import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plant_copilot.envelope import MetricResult


@dataclass(frozen=True)
class SouthCapabilities:
    running_now: bool = True
    pieces_count: bool = True
    rejects_count: bool = True
    energy_cumulative: bool = True
    downtime_intervals: bool = True
    planned_time: bool = False
    late_entries: bool = False
    shift_schedules: bool = False
    financial_cost: bool = False


class SouthPlantAdapter:
    CAPABILITIES = SouthCapabilities()

    def __init__(self, db_path: str = "data/south_sample.db"):
        self.db_path = db_path
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        self._con = sqlite3.connect(uri, uri=True)
        self._con.execute("PRAGMA query_only = ON")
        self._con.row_factory = sqlite3.Row

    def assets(self) -> list[dict]:
        rows = self._con.execute("SELECT asset_code, asset_desc, line FROM assets ORDER BY asset_code").fetchall()
        return [dict(r) for r in rows]

    def latest_timestamp(self) -> str:
        row = self._con.execute("SELECT MAX(stamp) FROM tbl_mc_status").fetchone()
        return row[0] if row else ""

    def running_now(self) -> MetricResult:
        metric = "south_running_now"
        as_of = self.latest_timestamp()
        sql = "SELECT asset_code, run_flag, qty_ok, qty_ng FROM tbl_mc_status WHERE stamp = ?"
        rows = self._con.execute(sql, (as_of,)).fetchall()

        running = [r["asset_code"] for r in rows if r["run_flag"] == "Y"]
        stopped = [r["asset_code"] for r in rows if r["run_flag"] == "N"]

        return MetricResult(
            status="ok",
            value=running,
            display=f"{len(running)} assets running at Plant South snapshot {as_of} ({', '.join(running)})",
            metric=metric,
            sql=sql,
            params={"snapshot_time": as_of},
            rows_used=len(rows),
            as_of=as_of,
            caveats=[
                "Plant South status is recorded at 5-minute intervals.",
                "run_flag is binary 'Y' or 'N'.",
            ],
            sensitivity=[
                {"name": "running_assets", "value": running},
                {"name": "stopped_assets", "value": stopped},
            ],
            details=[dict(r) for r in rows],
        ).seal()

    def unsupported(self, metric_name: str, reason: str) -> MetricResult:
        return MetricResult(
            status="insufficient_data",
            value=None,
            display=f"insufficient_data: {metric_name} is unsupported for Plant South schema.",
            metric=metric_name,
            as_of=self.latest_timestamp(),
            caveats=[
                "Amendment 8: Do not force Plant North rules onto Plant South.",
                f"Plant South capability check failed: {reason}",
            ],
            needed_data=reason,
        ).seal()

    def close(self) -> None:
        self._con.close()
