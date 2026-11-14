from datetime import date, timedelta

from plant_copilot.envelope import Coverage, MetricResult
from plant_copilot.timeutil import fmt_ts, parse_ts, plant_day_bounds

SQL_USED = (
    "SELECT minute_start, planned, running, pieces FROM machine_minutes "
    "WHERE company_id = :tenant AND machine_id = :machine AND minute_start >= :start AND minute_start < :end "
    "ORDER BY minute_start, id  -- run once per machine of the tenant; pieces are summed in Python "
    "after collapsing exact duplicate rows"
)


def sum_pieces(rows, start, end):
    """Sum per-minute pieces over every minute in [start, end).
    Exact duplicate rows count once. A minute with no row, conflicting rows, or NULL pieces is MISSING, never zero."""
    variants = {}
    for r in rows:
        variants.setdefault(r["minute_start"], set()).add((r["planned"], r["running"], r["pieces"]))
    total = 0
    missing = []
    t = start
    while t < end:
        text = fmt_ts(t)
        v = variants.get(text)
        if not v or len(v) > 1:
            missing.append(text)
        else:
            pieces = next(iter(v))[2]
            if pieces is None:
                missing.append(text)
            else:
                total += pieces
        t += timedelta(minutes=1)
    return total, missing


def q5_total_pieces(db, day: date) -> MetricResult:
    metric = "q5_total_pieces_plant_day"
    params = {"plant_day": day.isoformat(), "scope": "all machines of the tenant"}
    start, end = plant_day_bounds(day)
    as_of = db.latest_minute() or ""

    eff_end, partial = end, False
    if as_of:
        last = parse_ts(as_of) + timedelta(minutes=1)
        if last < end:
            eff_end, partial = max(start, last), True

    machines = db.machines()
    total, upper_extra = 0, 0
    missing_all, details = [], []
    for m in machines:
        rows = db.minute_rows(m["machine_id"], fmt_ts(start), fmt_ts(end))
        pieces, missing = sum_pieces(rows, start, eff_end)
        peak = max([r["pieces"] for r in rows if r["pieces"] is not None], default=0)
        total += pieces
        upper_extra += peak * len(missing)
        missing_all += [m["name"] + ": " + x for x in missing]
        details.append({
            "machine": m["name"], "pieces": pieces,
            "missing_minutes": len(missing), "max_pieces_in_a_minute": peak,
        })

    minutes_in_window = int((eff_end - start).total_seconds() // 60)
    expected = minutes_in_window * len(machines)
    observed = expected - len(missing_all)

    caveats = [
        "Plant day = 08:00 to 08:00 next morning.",
        "Sums the per-minute pieces column as recorded (profiling showed it is a per-minute count, 0 when a machine is not running).",
        "These are pieces counted by the machines, not good pieces: rejections are a separate table and are not subtracted.",
    ]
    if missing_all:
        caveats.append(
            str(len(missing_all)) + " machine-minute(s) had no usable data; their pieces are unknown, so the true total "
            "may be higher. Missing minutes are never treated as zero."
        )
    zero = [d["machine"] for d in details if d["pieces"] == 0]
    if zero:
        caveats.append("Machines with 0 recorded pieces in this window: " + ", ".join(zero) + ".")
    if partial:
        caveats.append("The plant day was not finished at the snapshot time; only minutes up to the snapshot are included.")

    display = str(total) + " pieces counted by " + str(len(machines)) + " machines"
    if missing_all:
        display += " (lower bound: " + str(len(missing_all)) + " machine-minutes had no data)"
    if partial:
        display += " - plant day not finished at snapshot"

    return MetricResult(
        status="incomplete" if partial else "ok",
        value=total, display=display, metric=metric, sql=SQL_USED,
        logic="for each machine of the tenant: collapse exact duplicate minute rows, sum pieces over the plant-day window, add up machines",
        params=params, rows_used=observed, as_of=as_of,
        coverage=Coverage(expected=expected, observed=observed, missing_ranges=missing_all),
        caveats=caveats,
        sensitivity=[{
            "name": "upper_bound_if_missing_minutes_ran_at_peak", "value": total + upper_extra,
            "note": "each missing minute assumed to produce that machine's highest per-minute count in the window",
        }],
        details=details,
    ).seal()
