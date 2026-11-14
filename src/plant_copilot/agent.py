import json
import os
from datetime import date
from typing import Any, Dict, List, Literal, Optional, Tuple

from google import genai
from google.genai import types
from pydantic import BaseModel

from plant_copilot.envelope import MetricResult

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

ALLOWED_TOOLS = {
    "q1_long_stops",
    "q2_standstill_shift",
    "energy_shift",
    "q5_total_pieces",
    "q6_top_stop_reason",
    "q7_stop_cost_rupees",
    "q8_late_stop_entries",
    "q9_rejections",
    "q10_running_now",
    "rank_machine_downtime",
    "south_running_now",
    "south_unsupported",
}

TOOL_CATALOG = """Tools (call only from this list):
- q1_long_stops(machine, day): count planned stops >=30m on plant day YYYY-MM-DD (08:00-08:00).
- q2_standstill_shift(machine, day, shift): planned standstill minutes for machine in shift A (08:00-20:00) or B (20:00-08:00) on plant day YYYY-MM-DD.
- energy_shift(machine, day, shift): meter-register energy kWh in shift A or B on YYYY-MM-DD.
- q5_total_pieces(day): total pieces across all tenant machines on plant day YYYY-MM-DD.
- q6_top_stop_reason(start_date, end_date, machine?): top real lost-time stop reason (excludes Data Issue) over calendar dates YYYY-MM-DD..YYYY-MM-DD; machine optional.
- q7_stop_cost_rupees(day): financial stop cost on YYYY-MM-DD (returns insufficient_data if no cost rates exist).
- q8_late_stop_entries(start_date, end_date): count unique live stop-reason entries created >24h after hour end over YYYY-MM-DD..YYYY-MM-DD.
- q9_rejections(day): rejected pieces on calendar date YYYY-MM-DD.
- q10_running_now(): machines running at tenant snapshot 'now'.
- rank_machine_downtime(day): rank all tenant machines by Data-Issue-corrected planned downtime on plant day YYYY-MM-DD.
- south_running_now(): Plant South running assets at snapshot (use ONLY when plant=south).
- south_unsupported(metric_name, reason): use when plant=south does not support the requested capability (e.g. planned_time, shift_schedules, late_entries, financial_cost)."""


class AgentDecision(BaseModel):
    action: Literal["CALL_TOOL", "FINISH", "CLARIFY", "CANNOT_ANSWER"]
    tool_name: Optional[str] = None
    machine: Optional[str] = None
    day: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    shift: Optional[str] = None
    reason: str = ""


def _is_iso_date(val: Optional[str]) -> bool:
    if not val:
        return False
    try:
        date.fromisoformat(val)
        return True
    except ValueError:
        return False


def validate_decision(decision: AgentDecision) -> Optional[str]:
    """Return None if valid, else an error message explaining what failed validation."""
    if decision.action != "CALL_TOOL":
        return None
    name = decision.tool_name
    if not name or name not in ALLOWED_TOOLS:
        return f"Tool {name!r} is not in ALLOWED_TOOLS."

    if decision.shift is not None and decision.shift not in ("A", "B"):
        return f"Invalid shift {decision.shift!r}; expected 'A' or 'B'."

    for field_name, val in (("day", decision.day), ("start_date", decision.start_date), ("end_date", decision.end_date)):
        if val is not None and not _is_iso_date(val):
            return f"Invalid ISO date for {field_name}: {val!r}."

    if name == "q1_long_stops" and (not decision.machine or not decision.day):
        return "q1_long_stops requires 'machine' and 'day'."
    if name in ("q2_standstill_shift", "energy_shift") and (not decision.machine or not decision.day):
        return f"{name} requires 'machine' and 'day'."
    if name in ("q5_total_pieces", "q7_stop_cost_rupees", "q9_rejections", "rank_machine_downtime") and not decision.day:
        return f"{name} requires 'day'."
    if name in ("q6_top_stop_reason", "q8_late_stop_entries") and (not decision.start_date or not decision.end_date):
        return f"{name} requires 'start_date' and 'end_date'."
    return None


