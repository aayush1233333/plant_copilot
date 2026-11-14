from datetime import date

from plant_copilot.operations import (
    q6_top_stop_reason,
    q7_stop_cost_rupees,
    q8_late_stop_entries,
    q9_rejections,
    q10_running_now,
)
from plant_copilot.tenant import TenantDB, resolve_tenant

DB = "data/factory.db"


def kalpa():
    return TenantDB(resolve_tenant(DB, "Kalpa Appliances"))


def test_q6_top_stop_reason():
    r = q6_top_stop_reason(kalpa())
    assert r.status == "ok"
    assert r.value == "Breakdown"


def test_q7_cost_returns_null_and_explains_missing_data():
    r = q7_stop_cost_rupees(kalpa(), date(2026, 11, 3))
    assert r.status == "insufficient_data"
    assert r.value is None
    assert "no cost" in r.display.lower()
    assert r.needed_data != ""


def test_q8_late_entries_count():
    r = q8_late_stop_entries(kalpa())
    assert r.status == "ok"
    assert r.value == 44


def test_q9_rejections_2_nov():
    r = q9_rejections(kalpa(), "2026-11-02")
    assert r.status == "ok"
    assert r.value == 124


def test_q10_running_machines_now():
    r = q10_running_now(kalpa())
    assert r.status == "ok"
    assert r.value == ["Press 2", "Bender 1", "Moulder 2"]
    assert r.as_of == "2026-11-07 14:36:00"

from plant_copilot.operations import rank_machine_downtime


def test_q6_machine_filter_and_dynamic_q9():
    r_empty = q6_top_stop_reason(kalpa(), "2026-11-06", "2026-11-06", machine_name="NonExistent")
    assert r_empty.status == "insufficient_data"

    r_m = q6_top_stop_reason(kalpa(), "2026-11-01", "2026-11-07", machine_name="Press 2")
    assert r_m.status == "ok"
    assert r_m.params["machine"] == "Press 2"

    r9 = q9_rejections(kalpa(), "2026-11-03")
    assert r9.status == "ok"
    assert "2026-11-03" in " ".join(r9.caveats)


def test_rank_machine_downtime_yesterday():
    r = rank_machine_downtime(kalpa(), date(2026, 11, 6))
    assert r.status == "ok"
    assert r.value is not None
    assert len(r.details) == 8
    assert r.details[0]["corrected_stopped_minutes"] >= r.details[1]["corrected_stopped_minutes"]
