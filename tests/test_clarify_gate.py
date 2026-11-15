import tempfile

from plant_copilot.agent import AgentDecision, missing_fields_question
from plant_copilot.workflow import WorkflowEngine

TENANT = "Kalpa Appliances"


def call(tool, **kw):
    return AgentDecision(action="CALL_TOOL", tool_name=tool, **kw)


def test_missing_shift_is_a_question_not_a_default():
    assert missing_fields_question(call("energy_shift", machine="Press 2", day="2026-11-04")) == "Which shift, A or B?"
    assert missing_fields_question(call("q2_standstill_shift", machine="Press 2", day="2026-11-03")) == "Which shift, A or B?"


def test_complete_call_has_no_question():
    assert missing_fields_question(call("energy_shift", machine="Press 2", day="2026-11-04", shift="B")) is None


def test_missing_range_end_and_day_are_asked():
    assert "end date" in missing_fields_question(call("q6_top_stop_reason", start_date="2026-11-01"))
    assert "Which date" in missing_fields_question(call("q5_total_pieces"))


def test_machine_question_lists_only_the_tenants_machines():
    text = missing_fields_question(call("q1_long_stops", day="2026-11-03"), ["Press 1", "Press 2"])
    assert "Which machine?" in text and "Press 1, Press 2" in text


def test_unknown_tool_and_other_actions_are_left_to_the_validator():
    assert missing_fields_question(call("run_sql")) is None
    assert missing_fields_question(AgentDecision(action="FINISH")) is None


class FakeAgent:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    def next_step(self, **kwargs):
        return self.decisions.pop(0), {"prompt_tokens": 1, "output_tokens": 1, "total_tokens": 2}


def run(decisions):
    engine = WorkflowEngine(checkpoint_dir=tempfile.mkdtemp(), agent=FakeAgent(decisions))
    return engine.run("How much energy did Press 2 use on 4 Nov?", TENANT)


def test_workflow_asks_for_the_shift_and_computes_nothing():
    res = run([call("energy_shift", machine="Press 2", day="2026-11-04")])
    assert res["status"] == "clarify"
    assert res["answer"] == "Which shift, A or B?"
    assert res["checkpoint"].status == "CLARIFY"
    assert res["checkpoint"].tool_envelopes == []


def test_workflow_still_answers_when_the_shift_is_given():
    res = run([call("energy_shift", machine="Press 2", day="2026-11-04", shift="A"), AgentDecision(action="FINISH")])
    assert res["status"] == "ok"
    assert res["evidence"]["params"]["shift"] == "A"
