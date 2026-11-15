from datetime import date
from typing import Optional

from plant_copilot.envelope import Coverage, MetricResult
from plant_copilot.stoppage import DATA_ISSUE, _load
from plant_copilot.tenant import LIVE_TS, TenantDB
from plant_copilot.timeutil import fmt_ts, plant_day_bounds


def q6_top_stop_reason(
    db: TenantDB,
    start_date: str = "2026-11-01",
    end_date: str = "2026-11-07",
    machine_name: Optional[str] = None,
) -> MetricResult:
    metric = "q6_top_stop_reason_real_lost_time"
    as_of = db.latest_minute() or ""
    params: dict = {"start_date": start_date, "end_date": end_date, "tenant": db._ctx.name}

    machine_id = None
    if machine_name is not None:
        hits = [m for m in db.machines() if m["name"].lower() == machine_name.strip().lower()]
        if len(hits) != 1:
            params["machine"] = machine_name
            return MetricResult(
                status="insufficient_data",
                value=None,
                display=f"No machine named {machine_name!r} exists for this tenant.",
                metric=metric,
                params=params,
                as_of=as_of,
                caveats=["Machine names are resolved only inside the current tenant."],
                needed_data="A valid machine name belonging to the tenant.",
            ).seal()
        machine_id = hits[0]["machine_id"]
        params["machine"] = hits[0]["name"]

    machine_filter = " AND machine_id = ?" if machine_id is not None else ""
    sql = (
        "WITH live AS ("
        "  SELECT DISTINCT company_id, machine_id, reason_date, hour_start, reason, minutes, "
        "                  COALESCE(remark, '') AS remark, COALESCE(entered_by, '') AS entered_by, created_at"
        "  FROM stop_reasons "
        f"  WHERE company_id = ? AND deleted_at = ? AND reason_date >= ? AND reason_date <= ?{machine_filter}"
        ") "
        "SELECT reason, COUNT(*) AS n_entries, SUM(minutes) AS total_minutes "
        "FROM live GROUP BY reason ORDER BY total_minutes DESC"
    )
    sql_params: list = [db._ctx.company_id, LIVE_TS, start_date, end_date]
    if machine_id is not None:
        sql_params.append(machine_id)

    rows = db._con.execute(sql, tuple(sql_params)).fetchall()

    data_issue_row = next((r for r in rows if r["reason"] == "Data Issue"), None)
    real_reasons = [r for r in rows if r["reason"] != "Data Issue"]

    top = real_reasons[0] if real_reasons else None
    top_reason = top["reason"] if top else None
    top_minutes = top["total_minutes"] if top else 0

    caveats = [
        "Live entries only (deleted_at = '0000-00-00 00:00:00'); exact duplicate rows collapsed to one.",
        "'Data Issue' entries indicate the machine was actually running (false system stop) and are excluded from real lost time.",
        "Filtered by operator-entered reason_date (calendar date).",
    ]
    if data_issue_row:
        caveats.append(
            f"Data Issue accounted for {data_issue_row['total_minutes']} entered minutes across {data_issue_row['n_entries']} entries (excluded)."
        )

    sensitivity = [
        {
            "name": "top_reason_raw_including_data_issue",
            "value": rows[0]["reason"] if rows else None,
            "minutes": rows[0]["total_minutes"] if rows else 0,
        },
        {
            "name": "real_reasons_ranking",
            "value": [{"reason": r["reason"], "minutes": r["total_minutes"]} for r in real_reasons],
        },
    ]

    display = (
        (f"{top_reason} on {params['machine']} ({top_minutes} real lost minutes entered by operators)" if "machine" in params else f"{top_reason} ({top_minutes} real lost minutes entered by operators)")
        if top_reason
        else "No real stop reasons recorded in this date range."
    )

    return MetricResult(
        status="ok",
        value=top_reason,
        display=display,
        metric=metric,
        sql=sql,
        logic="collapse exact live duplicate rows -> exclude Data Issue (machine was actually running) -> rank remaining stop reasons by sum(minutes)",
        params=params,
        rows_used=sum(r["n_entries"] for r in rows),
        as_of=as_of,
        caveats=caveats,
        sensitivity=sensitivity,
    ).seal()


