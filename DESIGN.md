# Plant Copilot: Architecture & Design Specification

## 1. System Architecture

Plant Copilot is a deterministic manufacturing metrics engine orchestrated by a token-optimized, checkpointed Gemini AI tool-calling agent (`src/plant_copilot/agent.py`, `src/plant_copilot/workflow.py`).

    Operator CLI (--tenant / --plant / --resume)
            |
            v
    Tenant Resolver (Trusted CLI context - never inferred from prompt)
            |
            v
    GeminiAgent Tool Loop (agent.py: gemini-2.5-flash, temperature=0, strict AgentDecision)
            |  - Strict 12-tool allowlist (ALLOWED_TOOLS); ISO date & shift validation
            |  - Multi-step loop receives only compact_digest() summaries, never raw DB rows
            v
    Watermark-Aware Cache (keyed by tenant, metric, normalized params, data_watermark)
            |
            v
    Deterministic Metrics Engine (SQLite PRAGMA query_only=ON + Python)
            |-- Stoppage (gaps-and-islands, Data Issue D4 correction)
            |-- Energy (meter registers, gap bridging D2, boundary proof)
            |-- Production (per-minute piece aggregation, coverage tracking)
            |-- Operations (rejections, late entries, machine downtime ranking, snapshot now)
            +-- Plant South Adapter (SouthPlantAdapter with explicit SouthCapabilities)
            |
            v
    Evidence Envelope Sealer (SHA-256 result_hash per MetricResult)
            |
            v
    Composer & GroundingValidator.validate_many (blocks hallucinated numbers)
            |
            v
    Output: Verified Answer + Evidence Envelope + Saved Checkpoint

---

## 2. Non-Negotiable Requirements Enforcement

| Requirement | Implementation Mechanism | Verification Test |
|---|---|---|
| **Client Isolation** | `TenantDB` forces `company_id = ?` on every query and opens SQLite with `?mode=ro` and `PRAGMA query_only = ON`. Energy hourly joins `energy_meters` on `company_id`. `AgentDecision` has no `tenant` parameter; prompt injections cannot change tenant. | `tests/test_tenant.py`, `test_workflow_client_isolation_and_bad_tool_blocked` |
| **Exact Numbers** | All calculations run deterministically in Python/SQL. Gemini only selects tools and parameters; it never runs SQL or math. | `test_production.py`, `test_stoppage.py`, `test_energy.py` |
| **Evidence Envelope** | Every metric call returns `MetricResult` (status, value, display, metric, sql, logic, params, rows_used, as_of, coverage, caveats, sensitivity, needed_data, result_hash). | `envelope.py`, `test_envelope_has_all_required_keys` |
| **Fresh Data ("Now")** | "Now" is the tenant's latest minute watermark (`2026-11-07 14:36:00` for Kalpa; `2026-11-07 07:55:00` for Plant South), never server wall-clock time. | `test_latest_minute_is_the_tenant_watermark`, `test_q10_running_machines_now` |
| **Energy Accuracy** | Register delta (`counter_end - counter_start`) is source of truth (`kwh` column is ~2.5% lower). Missing slots bridged only if non-decreasing and jump <= gap * max_delta. Boundary proven via adjacent Shift B reading (Amendment 4). Unproven gaps return `"incomplete"`. | `test_energy.py`, profiling scripts 06-08 |
| **Honesty** | Missing data or unsupported Plant South capabilities return `null` / `insufficient_data` with explicit explanation in `needed_data`. | `test_q7_cost_returns_null_and_explains_missing_data`, `test_south_adapter.py` |

---

## 3. Workflow State Machine, Token Optimization & Resume

Execution follows a strict checkpointed lifecycle:

    RECEIVED --> PLANNED (per tool step) --> EXECUTED --> COMPOSED --> DONE

