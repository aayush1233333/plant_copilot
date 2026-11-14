from plant_copilot.tenant import TenantDB, resolve_tenant

DB = "data/factory.db"
START = "2026-11-03 08:00:00"
END = "2026-11-04 08:00:00"


def kalpa():
    return TenantDB(resolve_tenant(DB, "Kalpa Appliances"))


def test_press2_stop_entries_and_data_issue_for_the_plant_day():
    entries = kalpa().stop_entries(102, START, END)
    assert len(entries) == 27
    di = [(e["hour_ts"], e["minutes"]) for e in entries if e["reason"] == "Data Issue"]
    assert di == [("2026-11-04 01:00:00", 51), ("2026-11-04 02:00:00", 45)]


def test_kalpa_cannot_read_orbit_stop_entries():
    assert kalpa().stop_entries(204, "2026-10-26 00:00:00", "2026-11-08 00:00:00") == []


def test_deleted_twin_is_excluded():
    # ids 752 (deleted) and 2148 (live) describe the same entry: exactly one must remain.
    entries = kalpa().stop_entries(101, "2026-10-28 02:00:00", "2026-10-28 03:00:00")
    assert len([e for e in entries if e["reason"] == "Die Cleaning" and e["minutes"] == 3]) == 1


def test_exact_live_duplicates_collapse():
    # ids 173 and 1691 are identical live rows: exactly one must remain.
    entries = kalpa().stop_entries(101, "2026-11-07 05:00:00", "2026-11-07 06:00:00")
    assert len([e for e in entries if e["reason"] == "Breakdown" and e["minutes"] == 43]) == 1