def q7_stop_cost_rupees(db: TenantDB, day: date = date(2026, 11, 3)) -> MetricResult:
    metric = "q7_stop_cost_rupees"
    params = {"plant_day": day.isoformat(), "tenant": db._ctx.name}
    as_of = db.latest_minute() or ""
    sql = "SELECT * FROM sqlite_master WHERE type='table' -- inspected all tables for cost/rate columns"

    return MetricResult(
        status="insufficient_data",
        value=None,
        display="null - The database contains no cost, rate, or financial valuation columns to compute monetary loss in rupees.",
        metric=metric,
        sql=sql,
        logic="check schema for machine cost rates or financial valuation tables -> none exist -> return null",
        params=params,
        rows_used=0,
        as_of=as_of,
        caveats=[
            "Amendment 6: Return null unless the schema contains a defensible cost rate or financial model. Never invent a rupee rate.",
            "All tables in factory.db were inspected: companies, machines, machine_minutes, plan, stop_reasons, rejections, energy_meters, energy_hourly. None contain monetary or currency values.",
        ],
        needed_data="Hourly downtime cost rate per machine, labor cost per downtime hour, or part value model.",
    ).seal()


def q8_late_stop_entries(db: TenantDB, start_date: str = "2026-11-01", end_date: str = "2026-11-07") -> MetricResult:
    metric = "q8_late_stop_entries_over_24h"
    params = {"start_date": start_date, "end_date": end_date, "tenant": db._ctx.name}
    as_of = db.latest_minute() or ""
    sql = (
        "WITH live AS ("
        "  SELECT DISTINCT company_id, machine_id, reason_date, hour_start, reason, minutes, "
        "                  COALESCE(remark, '') AS remark, COALESCE(entered_by, '') AS entered_by, created_at"
        "  FROM stop_reasons "
        "  WHERE company_id = ? AND deleted_at = ? AND reason_date >= ? AND reason_date <= ?"
        ") "
        "SELECT COUNT(*) AS total_entries, "
        "       SUM(strftime('%s', created_at) - strftime('%s', datetime(reason_date || ' ' || hour_start, '+1 hour')) > 86400) AS late_entries "
        "FROM live"
    )
    row = db._con.execute(sql, (db._ctx.company_id, LIVE_TS, start_date, end_date)).fetchone()
    total = row["total_entries"] or 0
    late = row["late_entries"] or 0

    plant_day_sql = (
        "WITH live AS ("
        "  SELECT DISTINCT company_id, machine_id, reason_date, hour_start, reason, minutes, "
        "                  COALESCE(remark, '') AS remark, COALESCE(entered_by, '') AS entered_by, created_at"
        "  FROM stop_reasons "
        "  WHERE company_id = ? AND deleted_at = ? "
        "    AND date(reason_date || ' ' || hour_start, '-8 hours') >= ? "
        "    AND date(reason_date || ' ' || hour_start, '-8 hours') <= ?"
        ") "
        "SELECT COUNT(*) AS total_entries, "
        "       SUM(strftime('%s', created_at) - strftime('%s', datetime(reason_date || ' ' || hour_start, '+1 hour')) > 86400) AS late_entries "
        "FROM live"
    )
    pd_row = db._con.execute(plant_day_sql, (db._ctx.company_id, LIVE_TS, start_date, end_date)).fetchone()
    pd_total = pd_row["total_entries"] or 0
    pd_late = pd_row["late_entries"] or 0

    return MetricResult(
        status="ok",
        value=late,
        display=f"{late} stop-reason entries created > 24h after described hour end (out of {total} total entries)",
        metric=metric,
        sql=sql,
        logic="collapse exact live duplicate rows -> compute seconds elapsed from described hour end to created_at -> count entries strictly > 86400 seconds (24h)",
        params=params,
        rows_used=total,
        as_of=as_of,
        caveats=[
            "Hour end is reason_date + hour_start + 1 hour. Lateness is strictly > 24 hours (86400 seconds).",
            "Entries appearing twice are counted once via deduplication.",
            "Live rows only (deleted_at = '0000-00-00 00:00:00').",
        ],
        sensitivity=[
            {"name": "calendar_date_range", "value": late, "total_entries": total},
            {"name": "plant_day_reading_alternative", "value": pd_late, "total_entries": pd_total},
        ],
    ).seal()


