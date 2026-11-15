import tempfile
from datetime import date

from plant_copilot.agent import ALLOWED_TOOLS, AgentDecision, validate_decision
from plant_copilot.operations import explain_machine_downtime
from plant_copilot.tenant import TenantDB, resolve_tenant
from plant_copilot.workflow import GroundingValidator, WorkflowEngine

DAY = date(2026, 11, 6)


def kalpa():
    return TenantDB(resolve_tenant("data/factory.db", "Kalpa Appliances"))


def sens(res, name):
    return next(s["value"] for s in res.sensitivity if s["name"] == name)


def test_winner_is_explained_with_its_own_reasons_not_the_plants():
    res = explain_machine_downtime(kalpa(), DAY)
    assert res.status == "ok"
    assert res.value["machine"] == "Press 1"
    ranking = {r["reason"]: r["minutes"] for r in sens(res, "winner_reasons_ranking")}
    assert ranking["Tool Change"] == 54 and ranking["Breakdown"] == 54
    assert res.value["top_reasons"] == ["Breakdown", "Tool Change"]
    assert "428" not in res.display and "370" not in res.display


def test_data_issue_is_excluded_from_reasons():
    res = explain_machine_downtime(kalpa(), DAY)
    assert "Data Issue" not in {r["reason"] for r in sens(res, "winner_reasons_ranking")}
    assert sens(res, "winner_data_issue_minutes_entered") > 0


def test_display_numbers_are_grounded_in_the_envelope():
    res = explain_machine_downtime(kalpa(), DAY)
    assert GroundingValidator.validate(res.display, res)


def test_same_inputs_same_hash():
    assert explain_machine_downtime(kalpa(), DAY).result_hash == explain_machine_downtime(kalpa(), DAY).result_hash


def test_other_tenant_gets_its_own_machine():
    orbit = TenantDB(resolve_tenant("data/factory.db", "Orbit Motors"))
    res = explain_machine_downtime(orbit, DAY)
    assert res.value["machine"] in {m["name"] for m in orbit.machines()}
    assert res.value["machine"] not in {m["name"] for m in kalpa().machines()}


def test_tool_is_allowed_and_requires_a_day():
    assert "explain_machine_downtime" in ALLOWED_TOOLS
    assert validate_decision(AgentDecision(action="CALL_TOOL", tool_name="explain_machine_downtime")) is not None
    assert validate_decision(AgentDecision(action="CALL_TOOL", tool_name="explain_machine_downtime", day="2026-11-06")) is None


class FakeAgent:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    def next_step(self, **kwargs):
        return self.decisions.pop(0), {"prompt_tokens": 1, "output_tokens": 1, "total_tokens": 2}

    def compose_multi_tool_answer(self, question, digests):
        raise AssertionError("a single tool must not need a phrasing call")


def test_workflow_answers_the_brief_example_with_one_tool_and_no_phrasing_call():
    engine = WorkflowEngine(checkpoint_dir=tempfile.mkdtemp(), agent=FakeAgent([
        AgentDecision(action="CALL_TOOL", tool_name="explain_machine_downtime", day="2026-11-06"),
        AgentDecision(action="FINISH"),
    ]))
    res = engine.run("Which machine lost the most time yesterday, and why?", "Kalpa Appliances")
    assert res["status"] == "ok"
    assert "Press 1" in res["answer"] and "tied" in res["answer"]
