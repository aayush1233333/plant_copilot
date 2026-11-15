import json
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from plant_copilot.agent import (
    AgentDecision,
    GeminiAgent,
    compact_digest,
    missing_fields_question,
    validate_decision,
)
from plant_copilot.energy import energy_shift
from plant_copilot.envelope import MetricResult
from plant_copilot.operations import (
    explain_machine_downtime,
    q6_top_stop_reason,
    q7_stop_cost_rupees,
    q8_late_stop_entries,
    q9_rejections,
    q10_running_now,
    rank_machine_downtime,
)
from plant_copilot.production import q5_total_pieces
from plant_copilot.south_adapter import SouthPlantAdapter
from plant_copilot.stoppage import q1_long_stops, q2_standstill_shift
from plant_copilot.tenant import TenantDB, resolve_tenant
from plant_copilot.timeutil import parse_ts, plant_day_of

WorkflowStatus = Literal[
    "RECEIVED", "PLANNED", "EXECUTED", "COMPOSED", "DONE",
    "CLARIFY", "CANNOT_ANSWER", "FAILED_RETRYABLE", "FAILED_FINAL", "EXPIRED"
]

SOUTH_ONLY_TOOLS = {"south_running_now", "south_unsupported"}


class MetricCall(BaseModel):
    metric: str
    params: Dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    intent: str = "agent_tool_loop"
    metric_calls: List[MetricCall] = Field(default_factory=list)
    reasoning: str = ""


