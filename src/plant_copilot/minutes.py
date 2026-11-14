from datetime import datetime, timedelta

from plant_copilot.timeutil import fmt_ts

RUNNING = "RUNNING"
STOPPED_PLANNED = "STOPPED_PLANNED"
NOT_PLANNED = "NOT_PLANNED"
UNKNOWN = "UNKNOWN"


def _state_of(planned, running) -> str:
    if planned == 1 and running == 1:
        return RUNNING
    if planned == 1 and running == 0:
        return STOPPED_PLANNED
    if planned == 0 and running == 0:
        return NOT_PLANNED
    return UNKNOWN  # NULLs or an inconsistent combination (e.g. running while not planned)


def classify_minutes(rows, start: datetime, end: datetime) -> list[tuple[str, str]]:
    """One (minute_text, state) pair for every minute in [start, end).

    - No row for a minute -> UNKNOWN (never assumed stopped).
    - Several identical rows -> collapsed to one.
    - Several conflicting rows -> UNKNOWN.
    """
    variants_by_minute = {}
    for r in rows:
        variant = (r["planned"], r["running"], r["pieces"])
        variants_by_minute.setdefault(r["minute_start"], set()).add(variant)

    grid = []
    t = start
    while t < end:
        text = fmt_ts(t)
        variants = variants_by_minute.get(text)
        if not variants or len(variants) > 1:
            state = UNKNOWN
        else:
            planned, running, _pieces = next(iter(variants))
            state = _state_of(planned, running)
        grid.append((text, state))
        t += timedelta(minutes=1)
    return grid
