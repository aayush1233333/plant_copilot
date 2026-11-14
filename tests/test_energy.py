from datetime import date

from plant_copilot.energy import energy_shift
from plant_copilot.tenant import TenantDB, resolve_tenant

DB = "data/factory.db"


def kalpa():
    return TenantDB(resolve_tenant(DB, "Kalpa Appliances"))


def test_q3_press2_energy_shift_a_4_nov():
    r = energy_shift(kalpa(), "Press 2", date(2026, 11, 4), "A")
    assert r.status == "ok"
    assert r.value == 229.3
    assert r.coverage.expected == 12
    assert r.coverage.observed == 11
    assert "2026-11-04 12:30:01..2026-11-04 13:30:00" in r.coverage.missing_ranges[0]


def test_q4_press3_energy_shift_a_5_nov():
    r = energy_shift(kalpa(), "Press 3", date(2026, 11, 5), "A")
    assert r.status == "ok"
    assert r.value == 140.7
    assert r.coverage.expected == 12
    assert r.coverage.observed == 11
    assert "2026-11-05 07:30:01..2026-11-05 08:30:00" in r.coverage.missing_ranges[0]


def test_energy_unknown_machine_returns_insufficient_data():
    r = energy_shift(kalpa(), "Nonexistent Press", date(2026, 11, 4), "A")
    assert r.status == "insufficient_data"


def test_energy_other_tenant_machine_not_found():
    # Final Press is Orbit Motors (machine_id 204)
    r = energy_shift(kalpa(), "Final Press", date(2026, 11, 4), "A")
    assert r.status == "insufficient_data"
