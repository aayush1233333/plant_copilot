from datetime import date, datetime

from plant_copilot.production import q5_total_pieces, sum_pieces
from plant_copilot.tenant import TenantDB, resolve_tenant

DB = "data/factory.db"
KALPA_NAMES = {"Press 1", "Press 2", "Press 3", "Press 4", "Bender 1", "Bender 2", "Moulder 1", "Moulder 2"}
T0 = datetime(2026, 11, 3, 8, 0)


def kalpa():
    return TenantDB(resolve_tenant(DB, "Kalpa Appliances"))


def row(minute, pieces):
    return {"minute_start": minute, "planned": 1, "running": 1, "pieces": pieces}


def test_q5_plant_day_31_oct():
    r = q5_total_pieces(kalpa(), date(2026, 10, 31))
    assert r.status == "ok"
    assert r.value == 54123
    assert r.coverage.expected == 11520 and r.coverage.observed == 11497
    assert len(r.coverage.missing_ranges) == 23
    assert r.as_of == "2026-11-07 14:36:00"


def test_q5_details_add_up_and_stay_in_tenant():
    r = q5_total_pieces(kalpa(), date(2026, 10, 31))
    assert sum(d["pieces"] for d in r.details) == r.value
    assert {d["machine"] for d in r.details} == KALPA_NAMES


def test_exact_duplicates_count_once():
    rows = [row("2026-11-03 08:00:00", 5), row("2026-11-03 08:00:00", 5)]
    assert sum_pieces(rows, T0, datetime(2026, 11, 3, 8, 1)) == (5, [])


def test_conflicting_duplicates_are_missing_not_summed():
    rows = [row("2026-11-03 08:00:00", 5), row("2026-11-03 08:00:00", 7)]
    assert sum_pieces(rows, T0, datetime(2026, 11, 3, 8, 1)) == (0, ["2026-11-03 08:00:00"])


def test_missing_minute_is_not_zero_pieces():
    rows = [row("2026-11-03 08:00:00", 4), row("2026-11-03 08:02:00", 6)]
    assert sum_pieces(rows, T0, datetime(2026, 11, 3, 8, 3)) == (10, ["2026-11-03 08:01:00"])


def test_upper_bound_is_not_below_the_value():
    r = q5_total_pieces(kalpa(), date(2026, 10, 31))
    upper = next(s["value"] for s in r.sensitivity if s["name"].startswith("upper_bound"))
    assert upper >= r.value


def test_unfinished_plant_day_is_incomplete():
    r = q5_total_pieces(kalpa(), date(2026, 11, 7))
    assert r.status == "incomplete"
