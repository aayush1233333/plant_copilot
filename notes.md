# Plant Copilot: Notes, Ambiguities & Stakeholder Questions

This document captures data ambiguities, assumptions, and specific clarification questions for the plant owner.

---

## 1. Open Questions for Plant North Owner

### Q1: Energy Shift Window Definition (Decision D1)
- **Observation**: Machine minute shifts are strictly `08:00–20:00` (Shift A) and `20:00–08:00` (Shift B). However, in `energy_hourly`, all hourly slots run on the half-hour (`07:30:01` to `19:30:00` for Shift A).
- **Question**: Does "energy in Shift A" mean the platform's labeled 07:30:01–19:30:00 window, or the nominal 08:00–20:00 window?
- **Decision Taken**: Adopted the 07:30:01–19:30:00 platform label window because interpolating across half-hour boundaries would violate the non-negotiable rule against interpolation.

### Q2: Energy kWh Column Discrepancy (Decision D3)
- **Observation**: Across all 12 meters, the `kwh` column is consistently ~2.5% below the physical register delta (`kwh / delta ≈ 0.975`).
- **Question**: Why does the `kwh` column deviate from the physical counter readings? Is there a power factor correction or CT ratio multiplier applied?
- **Decision Taken**: Used `counter_end - counter_start` as the authoritative ground truth; recorded `kwh` sum as sensitivity.

### Q3: Stop Reason "Real Lost Time" (Q6)
- **Observation**: `Data Issue` accounts for 3,974 operator-entered minutes between 1 and 7 Nov.
- **Question**: Should `Data Issue` be reported as lost time, or excluded because it indicates the machine was actually running?
- **Decision Taken**: Excluded `Data Issue` from real lost time ranking based on business rule ("machine was actually running"); primary answer is `Breakdown` (1,869 minutes).

### Q4: Calendar Dates vs. Plant Days for Rejections & Stoppages (Q6, Q8, Q9)
- **Observation**: Profiling proved `reason_date` and `reject_date` are calendar dates (entries in early morning hours 00:00–07:00 were created after the hour ended on that same calendar day).
- **Question**: When asking for "stops on 3 Nov", "rejections on 2 Nov", or "1 to 7 Nov", do operators mean calendar dates or plant days (08:00 to 08:00)?
- **Decision Taken**: Implemented calendar date as primary for `reason_date`/`reject_date` filters, while carrying plant-day derived figures in the sensitivity section.

### Q5: Financial Model / Cost Rates (Q7)
- **Observation**: No cost rates, hourly depreciation, labor rates, or product prices exist in `factory.db`.
- **Decision Taken**: Returned `null` with `insufficient_data` per Amendment 6.

---

## 2. Questions for Plant South Owner

1. **Void Downtime Intervals**: What does `is_void = 1` indicate in `tbl_downtime` when `tbl_mc_status` shows the machine stopped?
2. **Blank Downtime Causes**: Why are 71 downtime entries blank?
3. **Status Timestamp Placement**: Does `stamp` in `tbl_mc_status` mark the beginning or the end of the 5-minute interval?
4. **Shift Definitions**: Are Plant South shifts identical to Plant North (08:00 / 20:00)?


---

## 3. More questions for the Plant North owner

### N6: What does "did not run" mean in q1?
- **Observation**: Press 2 has 7 stops of 30 minutes or more by the system flag. One of them (102 minutes on 4 Nov) has 96 minutes entered as Data Issue, meaning the machine was actually running.
- **Question**: Should a stop be judged by the system flag (answer 7) or by what really happened (answer 6)?
- **Decision taken**: 6, with 7 kept in the envelope sensitivity.

### N7: q4: should a missing first slot make energy "incomplete"?
- **Observation**: Press 3's first shift-A slot is missing, but the previous slot ends at exactly 07:30:00 with the register value, and all 3,343 consecutive slot pairs link with a 0.0 jump.
- **Question**: Is a neighbouring reading enough proof of the boundary, or did you expect "incomplete"?
- **Decision taken**: 140.7 kWh, with "incomplete" kept as the strict alternative.

### N8: q2: a minute with no data
- **Observation**: Press 2 has no row at 10:47 on 3 Nov, between two stopped stretches. Our rule treats a missing minute as unknown, so the answer is 299 with a range of 299 to 300.
- **Question**: Should a missing minute inside a stop be counted as stopped?

### N9: What do "yesterday" and "this week" mean?
- **Question**: Is "yesterday" the previous plant day (08:00 to 08:00) or the previous calendar day, and which days make up "this week"?
- **Decision taken**: Yesterday means the previous plant day. An unclear range should be asked back, not guessed.

### N10: "Right now" and the last minute of data
- **Observation**: Press 1 ran through 14:35 and stopped at 14:36, the last minute in the snapshot. Energy data ends at 14:30 and rejections at 14:28, so "now" differs by source.
- **Question**: Should "running right now" use the exact last minute, or the last full minute?
- **Decision taken**: The exact latest minute, so Press 1 is not listed.
