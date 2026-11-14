from datetime import datetime, timedelta

from plant_copilot.minutes import NOT_PLANNED, RUNNING, STOPPED_PLANNED, UNKNOWN
from plant_copilot.runs import count_state, find_runs
from plant_copilot.timeutil import fmt_ts

MAP = {"R": RUNNING, "S": STOPPED_PLANNED, "N": NOT_PLANNED, "U": UNKNOWN}


def grid(spec, base=datetime(2026, 11, 3, 8, 0)):
    return [(fmt_ts(base + timedelta(minutes=i)), MAP[c]) for i, c in enumerate(spec)]


def long_runs(g, threshold=30):
    return [r for r in find_runs(g) if r["minutes"] >= threshold]


def test_run_of_exactly_30_counts():
    g = grid("R" + "S" * 30 + "R")
    runs = find_runs(g)
    assert len(runs) == 1
    assert runs[0]["minutes"] == 30
    assert runs[0]["before"] == RUNNING and runs[0]["after"] == RUNNING


def test_run_of_29_does_not_count_but_30_does():
    g = grid("R" + "S" * 29 + "R" + "S" * 30 + "R")
    assert [r["minutes"] for r in long_runs(g)] == [30]


def test_unknown_minute_breaks_a_run():
    g = grid("S" * 15 + "U" + "S" * 15)
    assert [r["minutes"] for r in find_runs(g)] == [15, 15]
    assert long_runs(g) == []


def test_not_planned_minute_breaks_a_run():
    g = grid("S" * 15 + "N" + "S" * 15)
    assert [r["minutes"] for r in find_runs(g)] == [15, 15]
    assert long_runs(g) == []


def test_run_crossing_2000_is_one_run():
    g = grid("S" * 20, base=datetime(2026, 11, 3, 19, 50))
    runs = find_runs(g)
    assert len(runs) == 1
    assert runs[0]["start"] == "2026-11-03 19:50:00"
    assert runs[0]["last_minute"] == "2026-11-03 20:09:00"


def test_window_edge_flags():
    g = grid("SSRSS")
    first, last = find_runs(g)
    assert first["touches_window_start"] and not first["touches_window_end"]
    assert last["touches_window_end"] and not last["touches_window_start"]
    assert first["before"] is None and last["after"] is None


def test_count_state_uses_half_open_window():
    g = grid("S" * 60)
    assert count_state(g, STOPPED_PLANNED, "2026-11-03 08:10:00", "2026-11-03 08:30:00") == 20


def test_run_ended_by_unknown_is_labelled():
    g = grid("RSSSU")
    assert find_runs(g)[0]["after"] == UNKNOWN