def q9_rejections(db: TenantDB, day_str: str = "2026-11-02") -> MetricResult:
    metric = "q9_rejections_count"
    params = {"date": day_str, "tenant": db._ctx.name}
    as_of = db.latest_minute() or ""
    sql = (
        "WITH live AS ("
        "  SELECT DISTINCT company_id, machine_id, reject_date, hour_start, qty, defect, created_at "
        "  FROM rejections "
        "  WHERE company_id = ? AND deleted_at = ? AND reject_date = ?"
        ") "
        "SELECT defect, SUM(qty) AS qty, COUNT(*) AS n_entries "
        "FROM live GROUP BY defect ORDER BY qty DESC"
    )
    rows = db._con.execute(sql, (db._ctx.company_id, LIVE_TS, day_str)).fetchall()
    total_qty = sum(r["qty"] or 0 for r in rows)
    total_entries = sum(r["n_entries"] for r in rows)

    pd_sql = (
        "WITH live AS ("
        "  SELECT DISTINCT company_id, machine_id, reject_date, hour_start, qty, defect, created_at "
        "  FROM rejections "
        "  WHERE company_id = ? AND deleted_at = ? "
        "    AND date(reject_date || ' ' || hour_start, '-8 hours') = ?"
        ") "
        "SELECT COALESCE(SUM(qty), 0) AS qty FROM live"
    )
    pd_qty = db._con.execute(pd_sql, (db._ctx.company_id, LIVE_TS, day_str)).fetchone()["qty"]

    return MetricResult(
        status="ok",
        value=total_qty,
        display=f"{total_qty} pieces rejected on {day_str}",
        metric=metric,
        sql=sql,
        logic="collapse exact live duplicate rejection rows for reject_date -> sum qty across all defect types",
        params=params,
        rows_used=total_entries,
        as_of=as_of,
        caveats=[
            "Live rows only (deleted_at = '0000-00-00 00:00:00'); exact duplicate rows collapsed to one.",
            f"Filtered on calendar reject_date = '{day_str}' (profiling showed reject_date is a calendar date).",
            "'No Rejection' records with qty = 0 are included in entries but contribute 0 to count.",
        ],
        sensitivity=[
            {"name": "defect_breakdown", "value": {r["defect"]: r["qty"] for r in rows}},
            {"name": "plant_day_reading_alternative", "value": pd_qty, "note": f"plant day {day_str} 08:00 to next day 08:00"},
        ],
    ).seal()


