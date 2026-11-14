from datetime import date

from plant_copilot.envelope import Coverage, MetricResult
from plant_copilot.minutes import STOPPED_PLANNED, UNKNOWN, classify_minutes
from plant_copilot.runs import find_runs
from plant_copilot.timeutil import fmt_ts, plant_day_bounds, shift_bounds

MIN_STOP_MINUTES = 30
DATA_ISSUE = "Data Issue"
UNCHANGED, ELIMINATED, AMBIGUOUS = "UNCHANGED", "ELIMINATED", "AMBIGUOUS"

SQL_USED = (
    "SELECT minute_start, planned, running, pieces FROM machine_minutes "
    "WHERE company_id = :tenant AND machine_id = :machine AND minute_start >= :start AND minute_start < :end "
    "ORDER BY minute_start, id;\n"
    "SELECT DISTINCT reason_date || ' ' || hour_start AS hour_ts, reason, minutes, remark, entered_by, created_at "
    "FROM stop_reasons WHERE company_id = :tenant AND machine_id = :machine AND deleted_at = '0000-00-00 00:00:00' "
    "AND reason_date || ' ' || hour_start >= :start AND reason_date || ' ' || hour_start < :end"
)


def classify_long_run(minutes, hour_counts, hours):
    """D4 rule. hour_counts: {hour_index: run minutes inside that hour}.
    hours[h]: {"stopped", "unknown", "di"} for that hour."""
    if sum(hours[h]["di"] for h in hour_counts) == 0:
        return UNCHANGED
    min_removed = 0
    for h, in_run in hour_counts.items():
        hh = hours[h]
        if hh["di"] > hh["stopped"] + hh["unknown"]:
            return AMBIGUOUS  # Data Issue minutes cannot all fit inside stopped/unknown minutes
        elsewhere = hh["stopped"] - in_run + hh["unknown"]
        min_removed += max(0, hh["di"] - elsewhere)
    return ELIMINATED if minutes - min_removed < MIN_STOP_MINUTES else AMBIGUOUS