def compact_digest(tool_name: str, params: Dict[str, Any], res: MetricResult) -> Dict[str, Any]:
    """Compact representation of a MetricResult for token-efficient multi-step reasoning."""
    digest: Dict[str, Any] = {
        "tool": tool_name,
        "params": params,
        "status": res.status,
        "value": res.value,
        "display": res.display,
        "as_of": res.as_of,
        "result_hash": res.result_hash[:12],
    }
    if res.needed_data:
        digest["needed_data"] = res.needed_data
    if res.details:
        digest["top_details"] = res.details[:3]
    if res.sensitivity:
        digest["sensitivity_summary"] = res.sensitivity[:2]
    return digest


def _extract_tokens(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    return {
        "prompt_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(usage, "candidates_token_count", 0) or 0),
        "total_tokens": int(getattr(usage, "total_token_count", 0) or 0),
    }


class GeminiAgent:
    """Token-optimized Gemini tool-calling planner & multi-tool answer composer."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self._client = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError("GEMINI_API_KEY is not set. Set $env:GEMINI_API_KEY in PowerShell.")
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=25000),
            )
        return self._client

    def _thinking_cfg(self) -> Optional[types.ThinkingConfig]:
        if "2.5" in self.model:
            return types.ThinkingConfig(thinking_budget=0)
        return None

    def next_step(
        self,
        question: str,
        plant: str,
        machines: List[str],
        as_of: str,
        current_plant_day: str,
        digests: List[Dict[str, Any]],
    ) -> Tuple[AgentDecision, Dict[str, int]]:
        system_prompt = (
            "You are Plant Copilot's deterministic tool planner.\n"
            f"Plant: {plant}. Snapshot 'now': {as_of}. Current plant day: {current_plant_day}.\n"
            f"Available machines/assets: {', '.join(machines)}.\n"
            "Rules:\n"
            "1. Plant day runs 08:00 to 08:00 next day; 'yesterday' = previous plant day.\n"
            "2. Never invent numbers or switch tenants. Only pick tools and parameters.\n"
            "3. Choose CALL_TOOL if another metric is needed, FINISH once tool digests answer the question, "
            "CANNOT_ANSWER if no tool or data supports the request, or CLARIFY if ambiguous.\n"
            "4. Do not repeat an already completed tool call with the same parameters.\n\n"
            + TOOL_CATALOG
        )
        user_prompt = (
            f"Question: {question}\n"
            f"Completed tool digests ({len(digests)}): {json.dumps(digests, separators=(',', ':'))}"
        )

        client = self._get_client()
        cfg = types.GenerateContentConfig(
            temperature=0,
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=AgentDecision,
            thinking_config=self._thinking_cfg(),
        )
        response = client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=cfg,
        )
        if getattr(response, "parsed", None) is not None:
            decision = response.parsed
        else:
            decision = AgentDecision.model_validate_json(response.text)
        return decision, _extract_tokens(response)

    def compose_multi_tool_answer(
        self,
        question: str,
        digests: List[Dict[str, Any]],
    ) -> Tuple[str, Dict[str, int]]:
        system_prompt = (
            "Summarize the verified tool digests to answer the user's question concisely.\n"
            "STRICT RULE: Use ONLY numbers present in the digests. Never calculate or invent numbers. "
            "Include the snapshot timestamp (as_of)."
        )
        user_prompt = (
            f"Question: {question}\n"
            f"Tool digests: {json.dumps(digests, separators=(',', ':'))}"
        )
        client = self._get_client()
        cfg = types.GenerateContentConfig(
            temperature=0,
            system_instruction=system_prompt,
            thinking_config=self._thinking_cfg(),
        )
        response = client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=cfg,
        )
        return (response.text or "").strip(), _extract_tokens(response)