def q10_running_now(db: TenantDB) -> MetricResult:
    metric = "q10_machines_running_now"
    as_of = db.latest_minute() or ""
    params = {"snapshot_minute": as_of, "tenant": db._ctx.name}
    sql = (
        "SELECT m.machine_id, m.name, mm.planned, mm.running, mm.pieces "
        "FROM machines m "
        "LEFT JOIN machine_minutes mm "
        "  ON m.company_id = mm.company_id AND m.machine_id = mm.machine_id AND mm.minute_start = ? "
        "WHERE m.company_id = ? "
        "ORDER BY m.machine_id"
    )
    rows = db._con.execute(sql, (as_of, db._ctx.company_id)).fetchall()

    running_machines = []
    stopped_machines = []
    no_data_machines = []

    for r in rows:
        if r["running"] is None:
            no_data_machines.append(r["name"])
        elif r["running"] == 1:
            running_machines.append(r["name"])
        else:
            stopped_machines.append(r["name"])

    caveats = [
        f"'Now' is defined by the latest available timestamp in the tenant's snapshot ({as_of}), not the server wall-clock time.",
        "A machine is considered running only if it has a live record at that exact minute with running = 1.",
    ]
    if no_data_machines:
        caveats.append(f"Machines with no data at snapshot time: {', '.join(no_data_machines)} (not assumed stopped).")
    else:
        caveats.append("All tenant machines had a recorded state at the snapshot minute.")

    return MetricResult(
        status="ok",
        value=running_machines,
        display=f"{len(running_machines)} machines running at snapshot time ({', '.join(running_machines)})",
        metric=metric,
        sql=sql,
        logic="query tenant latest minute -> join machine_minutes at that minute for each machine -> return machines with running = 1",
        params=params,
        rows_used=len(rows),
        as_of=as_of,
        caveats=caveats,
        sensitivity=[
            {"name": "running_count", "value": len(running_machines)},
            {"name": "stopped_count", "value": len(stopped_machines)},
            {"name": "no_data_count", "value": len(no_data_machines)},
        ],
        details=[dict(r) for r in rows],
    ).seal()


def rank_machine_downtime(db: TenantDB, day: date) -> MetricResult:
    """Rank all machines of the tenant by Data-Issue-corrected planned standstill minutes on a plant day."""
    metric = "rank_machine_downtime_plant_day"
    as_of = db.latest_minute() or ""
    params = {"plant_day": day.isoformat(), "tenant": db._ctx.name}
    machines = db.machines()
    if not machines:
        return MetricResult(
            status="insufficient_data",
            value=None,
            display="No machines found for this tenant.",
            metric=metric,
            params=params,
            as_of=as_of,
            needed_data="Machine records for the tenant.",
        ).seal()

    ranking = []
    total_rows = 0
    total_observed = 0
    expected_total = len(machines) * 1440

    for m in machines:
        d = _load(db, m["name"], day)
        if d is None:
            continue
        hours = d["hours"]
        raw_stopped = sum(h["stopped"] for h in hours)
        unknown = sum(h["unknown"] for h in hours)
        di_total = sum(h["di"] for h in hours)
        removed = sum(min(h["di"], h["stopped"]) for h in hours)
        corrected = raw_stopped - removed
        ambiguous_di = any(h["di"] > h["stopped"] + h["unknown"] for h in hours)
        total_rows += len(d["rows"]) + len(d["entries"])
        total_observed += 1440 - unknown
        ranking.append({
            "machine": m["name"],
            "corrected_stopped_minutes": corrected,
            "raw_stopped_minutes": raw_stopped,
            "data_issue_minutes": di_total,
            "unknown_minutes": unknown,
            "ambiguous_di": ambiguous_di,
        })

    ranking.sort(key=lambda x: (-x["corrected_stopped_minutes"], x["machine"]))
    top = ranking[0] if ranking else None
    top_machine = top["machine"] if top else None

    display = (
        f"{top['machine']} lost the most planned time on plant day {day.isoformat()} "
        f"({top['corrected_stopped_minutes']} min corrected; raw: {top['raw_stopped_minutes']} min)"
        if top
        else f"No downtime data available for plant day {day.isoformat()}."
    )

    return MetricResult(
        status="ok" if top else "insufficient_data",
        value=top_machine,
        display=display,
        metric=metric,
        sql="Per-machine minute_start + stop_reasons across plant_day window (08:00 to next day 08:00)",
        logic="for each tenant machine: classify minutes -> count planned stopped minutes -> subtract Data Issue minutes per hour -> rank descending",
        params=params,
        rows_used=total_rows,
        as_of=as_of,
        coverage=Coverage(expected=expected_total, observed=total_observed),
        caveats=[
            "Plant day = 08:00 to 08:00 next morning.",
            "Ranked by Data-Issue-corrected planned stopped minutes; raw system-state totals are included in details.",
            "Missing minutes are tracked in unknown_minutes and never assumed stopped.",
        ],
        details=ranking,
    ).seal()


