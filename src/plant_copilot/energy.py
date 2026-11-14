from datetime import date, datetime, timedelta

from plant_copilot.envelope import Coverage, MetricResult
from plant_copilot.tenant import TenantDB
from plant_copilot.timeutil import fmt_ts, parse_ts

SQL_USED = (
    "SELECT h.id, h.meter_id, h.report_date, h.shift, h.start_time, h.end_time, "
    "h.kwh, h.counter_start, h.counter_end, h.pf "
    "FROM energy_hourly h "
    "JOIN energy_meters m ON h.meter_id = m.meter_id "
    "WHERE m.company_id = :tenant AND m.machine_id = :machine "
    "AND h.start_time >= :start AND h.start_time < :end "
    "ORDER BY h.start_time, h.id"
)


def energy_shift(db: TenantDB, machine_name: str, day: date, shift: str = "A") -> MetricResult:
    metric = "energy_kwh_shift"
    params = {"machine": machine_name, "day": day.isoformat(), "shift": shift}
    as_of = db.latest_minute() or ""

    hits = [m for m in db.machines() if m["name"].lower() == machine_name.strip().lower()]
    if len(hits) != 1:
        return MetricResult(
            status="insufficient_data", metric=metric, params=params, as_of=as_of,
            display=f"No machine with name '{machine_name}' exists for this tenant.",
            caveats=["Machine names are resolved only inside the current tenant."],
            needed_data="A valid machine name for this tenant.",
        ).seal()
    machine = hits[0]
    mach_id = machine["machine_id"]

    meters = [m for m in db.energy_meters() if m["machine_id"] == mach_id]
    if len(meters) != 1:
        return MetricResult(
            status="insufficient_data", metric=metric, params=params, as_of=as_of,
            display=f"No energy meter associated with machine '{machine_name}'.",
            caveats=["Energy requires a mapped meter in energy_meters."],
            needed_data="An energy meter mapping for this machine.",
        ).seal()
    meter = meters[0]
    meter_id = meter["meter_id"]

    cur = db._con.cursor()
    cur.execute("SELECT MAX(counter_end - counter_start) FROM energy_hourly WHERE meter_id = ?", (meter_id,))
    row_max = cur.fetchone()
    max_slot_delta = (row_max[0] if row_max and row_max[0] is not None else 50.0)

    if shift == "A":
        shift_start = datetime(day.year, day.month, day.day, 7, 30, 0)
    elif shift == "B":
        shift_start = datetime(day.year, day.month, day.day, 19, 30, 0)
    else:
        raise ValueError(f"Unknown shift {shift!r}")
    shift_end = shift_start + timedelta(hours=12)

    expected_slots = []
    for i in range(12):
        s = shift_start + timedelta(hours=i, seconds=1)
        e = shift_start + timedelta(hours=i + 1)
        expected_slots.append((fmt_ts(s), fmt_ts(e)))

    buf_start = fmt_ts(shift_start - timedelta(hours=2))
    buf_end = fmt_ts(shift_end + timedelta(hours=2))
    rows = db.energy_rows(mach_id, buf_start, buf_end)

    rows_by_start = {r["start_time"]: r for r in rows}
    rows_by_end = {r["end_time"]: r for r in rows}

    observed_slots = []
    missing_slots = []
    for s_txt, e_txt in expected_slots:
        if s_txt in rows_by_start:
            observed_slots.append(rows_by_start[s_txt])
        else:
            missing_slots.append((s_txt, e_txt))

    caveats = [
        "Energy shift window corresponds to platform energy slot labels (07:30:01-19:30:00 for Shift A).",
        "Energy is calculated from physical meter registers (counter_start/counter_end); kwh column is ~2.5% below register delta (unexplained platform bias).",
    ]

    start_reg = None
    first_slot_start, first_slot_end = expected_slots[0]
    if first_slot_start in rows_by_start:
        start_reg = rows_by_start[first_slot_start]["counter_start"]
    else:
        pred_end = fmt_ts(shift_start)
        if pred_end in rows_by_end:
            pred_row = rows_by_end[pred_end]
            start_reg = pred_row["counter_end"]
            caveats.append(f"Shift start slot was missing; register boundary was proven continuous from preceding slot ending at {pred_end}.")
        else:
            caveats.append("Shift start boundary register cannot be verified; preceding slot missing.")

    end_reg = None
    last_slot_start, last_slot_end = expected_slots[-1]
    if last_slot_start in rows_by_start:
        end_reg = rows_by_start[last_slot_start]["counter_end"]
    else:
        succ_start = fmt_ts(shift_end + timedelta(seconds=1))
        if succ_start in rows_by_start:
            succ_row = rows_by_start[succ_start]
            end_reg = succ_row["counter_start"]
            caveats.append(f"Shift end slot was missing; register boundary was proven continuous from succeeding slot starting at {succ_start}.")
        else:
            caveats.append("Shift end boundary register cannot be verified; succeeding slot missing.")

    can_reconcile = (start_reg is not None and end_reg is not None and end_reg >= start_reg)
    unbridgeable_reasons = []

    relevant_rows = sorted(
        [r for r in rows if (r["start_time"] >= fmt_ts(shift_start) and r["end_time"] <= fmt_ts(shift_end + timedelta(hours=1)))
         or r["end_time"] == fmt_ts(shift_start)],
        key=lambda x: x["start_time"],
    )

    for i in range(len(relevant_rows) - 1):
        curr = relevant_rows[i]
        nxt = relevant_rows[i + 1]
        t_curr_end = parse_ts(curr["end_time"])
        t_nxt_start = parse_ts(nxt["start_time"])
        gap_sec = (t_nxt_start - t_curr_end).total_seconds()
        reg_jump = nxt["counter_start"] - curr["counter_end"]

        if reg_jump < 0:
            can_reconcile = False
            unbridgeable_reasons.append(f"Register decreased between {curr['end_time']} and {nxt['start_time']}.")
            break

        if gap_sec > 1:
            missing_hours = round((gap_sec - 1) / 3600)
            max_allowed_jump = missing_hours * max_slot_delta * 1.05
            if reg_jump > max_allowed_jump:
                can_reconcile = False
                unbridgeable_reasons.append(f"Register jump of {reg_jump:.2f} kWh exceeds physical threshold.")
                break
            else:
                caveats.append(f"Bridged missing slot ({missing_hours}h) between {curr['end_time']} and {nxt['start_time']} (register jump {reg_jump:.2f} kWh <= physical threshold).")

    needed_data = ""
    if not can_reconcile:
        status = "incomplete"
        value = "incomplete"
        display = f"incomplete: Energy cannot be determined exactly for {machine_name} in Shift {shift}."
        needed_data = "; ".join(unbridgeable_reasons) or "Missing boundary meter register reading that could not be proven from adjacent slots."
    else:
        status = "ok"
        value = round(end_reg - start_reg, 1)
        display = f"{value:.1f} kWh used by {machine_name}'s meter in Shift {shift}"

    obs_kwh = sum(r["kwh"] for r in observed_slots)
    sensitivity = [
        {"name": "observed_rows_kwh_sum", "value": round(obs_kwh, 2), "note": "sum of kwh column for observed slots only (biased low by ~2.5% and missing slots omitted)"},
        {"name": "observed_slots_count", "value": len(observed_slots), "note": "number of 1-hour slots observed out of 12 expected"},
    ]
    if missing_slots:
        sensitivity.append({
            "name": "strict_unbridged_alternative",
            "value": "incomplete",
            "note": "result if any missing slot inside or at the boundary of Shift A is treated as incomplete",
        })

    return MetricResult(
        status=status,
        value=value,
        display=display,
        metric=metric,
        sql=SQL_USED,
        logic="verify register continuity across shift slots and adjacent boundary readings -> reconcile total register delta",
        params=params,
        rows_used=len(observed_slots),
        as_of=as_of,
        coverage=Coverage(
            expected=12,
            observed=len(observed_slots),
            missing_ranges=[f"{s}..{e}" for s, e in missing_slots],
        ),
        caveats=caveats,
        sensitivity=sensitivity,
        needed_data=needed_data,
    ).seal()