def _run_hour_counts(idx, run):
    i0, i1 = idx[run["start"]], idx[run["last_minute"]]
    counts = {}
    for i in range(i0, i1 + 1):
        counts[i // 60] = counts.get(i // 60, 0) + 1
    return counts


def _unknown_ranges(grid, lo=None, hi=None):
    out, start, prev = [], None, None
    for text, state in grid:
        if lo is not None and not (lo <= text < hi):
            continue
        if state == UNKNOWN:
            if start is None:
                start = text
            prev = text
        elif start is not None:
            out.append(start + ".." + prev)
            start = None
    if start is not None:
        out.append(start + ".." + prev)
    return out


def _load(db, machine_name, day):
    hits = [m for m in db.machines() if m["name"].lower() == machine_name.strip().lower()]
    if len(hits) != 1:
        return None
    machine = hits[0]
    start, end = plant_day_bounds(day)
    s, e = fmt_ts(start), fmt_ts(end)
    rows = db.minute_rows(machine["machine_id"], s, e)
    entries = db.stop_entries(machine["machine_id"], s, e)
    grid = classify_minutes(rows, start, end)
    di = {}
    for en in entries:
        if en["reason"] == DATA_ISSUE:
            di[en["hour_ts"]] = di.get(en["hour_ts"], 0) + en["minutes"]
    hours = []
    for i in range(24):
        block = grid[i * 60:(i + 1) * 60]
        hours.append({
            "hour": block[0][0],
            "stopped": sum(1 for _t, st in block if st == STOPPED_PLANNED),
            "unknown": sum(1 for _t, st in block if st == UNKNOWN),
            "di": di.get(block[0][0], 0),
        })
    return {
        "machine": machine, "start": s, "end": e, "rows": rows, "entries": entries,
        "grid": grid, "hours": hours, "runs": find_runs(grid),
        "idx": {t: i for i, (t, _st) in enumerate(grid)},
    }


def _machine_not_found(metric, params, db):
    return MetricResult(
        status="insufficient_data", metric=metric, params=params, as_of=db.latest_minute() or "",
        display="No machine with that name exists for this tenant.",
        caveats=["Machine names are resolved only inside the current tenant."],
        needed_data="A machine name that exists for this tenant.",
    ).seal()


def q1_long_stops(db, machine_name: str, day: date) -> MetricResult:
    metric = "q1_long_stops_plant_day"
    params = {"machine": machine_name, "plant_day": day.isoformat(), "min_stop_minutes": MIN_STOP_MINUTES}
    d = _load(db, machine_name, day)
    if d is None:
        return _machine_not_found(metric, params, db)

    grid, hours, idx = d["grid"], d["hours"], d["idx"]
    long_runs = [r for r in d["runs"] if r["minutes"] >= MIN_STOP_MINUTES]
    counts = {UNCHANGED: 0, ELIMINATED: 0, AMBIGUOUS: 0}
    details = []
    for r in long_runs:
        verdict = classify_long_run(r["minutes"], _run_hour_counts(idx, r), hours)
        counts[verdict] += 1
        details.append({
            "start": r["start"], "last_minute": r["last_minute"], "minutes": r["minutes"],
            "before": r["before"], "after": r["after"], "verdict": verdict,
        })

    low = counts[UNCHANGED]
    high = low + counts[AMBIGUOUS]
    raw = len(long_runs)
    upper_grid = [(t, STOPPED_PLANNED if s == UNKNOWN else s) for t, s in grid]
    upper = len([r for r in find_runs(upper_grid) if r["minutes"] >= MIN_STOP_MINUTES])

    di_entries = [e for e in d["entries"] if e["reason"] == DATA_ISSUE]
    caveats = [
        "Plant day = 08:00 to 08:00 next morning. A stop crossing 20:00 or midnight counts once.",
        "A stop is a run of consecutive planned minutes with running = 0. A missing minute (no data) ends a run.",
        "Data Issue correction uses live, de-duplicated operator entries. Entries give minutes per hour, not which minutes, "
        "so a stop is only removed when the entries provably leave it shorter than 30 minutes.",
        "Calendar-day reading of the question would give a different count (owner question).",
    ]
    if di_entries:
        caveats.append(
            "Data Issue entries used: " + str(len(di_entries)) + ", last created at "
            + max(e["created_at"] for e in di_entries)
            + ". The answer is valid as of the snapshot only."
        )
    if any(r["touches_window_start"] or r["touches_window_end"] for r in long_runs):
        caveats.append("At least one long stop touches the edge of the plant day; its true length may extend beyond it.")

    if counts[AMBIGUOUS] == 0:
        status, value = "ok", low
        display = str(low) + " stops of 30+ minutes (Data Issue corrected); raw system state: " + str(raw)
    else:
        status, value = "ambiguous", None
        display = "Between " + str(low) + " and " + str(high) + " stops of 30+ minutes (Data Issue placement unresolved)"

    unknown = _unknown_ranges(grid)
    return MetricResult(
        status=status, value=value, display=display, metric=metric, sql=SQL_USED,
        logic="classify minutes -> runs of STOPPED_PLANNED -> keep runs >= 30 -> apply D4 rule (UNCHANGED/ELIMINATED/AMBIGUOUS)",
        params=params, rows_used=len(d["rows"]) + len(d["entries"]), as_of=db.latest_minute() or "",
        coverage=Coverage(expected=1440, observed=1440 - sum(h["unknown"] for h in hours), missing_ranges=unknown),
        caveats=caveats,
        sensitivity=[
            {"name": "raw_system_state", "value": raw, "note": "Data Issue not applied"},
            {"name": "raw_with_unknown_as_stopped", "value": upper, "note": "raw count (Data Issue NOT applied) if every missing minute were a planned stop"},
            {"name": "corrected_range", "value": [low, high], "note": "unchanged .. unchanged + ambiguous"},
        ],
        details=details,
    ).seal()


def q2_standstill_shift(db, machine_name: str, day: date, shift: str = "A") -> MetricResult:
    metric = "q2_planned_standstill_minutes_shift"
    params = {"machine": machine_name, "plant_day": day.isoformat(), "shift": shift}
    d = _load(db, machine_name, day)
    if d is None:
        return _machine_not_found(metric, params, db)

    lo, hi = shift_bounds(day, shift)
    lo, hi = fmt_ts(lo), fmt_ts(hi)
    in_shift = [h for h in d["hours"] if lo <= h["hour"] < hi]
    stopped = sum(h["stopped"] for h in in_shift)
    unknown = sum(h["unknown"] for h in in_shift)
    di_hours = [h for h in in_shift if h["di"] > 0]
    ambiguous = any(h["di"] > h["stopped"] + h["unknown"] or h["unknown"] > 0 for h in di_hours)
    removed = sum(min(h["di"], h["stopped"]) for h in di_hours)
    corrected = stopped - removed

    caveats = [
        "Counts minutes with planned = 1 and running = 0 inside the shift window (08:00-20:00 for A, 20:00-08:00 for B).",
        "Minutes with no data are not counted as stopped.",
    ]
    if unknown:
        caveats.append(str(unknown) + " minute(s) in this shift had no data; the true count may be higher by up to that many.")
    if di_hours:
        caveats.append("Data Issue minutes entered by operators were treated as running and removed.")

    if ambiguous:
        status, value, display = "ambiguous", None, "Data Issue minutes could not be placed exactly."
    else:
        status, value = "ok", corrected
        display = str(corrected) + " planned minutes stopped in shift " + shift
        if unknown:
            display += " (" + str(unknown) + " minute with no data)"

    return MetricResult(
        status=status, value=value, display=display, metric=metric, sql=SQL_USED,
        logic="classify minutes -> count STOPPED_PLANNED inside the shift window -> subtract operator-entered Data Issue minutes per hour",
        params=params, rows_used=len(in_shift) * 60 - unknown, as_of=db.latest_minute() or "",
        coverage=Coverage(expected=len(in_shift) * 60, observed=len(in_shift) * 60 - unknown,
                          missing_ranges=_unknown_ranges(d["grid"], lo, hi)),
        caveats=caveats,
        sensitivity=[
            {"name": "raw_system_state", "value": stopped, "note": "Data Issue not applied"},
            {"name": "unknown_minutes_counted_as_stopped", "value": corrected + unknown, "note": "upper bound"},
        ],
    ).seal()