class Checkpoint(BaseModel):
    run_id: str
    tenant: str
    plant: str = "north"
    normalized_question: str
    plan: Optional[ExecutionPlan] = None
    completed_steps: List[str] = Field(default_factory=list)
    current_step: WorkflowStatus
    tool_digests: List[Dict[str, Any]] = Field(default_factory=list)
    tool_envelopes: List[Dict[str, Any]] = Field(default_factory=list)
    result_hashes: Dict[str, str] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)
    token_usage: Dict[str, int] = Field(
        default_factory=lambda: {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    )
    data_watermark: str = ""
    final_answer: str = ""
    final_value: Any = None
    status: WorkflowStatus


class GroundingValidator:
    @staticmethod
    def _allowed_from_envelope(envelope: MetricResult) -> set[str]:
        allowed: set[str] = set()

        def _collect_nums(obj: Any) -> None:
            if isinstance(obj, bool):
                return
            if isinstance(obj, (int, float)):
                allowed.add(str(obj))
                if isinstance(obj, float):
                    allowed.add(str(int(obj)))
            elif isinstance(obj, str):
                for n in re.findall(r"\b\d+(?:\.\d+)?\b", obj):
                    allowed.add(n)
            elif isinstance(obj, dict):
                for val in obj.values():
                    _collect_nums(val)
            elif isinstance(obj, list):
                for item in obj:
                    _collect_nums(item)

        _collect_nums(envelope.value)
        _collect_nums(envelope.params)
        _collect_nums(envelope.display)
        _collect_nums(envelope.as_of)
        _collect_nums(envelope.details)
        _collect_nums(envelope.sensitivity)
        _collect_nums(envelope.coverage.observed)
        _collect_nums(envelope.coverage.expected)
        return allowed

    @classmethod
    def validate(cls, composed_text: str, envelope: MetricResult) -> bool:
        return cls.validate_many(composed_text, [envelope])

    @classmethod
    def validate_many(cls, composed_text: str, envelopes: List[MetricResult]) -> bool:
        nums_in_text = set(re.findall(r"\b\d+(?:\.\d+)?\b", composed_text))
        allowed_nums: set[str] = set()
        for env in envelopes:
            allowed_nums.update(cls._allowed_from_envelope(env))
        return all(n in allowed_nums for n in nums_in_text)


class WorkflowEngine:
    def __init__(
        self,
        db_path: str = "data/factory.db",
        south_db_path: str = "data/south_sample.db",
        checkpoint_dir: str = ".checkpoints",
        agent: Optional[Any] = None,
        use_llm_composer: bool = False,
    ):
        self.db_path = db_path
        self.south_db_path = south_db_path
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.agent = agent if agent is not None else GeminiAgent()
        self.use_llm_composer = use_llm_composer
        self._cache: Dict[str, MetricResult] = {}

    def _save_checkpoint(self, cp: Checkpoint) -> None:
        path = self.checkpoint_dir / f"{cp.run_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            f.write(cp.model_dump_json(indent=2))

    def _load_checkpoint(self, run_id: str) -> Optional[Checkpoint]:
        path = self.checkpoint_dir / f"{run_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return Checkpoint.model_validate_json(f.read())

    @staticmethod
    def _add_tokens(cp: Checkpoint, usage: Dict[str, int]) -> None:
        for k in ("prompt_tokens", "output_tokens", "total_tokens"):
            cp.token_usage[k] = cp.token_usage.get(k, 0) + int(usage.get(k, 0))

    @staticmethod
    def _decision_to_call(decision: AgentDecision) -> MetricCall:
        name = decision.tool_name or ""
        params: Dict[str, Any] = {}
        if decision.machine:
            params["machine"] = decision.machine
        if decision.day:
            params["day"] = decision.day
        if decision.start_date:
            params["start_date"] = decision.start_date
        if decision.end_date:
            params["end_date"] = decision.end_date
        if decision.shift:
            params["shift"] = decision.shift
        if name == "south_unsupported":
            params["metric_name"] = decision.machine or "unsupported_metric"
            params["reason"] = decision.reason or "Capability unsupported by Plant South schema."
        return MetricCall(metric=name, params=params)

    def _execute_metric(
        self,
        call: MetricCall,
        plant: str,
        watermark: str,
        db: Optional[TenantDB] = None,
        south: Optional[SouthPlantAdapter] = None,
    ) -> MetricResult:
        tenant_key = "south" if plant == "south" else str(db._ctx.company_id)
        cache_key = f"{tenant_key}:{call.metric}:{json.dumps(call.params, sort_keys=True)}:{watermark}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        name = call.metric
        p = call.params
        if plant == "south":
            assert south is not None
            if name == "south_running_now":
                res = south.running_now()
            elif name == "south_unsupported":
                res = south.unsupported(p.get("metric_name", "metric"), p.get("reason", "Unsupported by Plant South"))
            else:
                res = south.unsupported(name, f"{name} is a Plant North metric not supported on Plant South.")
        else:
            assert db is not None
            if name == "q1_long_stops":
                res = q1_long_stops(db, p["machine"], date.fromisoformat(p["day"]))
            elif name == "q2_standstill_shift":
                res = q2_standstill_shift(db, p["machine"], date.fromisoformat(p["day"]), p["shift"])
            elif name == "energy_shift":
                res = energy_shift(db, p["machine"], date.fromisoformat(p["day"]), p["shift"])
            elif name == "q5_total_pieces":
                res = q5_total_pieces(db, date.fromisoformat(p["day"]))
            elif name == "q6_top_stop_reason":
                res = q6_top_stop_reason(db, p["start_date"], p["end_date"], machine_name=p.get("machine"))
            elif name == "q7_stop_cost_rupees":
                res = q7_stop_cost_rupees(db, date.fromisoformat(p["day"]))
            elif name == "q8_late_stop_entries":
                res = q8_late_stop_entries(db, p["start_date"], p["end_date"])
            elif name == "q9_rejections":
                res = q9_rejections(db, p["day"])
            elif name == "q10_running_now":
                res = q10_running_now(db)
            elif name == "rank_machine_downtime":
                res = rank_machine_downtime(db, date.fromisoformat(p["day"]))
            elif name in ("explain_machine_downtime", "explain_downtime"):
                res = explain_machine_downtime(db, date.fromisoformat(p["day"]))
            else:
                raise ValueError(f"Unknown metric {name}")

        self._cache[cache_key] = res
        return res

    def _open_backend(self, plant: str, tenant_name: str):
        if plant == "south":
            south = SouthPlantAdapter(self.south_db_path)
            watermark = south.latest_timestamp() or ""
            machines = [a["asset_code"] for a in south.assets()]
            return None, south, watermark, machines
        db = TenantDB(resolve_tenant(self.db_path, tenant_name))
        watermark = db.latest_minute() or ""
        machines = [m["name"] for m in db.machines()]
        return db, None, watermark, machines

    @staticmethod
    def _compose_deterministic(envelopes: List[MetricResult], watermark: str) -> str:
        if len(envelopes) == 1:
            env = envelopes[0]
            if env.status == "insufficient_data":
                prefix = "" if env.display.lower().startswith("null") else "null - "
                return f"{prefix}{env.display} (Needed: {env.needed_data}) [as_of: {env.as_of}]"
            return f"{env.display} [as_of: {env.as_of}]"
        parts = [e.display.rstrip(".") + "." for e in envelopes]
        return " ".join(parts) + f" [as_of: {watermark}]"

    def run(
        self,
        question: str,
        tenant_name: str,
        plant: str = "north",
        run_id: Optional[str] = None,
        max_steps: int = 5,
    ) -> Dict[str, Any]:
        run_id = run_id or str(uuid.uuid4())
        db, south, watermark, machines = self._open_backend(plant, tenant_name)
        effective_tenant = "Plant South" if plant == "south" else db._ctx.name

        cp = Checkpoint(
            run_id=run_id,
            tenant=effective_tenant,
            plant=plant,
            normalized_question=question.strip(),
            plan=ExecutionPlan(),
            current_step="RECEIVED",
            data_watermark=watermark,
            status="RECEIVED",
        )
        cp.completed_steps.append("RECEIVED")
        self._save_checkpoint(cp)
        return self._continue_from_checkpoint(cp, db, south, watermark, machines, max_steps=max_steps)

    def resume(self, run_id: str, max_steps: int = 5) -> Dict[str, Any]:
        cp = self._load_checkpoint(run_id)
        if cp is None:
            raise FileNotFoundError(f"No checkpoint found for run_id={run_id}")

        if cp.status == "DONE":
            envelopes = [MetricResult.model_validate(e) for e in cp.tool_envelopes]
            return {
                "status": "ok",
                "answer": cp.final_answer,
                "value": cp.final_value,
                "evidence": envelopes[-1].model_dump() if envelopes else {},
                "all_evidence": [e.model_dump() for e in envelopes],
                "checkpoint": cp,
            }

        db, south, watermark, machines = self._open_backend(cp.plant, cp.tenant)
        if cp.data_watermark and watermark != cp.data_watermark:
            cp.status = "EXPIRED"
            cp.current_step = "EXPIRED"
            cp.errors.append(f"Data watermark changed from {cp.data_watermark} to {watermark}.")
            self._save_checkpoint(cp)
            if db:
                db.close()
            if south:
                south.close()
            return {"status": "expired", "error": "Data snapshot changed; please re-run.", "checkpoint": cp}

        if cp.plan is None:
            cp.plan = ExecutionPlan()
        return self._continue_from_checkpoint(cp, db, south, watermark, machines, max_steps=max_steps)

    def _continue_from_checkpoint(
        self,
        cp: Checkpoint,
        db: Optional[TenantDB],
        south: Optional[SouthPlantAdapter],
        watermark: str,
        machines: List[str],
        max_steps: int = 5,
    ) -> Dict[str, Any]:
        try:
            current_plant_day = plant_day_of(parse_ts(watermark)).isoformat() if watermark else ""
            if "EXECUTED" not in cp.completed_steps:
                seen_calls = {
                    (c.metric, json.dumps(c.params, sort_keys=True))
                    for c in cp.plan.metric_calls
                }

                while len(cp.tool_envelopes) < max_steps:
                    decision, tokens = self.agent.next_step(
                        question=cp.normalized_question,
                        plant=cp.plant,
                        machines=machines,
                        as_of=watermark,
                        current_plant_day=current_plant_day,
                        digests=cp.tool_digests,
                    )
                    self._add_tokens(cp, tokens)

                    if decision.action in ("CANNOT_ANSWER", "CLARIFY"):
                        cp.status = decision.action
                        cp.current_step = decision.action
                        cp.final_answer = decision.reason or "I cannot answer this question from the available data."
                        if decision.reason:
                            cp.errors.append(decision.reason)
                        self._save_checkpoint(cp)
                        return {
                            "status": decision.action.lower(),
                            "answer": cp.final_answer,
                            "checkpoint": cp,
                        }

                    if decision.action == "FINISH":
                        if not cp.tool_envelopes:
                            cp.status = "CANNOT_ANSWER"
                            cp.current_step = "CANNOT_ANSWER"
                            cp.final_answer = "No verified metric data was gathered to answer this question."
                            self._save_checkpoint(cp)
                            return {"status": "cannot_answer", "answer": cp.final_answer, "checkpoint": cp}
                        break

                    clarify_msg = missing_fields_question(decision, machines)
                    if clarify_msg:
                        cp.status = "CLARIFY"
                        cp.current_step = "CLARIFY"
                        cp.final_answer = clarify_msg
                        self._save_checkpoint(cp)
                        return {"status": "clarify", "answer": cp.final_answer, "checkpoint": cp}

                    err = validate_decision(decision)
                    if err:
                        cp.status = "FAILED_FINAL"
                        cp.current_step = "FAILED_FINAL"
                        cp.errors.append(f"Plan validation failed: {err}")
                        self._save_checkpoint(cp)
                        return {"status": "error", "error": err, "checkpoint": cp}

                    if cp.plant == "north" and decision.tool_name in SOUTH_ONLY_TOOLS:
                        err = f"South-only tool {decision.tool_name!r} cannot be executed on North plant."
                        cp.status = "FAILED_FINAL"
                        cp.current_step = "FAILED_FINAL"
                        cp.errors.append(err)
                        self._save_checkpoint(cp)
                        return {"status": "error", "error": err, "checkpoint": cp}

                    call = self._decision_to_call(decision)
                    call_sig = (call.metric, json.dumps(call.params, sort_keys=True))
                    if call_sig in seen_calls:
                        if cp.tool_envelopes:
                            break
                        cp.status = "FAILED_FINAL"
                        cp.current_step = "FAILED_FINAL"
                        cp.errors.append(f"Repeated tool call rejected: {call.metric}")
                        self._save_checkpoint(cp)
                        return {"status": "error", "error": "Repeated tool call", "checkpoint": cp}

                    envelope = self._execute_metric(call, cp.plant, watermark, db=db, south=south)
                    seen_calls.add(call_sig)
                    cp.plan.metric_calls.append(call)
                    cp.tool_envelopes.append(envelope.model_dump())
                    cp.tool_digests.append(compact_digest(call.metric, call.params, envelope))
                    step_key = f"{len(cp.tool_envelopes)}:{call.metric}"
                    cp.result_hashes[step_key] = envelope.result_hash
                    cp.current_step = "PLANNED"
                    if "PLANNED" not in cp.completed_steps:
                        cp.completed_steps.append("PLANNED")
                    cp.status = "PLANNED"
                    self._save_checkpoint(cp)

                    if decision.final_if_ok and envelope.status in ("ok", "insufficient_data"):
                        break

                cp.current_step = "EXECUTED"
                if "EXECUTED" not in cp.completed_steps:
                    cp.completed_steps.append("EXECUTED")
                cp.status = "EXECUTED"
                self._save_checkpoint(cp)

            envelopes = [MetricResult.model_validate(e) for e in cp.tool_envelopes]
            if "COMPOSED" not in cp.completed_steps:
                if len(envelopes) == 1 or not self.use_llm_composer:
                    answer_text = self._compose_deterministic(envelopes, watermark)
                else:
                    answer_text, tokens = self.agent.compose_multi_tool_answer(
                        cp.normalized_question, cp.tool_digests
                    )
                    self._add_tokens(cp, tokens)
                    if not GroundingValidator.validate_many(answer_text, envelopes):
                        answer_text = self._compose_deterministic(envelopes, watermark)

                if not GroundingValidator.validate_many(answer_text, envelopes):
                    cp.status = "FAILED_FINAL"
                    cp.current_step = "FAILED_FINAL"
                    cp.errors.append("Grounding validation failed: composed answer contained ungrounded numbers.")
                    self._save_checkpoint(cp)
                    return {"status": "error", "error": "Grounding check failed", "checkpoint": cp}

                cp.final_answer = answer_text
                cp.final_value = envelopes[-1].value if len(envelopes) == 1 else [e.value for e in envelopes]
                cp.current_step = "COMPOSED"
                cp.completed_steps.append("COMPOSED")
                cp.status = "COMPOSED"
                self._save_checkpoint(cp)

            cp.current_step = "DONE"
            if "DONE" not in cp.completed_steps:
                cp.completed_steps.append("DONE")
            cp.status = "DONE"
            self._save_checkpoint(cp)

            return {
                "status": "ok",
                "answer": cp.final_answer,
                "value": cp.final_value,
                "evidence": envelopes[-1].model_dump(),
                "all_evidence": [e.model_dump() for e in envelopes],
                "checkpoint": cp,
            }
        except Exception as exc:
            cp.status = "FAILED_RETRYABLE"
            cp.errors.append(f"{type(exc).__name__}: {exc}")
            self._save_checkpoint(cp)
            return {
                "status": "failed_retryable",
                "error": str(exc),
                "checkpoint": cp,
            }
        finally:
            if db:
                db.close()
            if south:
                south.close()
