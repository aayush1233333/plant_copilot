from datetime import date

from plant_copilot.envelope import MetricResult
from plant_copilot.stoppage import (
    AMBIGUOUS, ELIMINATED, UNCHANGED, classify_long_run, q1_long_stops, q2_standstill_shift,
)
from plant_copilot.tenant import TenantDB, resolve_tenant

DB = "data/factory.db"
DAY = date(2026, 11, 3)


def kalpa():
    return TenantDB(resolve_tenant(DB, "Kalpa Appliances"))


def sens(result, name):
    return next(s["value"] for s in result.sensitivity if s["name"] == name)


def test_no_data_issue_is_unchanged():
    hours = {1: {"stopped": 40, "unknown": 0, "di": 0}}
    assert classify_long_run(40, {1: 40}, hours) == UNCHANGED


def test_data_issue_forced_inside_run_is_eliminated():
    hours = {1: {"stopped": 52, "unknown": 0, "di": 51}, 2: {"stopped": 50, "unknown": 0, "di": 45}}
    assert classify_long_run(102, {1: 52, 2: 50}, hours) == ELIMINATED


def test_data_issue_that_could_be_elsewhere_is_ambiguous():
    hours = {1: {"stopped": 60, "unknown": 0, "di": 10}}
    assert classify_long_run(40, {1: 40}, hours) == AMBIGUOUS


def test_data_issue_larger_than_stopped_minutes_is_ambiguous():
    hours = {1: {"stopped": 60, "unknown": 0, "di": 70}}
    assert classify_long_run(60, {1: 60}, hours) == AMBIGUOUS


def test_q1_press2_corrected_and_raw():
    r = q1_long_stops(kalpa(), "Press 2", DAY)
    assert r.status == "ok"
    assert r.value == 6
    assert sens(r, "raw_system_state") == 7
    assert r.as_of == "2026-11-07 14:36:00"
    assert sum(1 for x in r.details if x["verdict"] == ELIMINATED) == 1


def test_q2_press2_shift_a():
    r = q2_standstill_shift(kalpa(), "Press 2", DAY, "A")
    assert r.status == "ok"
    assert r.value == 299
    assert sens(r, "unknown_minutes_counted_as_stopped") == 300
    assert r.coverage.expected == 720 and r.coverage.observed == 719


def test_hash_is_stable_and_changes_with_params():
    a = q1_long_stops(kalpa(), "Press 2", DAY)
    b = q1_long_stops(kalpa(), "Press 2", DAY)
    c = q1_long_stops(kalpa(), "Press 2", date(2026, 11, 4))
    assert a.result_hash == b.result_hash != ""
    assert a.result_hash != c.result_hash


def test_machine_of_another_tenant_is_not_found():
    r = q1_long_stops(kalpa(), "Line A Robot", DAY)
    assert r.status == "insufficient_data"
    assert r.value is None


def test_envelope_has_all_required_keys():
    keys = set(q1_long_stops(kalpa(), "Press 2", DAY).model_dump().keys())
    required = {"status", "value", "display", "metric", "sql", "params", "rows_used", "as_of",
                "coverage", "caveats", "sensitivity", "needed_data", "result_hash"}
    assert required <= keys
