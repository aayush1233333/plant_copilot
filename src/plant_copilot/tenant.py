import sqlite3
from dataclasses import dataclass
from pathlib import Path

LIVE_TS = "0000-00-00 00:00:00"


@dataclass(frozen=True)
class TenantContext:
    company_id: int
    name: str
    db_path: str


def resolve_tenant(db_path: str, tenant_name: str) -> TenantContext:
    """Trusted lookup: called by the CLI/server with an operator-supplied name, never with question text."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        rows = con.execute(
            "SELECT company_id, name FROM companies WHERE lower(name) = lower(?)",
            (tenant_name,),
        ).fetchall()
    finally:
        con.close()
    if len(rows) != 1:
        raise ValueError(f"tenant {tenant_name!r} matched {len(rows)} companies; expected exactly 1")
    return TenantContext(company_id=rows[0][0], name=rows[0][1], db_path=db_path)


class TenantDB:
    def __init__(self, ctx: TenantContext):
        self._ctx = ctx
        uri = Path(ctx.db_path).resolve().as_uri() + "?mode=ro"
        self._con = sqlite3.connect(uri, uri=True)
        self._con.execute("PRAGMA query_only = ON")
        self._con.row_factory = sqlite3.Row

    def machines(self) -> list[dict]:
        rows = self._con.execute(
            "SELECT machine_id, name, plant, shop FROM machines WHERE company_id = ? ORDER BY machine_id",
            (self._ctx.company_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def energy_meters(self) -> list[dict]:
        rows = self._con.execute(
            "SELECT meter_id, machine_id, meter_name FROM energy_meters WHERE company_id = ? ORDER BY meter_id",
            (self._ctx.company_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_minute(self):
        row = self._con.execute(
            "SELECT MAX(minute_start) FROM machine_minutes WHERE company_id = ?",
            (self._ctx.company_id,),
        ).fetchone()
        return row[0]

    def minute_rows(self, machine_id: int, start: str, end: str) -> list[dict]:
        rows = self._con.execute(
            "SELECT minute_start, planned, running, pieces FROM machine_minutes "
            "WHERE company_id = ? AND machine_id = ? AND minute_start >= ? AND minute_start < ? "
            "ORDER BY minute_start, id",
            (self._ctx.company_id, machine_id, start, end),
        ).fetchall()
        return [dict(r) for r in rows]

    def stop_entries(self, machine_id: int, start: str, end: str) -> list[dict]:
        rows = self._con.execute(
            "SELECT DISTINCT reason_date || ' ' || hour_start AS hour_ts, reason, minutes, "
            "COALESCE(remark, '') AS remark, COALESCE(entered_by, '') AS entered_by, created_at "
            "FROM stop_reasons WHERE company_id = ? AND machine_id = ? AND deleted_at = ? "
            "AND reason_date || ' ' || hour_start >= ? AND reason_date || ' ' || hour_start < ? "
            "ORDER BY hour_ts, reason, created_at",
            (self._ctx.company_id, machine_id, LIVE_TS, start, end),
        ).fetchall()
        return [dict(r) for r in rows]

    def energy_rows(self, machine_id: int, start: str, end: str) -> list[dict]:
        """Tenant-isolated: joins energy_meters on company_id."""
        rows = self._con.execute(
            "SELECT h.id, h.meter_id, h.report_date, h.shift, h.start_time, h.end_time, "
            "h.kwh, h.counter_start, h.counter_end, h.pf "
            "FROM energy_hourly h "
            "JOIN energy_meters m ON h.meter_id = m.meter_id "
            "WHERE m.company_id = ? AND m.machine_id = ? "
            "AND h.start_time >= ? AND h.start_time < ? "
            "ORDER BY h.start_time, h.id",
            (self._ctx.company_id, machine_id, start, end),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._con.close()