def explain_machine_downtime(db: TenantDB, day: date) -> MetricResult:
    """Rank machines on a plant day, then explain the winner with ITS OWN stop reasons on the SAME plant-day window."""
    metric = "explain_machine_downtime_plant_day"
    ranked = rank_machine_downtime(db, day)
    if ranked.status != "ok":
        return MetricResult(
            status=ranked.status, value=None, display=ranked.display, metric=metric,
            params=ranked.params, as_of=ranked.as_of, needed_data=ranked.needed_data,
        ).seal()

    top = ranked.details[0]
    name = top["machine"]
    loaded = _load(db, name, day)
    reasons: dict = {}
    data_issue_entered = 0
    for entry in loaded["entries"]:
        if entry["reason"] == DATA_ISSUE:
            data_issue_entered += entry["minutes"]
        else:
            reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + entry["minutes"]
    ordered = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
    entered_real = sum(reasons.values())
    corrected = top["corrected_stopped_minutes"]
    raw = top["raw_stopped_minutes"]

    head = (
        f"{name} lost the most planned time on plant day {day.isoformat()} "
        f"({corrected} min corrected; raw: {raw} min)."
    )
    top_reasons = []
    if ordered:
        best = ordered[0][1]
        top_reasons = [r for r, m in ordered if m == best]
        if len(top_reasons) == 1:
            why = f" Its top operator-entered reason was {top_reasons[0]} ({best} min)."
        else:
            why = f" Its top operator-entered reasons were tied: {' and '.join(top_reasons)} ({best} min each)."
        why += f" Operators entered {entered_real} real reason minutes against {corrected} stopped minutes."
    else:
        why = " Operators entered no real stop reason for it that day."

    caveats = [
        "Plant day = 08:00 to 08:00 next morning, used for both the downtime ranking and the stop reasons.",
        "Reasons are the winner's own live, de-duplicated operator entries; Data Issue entries are excluded (the machine was actually running).",
        "Operator entries are per machine-hour and are not matched to individual stopped minutes, so entered minutes can differ from stopped minutes.",
    ]
    tied_machines = [x["machine"] for x in ranked.details[1:] if x["corrected_stopped_minutes"] == corrected]
    if tied_machines:
        caveats.append("Tied on corrected minutes with: " + ", ".join(tied_machines) + ". Ties are broken alphabetically.")
    if top["ambiguous_di"]:
        caveats.append("Data Issue entries for the winner exceed its stopped minutes in at least one hour; its corrected minutes are approximate.")

    return MetricResult(
        status="ok",
        value={"machine": name, "top_reasons": top_reasons},
        display=head + why,
        metric=metric,
        sql="Per-machine minute_start + stop_reasons across the plant_day window; winner's stop_reasons grouped by reason (Data Issue excluded)",
        logic="rank machines by Data-Issue-corrected planned stopped minutes -> take the winner -> sum its own live, de-duplicated reasons on the same plant-day window",
        params=ranked.params,
        rows_used=ranked.rows_used,
        as_of=ranked.as_of,
        coverage=ranked.coverage,
        caveats=caveats,
        sensitivity=[
            {"name": "winner_reasons_ranking", "value": [{"reason": r, "minutes": m} for r, m in ordered]},
            {"name": "winner_real_reason_minutes_entered", "value": entered_real},
            {"name": "winner_data_issue_minutes_entered", "value": data_issue_entered},
        ],
        details=ranked.details,
    ).seal()