- Terminal/recovery states: `CLARIFY`, `CANNOT_ANSWER`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `EXPIRED`.
- Checkpoints persist to `.checkpoints/{run_id}.json` after `RECEIVED`, after every completed tool call, and after `EXECUTED`, `COMPOSED`, and `DONE`.
- **Mid-Run Resume:** On API error or rate-limit (`FAILED_RETRYABLE`), completed `tool_envelopes` and `tool_digests` remain saved. Running `WorkflowEngine.resume(run_id)` (`cli ask --resume <run_id>`) validates `data_watermark` (returning `EXPIRED` if data changed), skips already completed tool steps, and continues from the failed step.
- **Token Optimization:**
  1. Compact static tool catalog + machine list + snapshot timestamp only (zero raw DB rows sent to Gemini).
  2. Multi-step iterations pass only `compact_digest()` summaries (`result_hash[:12]`, `value`, `display`, top 3 details) instead of replaying full histories.
  3. `ThinkingConfig(thinking_budget=0)` on `gemini-2.5-flash` removes hidden reasoning-token overhead.
  4. Single-tool answers compose deterministically from `MetricResult.display` at 0 extra LLM tokens.

Verified by `tests/test_workflow.py` (`test_workflow_multistep_tool_loop_and_compact_digests`, `test_workflow_midrun_failure_and_resume_skips_completed_steps`, `test_workflow_resume_expires_if_watermark_changes`).

---

## 4. Defended Answers & Numbers (`answers.json`)

| Key | Value | Logic & Defensibility |
|---|---|---|
| **q1** | `6` | 7 raw stops >= 30 min on plant day 3 Nov (08:00 to 08:00). Stop 01:08-02:49 (102 min) contained 96 min of entered "Data Issue" in hours 01:00 and 02:00, provably reducing it below 30 min (D4 rule -> ELIMINATED). Primary = 6, raw alternative = 7. |
| **q2** | `299` | Minutes with `planned = 1` and `running = 0` in Shift A (08:00-20:00) on 3 Nov. 1 minute had no data (`10:47:00`), leaving standstill bounded between 299 and 300 min. |
| **q3** | `229.3` | Press 2 (meter 501) on 4 Nov Shift A (07:30:01-19:30:00). Start reg: 43372.70, End reg: 43601.98. Missing interior slot 12:30-13:30 successfully bridged (jump 17.82 kWh <= 22.37 max slot delta). `43601.98 - 43372.70 = 229.28 -> 229.3 kWh`. |
| **q4** | `140.7` | Press 3 (meter 502) on 5 Nov Shift A. First slot (07:30-08:30) missing; preceding Shift B slot ended at 07:30:00 with reg 12177.65. Jump to next slot is 13.27 kWh <= 15.27 max delta. End reg: 12318.36. `12318.36 - 12177.65 = 140.71 -> 140.7 kWh` (Amendment 4). |
| **q5** | `54123` | Sum of per-minute pieces across all 8 Kalpa machines on 31 Oct plant day (08:00 to 08:00). 23 machine-minutes missing data (lower bound; upper bound 54372). Bender 1 was idle (0 pieces). |
| **q6** | `"Breakdown"` | Top reason by entered operator minutes 1-7 Nov. `Data Issue` (3,974 min) excluded as it indicates machine was actually running. Breakdown = 1,869 min (calendar) / 1,749 min (plant day). |
| **q7** | `null` | Zero cost/rate/financial columns exist in `factory.db`. Returns `null` with needed data specified (Amendment 6). |
| **q8** | `44` | Live deduplicated stop entries where `created_at > hour_end + 24h` between 1 and 7 Nov (calendar). Sensitivity: 42 entries under plant-day reading. |
| **q9** | `124` | Live deduplicated rejections on calendar date 2 Nov (Burr 29, Crack 26, Dent 30, Flash 16, Short shot 23). Sensitivity: 190 pieces under plant-day reading. |
| **q10** | `["Press 2", "Bender 1", "Moulder 2"]` | Live machine records at tenant watermark `2026-11-07 14:36:00` with `running = 1`. All 8 machines have recorded state. |

---

## 5. Plant South Integration

Plant South (`south_sample.db`) uses `SouthPlantAdapter` (`--plant south`) with explicit `SouthCapabilities`:
- **Supported**: `running_now` (5-min intervals, binary `run_flag`), `pieces_count` (`qty_ok`), `rejects_count` (`qty_ng`), `energy_cumulative` (`kwh_cum`).
- **Unsupported**: `planned_time`, `late_entries`, `shift_schedules`, `financial_cost`.
- Unsupported queries return `status="insufficient_data"` without forcing Plant North rules onto Plant South.
