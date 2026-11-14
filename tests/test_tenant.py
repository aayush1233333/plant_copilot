import sqlite3

import pytest

from plant_copilot.tenant import TenantDB, resolve_tenant

DB = "data/factory.db"


def test_kalpa_sees_only_kalpa_machines():
    db = TenantDB(resolve_tenant(DB, "Kalpa Appliances"))
    ids = {m["machine_id"] for m in db.machines()}
    assert ids == {101, 102, 103, 104, 111, 112, 121, 122}


def test_orbit_and_kalpa_are_isolated():
    orbit = TenantDB(resolve_tenant(DB, "Orbit Motors"))
    kalpa = TenantDB(resolve_tenant(DB, "Kalpa Appliances"))
    assert {m["machine_id"] for m in orbit.machines()} == {201, 202, 203, 204}
    assert {m["meter_id"] for m in orbit.energy_meters()} == {508, 509, 510, 511}
    assert {m["meter_id"] for m in kalpa.energy_meters()} == set(range(500, 508))


def test_kalpa_cannot_read_orbit_energy():
    kalpa = TenantDB(resolve_tenant(DB, "Kalpa Appliances"))
    # Machine 201 is Orbit's Line A Robot (meter 508)
    rows = kalpa.energy_rows(201, "2026-10-26 00:00:00", "2026-11-08 00:00:00")
    assert rows == []


def test_writes_are_rejected():
    db = TenantDB(resolve_tenant(DB, "Kalpa Appliances"))
    with pytest.raises(sqlite3.OperationalError):
        db._con.execute("INSERT INTO companies VALUES (99, 'Evil')")


@pytest.mark.parametrize("bad_name", ["", "o", "k", "Kalpa", "nonexistent"])
def test_bad_tenant_names_fail(bad_name):
    with pytest.raises(ValueError):
        resolve_tenant(DB, bad_name)


def test_latest_minute_is_the_tenant_watermark():
    kalpa = TenantDB(resolve_tenant(DB, "Kalpa Appliances"))
    assert kalpa.latest_minute() == "2026-11-07 14:36:00"
