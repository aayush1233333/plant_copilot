from plant_copilot.south_adapter import SouthPlantAdapter

DB = "data/south_sample.db"


def test_south_adapter_running_now():
    adapter = SouthPlantAdapter(DB)
    try:
        r = adapter.running_now()
        assert r.status == "ok"
        assert isinstance(r.value, list)
        assert r.as_of == "2026-11-07 07:55:00"
    finally:
        adapter.close()


def test_south_adapter_reports_unsupported_planned_time():
    adapter = SouthPlantAdapter(DB)
    try:
        r = adapter.unsupported("q1_long_stops_during_planned_time", "No planned schedule or shift table exists in South schema.")
        assert r.status == "insufficient_data"
        assert r.value is None
        assert "unsupported" in r.display
    finally:
        adapter.close()


def test_south_capabilities_flags():
    adapter = SouthPlantAdapter(DB)
    assert adapter.CAPABILITIES.running_now is True
    assert adapter.CAPABILITIES.planned_time is False
    assert adapter.CAPABILITIES.late_entries is False
    adapter.close()
