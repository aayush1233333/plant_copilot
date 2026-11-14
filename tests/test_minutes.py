from datetime import datetime

from plant_copilot.minutes import (
    NOT_PLANNED, RUNNING, STOPPED_PLANNED, UNKNOWN, classify_minutes,
)
from plant_copilot.tenant import TenantDB, resolve_tenant

DB = "data/factory.db"
T0 = datetime(2026, 11, 3, 8, 0)


def row(minute, planned, running, pieces=0):
    return {"minute_start": minute, "planned": planned, "running": running, "pieces": pieces}


def states(rows, minutes=3):
    end = datetime(2026, 11, 3, 8, minutes)
    return [s for _, s in classify_minutes(rows, T0, end)]


def test_each_state_is_classified():
    rows = [
        row("2026-11-03 08:00:00", 1, 1, 5),
        row("2026-11-03 08:01:00", 1, 0),
        row("2026-11-03 08:02:00", 0, 0),
    ]
    assert states(rows) == [RUNNING, STOPPED_PLANNED, NOT_PLANNED]


def test_missing_minute_is_unknown_not_stopped():
    rows = [row("2026-11-03 08:00:00", 1, 0), row("2026-11-03 08:02:00", 1, 0)]
    assert states(rows) == [STOPPED_PLANNED, UNKNOWN, STOPPED_PLANNED]


def test_exact_duplicates_collapse_to_one():
    rows = [row("2026-11-03 08:00:00", 1, 1, 4), row("2026-11-03 08:00:00", 1, 1, 4)]
    assert states(rows, minutes=1) == [RUNNING]


def test_conflicting_duplicates_are_unknown():
    rows = [row("2026-11-03 08:00:00", 1, 1, 4), row("2026-11-03 08:00:00", 1, 0, 0)]
    assert states(rows, minutes=1) == [UNKNOWN]


def test_inconsistent_row_is_unknown():
    rows = [row("2026-11-03 08:00:00", 0, 1, 3)]
    assert states(rows, minutes=1) == [UNKNOWN]


def test_grid_length_equals_window_length():
    grid = classify_minutes([], datetime(2026, 11, 3, 8, 0), datetime(2026, 11, 3, 20, 0))
    assert len(grid) == 720
    assert all(s == UNKNOWN for _, s in grid)


def test_kalpa_cannot_read_orbit_machine_minutes():
    kalpa = TenantDB(resolve_tenant(DB, "Kalpa Appliances"))
    assert kalpa.minute_rows(201, "2026-10-26 08:00:00", "2026-11-08 00:00:00") == []
