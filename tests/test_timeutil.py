import sqlite3
from datetime import date, datetime
from pathlib import Path

from plant_copilot.timeutil import (
    parse_ts, plant_day_bounds, plant_day_of, shift_bounds, shift_of,
)

DB = "data/factory.db"


def test_boundaries_at_0800_and_2000():
    assert shift_of(datetime(2026, 11, 4, 7, 59)) == "B"
    assert shift_of(datetime(2026, 11, 4, 8, 0)) == "A"
    assert shift_of(datetime(2026, 11, 4, 19, 59)) == "A"
    assert shift_of(datetime(2026, 11, 4, 20, 0)) == "B"
    assert plant_day_of(datetime(2026, 11, 4, 7, 59)) == date(2026, 11, 3)
    assert plant_day_of(datetime(2026, 11, 4, 8, 0)) == date(2026, 11, 4)


def test_midnight_belongs_to_previous_plant_day_shift_b():
    t = datetime(2026, 11, 4, 0, 0)
    assert shift_of(t) == "B"
    assert plant_day_of(t) == date(2026, 11, 3)


def test_plant_day_and_shift_bounds():
    d = date(2026, 11, 3)
    assert plant_day_bounds(d) == (datetime(2026, 11, 3, 8), datetime(2026, 11, 4, 8))
    assert shift_bounds(d, "A") == (datetime(2026, 11, 3, 8), datetime(2026, 11, 3, 20))
    assert shift_bounds(d, "B") == (datetime(2026, 11, 3, 20), datetime(2026, 11, 4, 8))


def test_shifts_tile_the_plant_day_exactly():
    d = date(2026, 11, 3)
    day_start, day_end = plant_day_bounds(d)
    a_start, a_end = shift_bounds(d, "A")
    b_start, b_end = shift_bounds(d, "B")
    assert a_start == day_start
    assert a_end == b_start
    assert b_end == day_end


def test_derived_shift_and_plant_day_match_stored_labels_for_every_row():
    # Test-only raw read-only connection: production code goes through TenantDB.
    uri = Path(DB).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    rows = con.execute("SELECT minute_start, shift, shift_date FROM machine_minutes").fetchall()
    con.close()
    assert len(rows) == 211708
    bad = [
        r for r in rows
        if shift_of(parse_ts(r[0])) != r[1] or plant_day_of(parse_ts(r[0])).isoformat() != r[2]
    ]
    assert bad == []
