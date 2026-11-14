# Decisions log

## Data rules (from profiling, scripts 01-08)

- Tenant key: company_id. energy_hourly has none, so energy goes through energy_meters.company_id.
- Timestamps are naive plant-local text, no timezone.
- machine_minutes: no duplicate keys in this snapshot; missing minutes (1-2 in a row) are UNKNOWN, never stopped.
- stop_reasons / rejections: live = deleted_at '0000-00-00 00:00:00'; exact duplicates collapsed to one.
- reason_date and reject_date are CALENDAR dates (verified: no entry created before its hour). Plant day derived from reason_date + hour_start minus 8 hours.
- Lateness = created_at minus end of the described hour; strictly greater than 24h.

## Energy

- Register (counter_start/counter_end) is the source of truth; kwh column is about 0.975 x register delta, unexplained (owner question).
- Meter clock equals machine clock (best correlation offset 0 on all 12 meters; Press 3 stop at 20:00 lands mid-slot).
- D1: energy shift A = platform label (slots 07:30:01-19:30:00). PENDING owner confirmation. Caveat shown on every energy answer.
- D2: bridge a gap only if register non-decreasing and jump <= slots x meter max single-slot delta; else incomplete.
- D3: register over kwh column.

## Open owner questions
- Does energy shift A mean the platform label window (07:30-19:30) or the nominal 08:00-20:00?
- Why is kwh about 2.5% below the register delta?
- q9: calendar date or plant day for "2 Nov"?
- q6/q8: calendar dates or plant days for "1 to 7 Nov"?


## Plant South (south_sample.db, script 09)
- No tenant column: tenant = the database connection. 3 assets, 2 days (5 Nov 08:00 to 7 Nov 07:55).
- Status: 5-minute rows, run_flag Y/N only, no gaps, no duplicates. qty_ok / qty_ng are per-interval counts.
- Stamp appears to label the START of its 5-minute bucket (inferred from downtime alignment).
- Downtime intervals tile the N status rows exactly (366 rows). Void intervals (7) still show the machine stopped.
- cause_txt: 4 values, 71 blank, abbreviated codes.
- Energy: kwh_cum cumulative, hourly on :00, no gaps/resets/duplicates. Last reading 7 Nov 07:00, so a day ending 08:00 on 7 Nov is incomplete.
- Capabilities: running_now, pieces, rejects(partial), downtime, energy = supported; planned_time, late_entries, cost = insufficient_data; shifts = not assumed.

## South owner questions
- What does is_void mean, given status still shows the machine stopped?
- Why are 71 downtime causes blank?
- Is the status stamp the start or end of its 5-minute bucket?
- Are South shifts the same 08:00/20:00 as North?
- Why does qty_ng appear on non-running rows? What unit is kwh_cum?


## Stop runs (Step 4)
- Stop = run of consecutive STOPPED_PLANNED minutes. RUNNING, NOT_PLANNED and UNKNOWN all end a run; a missing minute is never bridged.
- q1 counts runs with >= 30 minutes per PLANT day (08:00 to 08:00). A stop crossing 20:00 is one stop. A calendar-day reading would give a different count (Press 2, 3 Nov: 4 stops start on 3 Nov, 3 on 4 Nov before 08:00). Owner question.
- Each run records the state before and after it, and flags if it touches the window edge.
- Raw candidates for Press 2, 3 Nov: q1 = 7, q2 = 299 (1 UNKNOWN minute in shift A). Cross-checked against SQL. NOT FINAL until the Data Issue decision and the evidence envelope.

## D4: Data Issue correction (Step 5) - CONFIRMED
- Press 2, 3 Nov: 2 live Data Issue entries (4 Nov 01:00 = 51 min, 02:00 = 45 min), both inside the 102-min stop 01:08-02:49. Entered minutes equal stopped minutes in both hours (51+1=52, 45+5=50).
- Long-run rule: UNCHANGED if no Data Issue entries fall in the hours it touches; ELIMINATED if run minutes minus Data Issue minutes (capped per hour at that hour's stopped minutes) is < 30; otherwise AMBIGUOUS (report a range, never guess minute placement).
- Code must TEST the subset assumption (Data Issue minutes <= stopped minutes in each hour used); if it fails, the run is AMBIGUOUS.
- q1 primary = corrected = 6 (alternative: raw = 7). q2 primary = 299 (same in both versions; 1 UNKNOWN minute in shift A gives range 299-300).
- Entries were created after the plant day closed (4 Nov 09:09 and 11:44), so answers are valid as of the snapshot only.
- Owner question: does "did not run" mean the system flag (answer 7) or real running (answer 6)?

## D5: q5 total pieces (Step 7)
- q5 = sum of per-minute pieces for all Kalpa machines over the plant day of 31 Oct (31 Oct 08:00 to 1 Nov 08:00). Reproduced by an independent SQL query: 54123.
- 23 machine-minutes had no data (11497 of 11520 present). Missing minutes are never treated as zero, so 54123 is a lower bound; the envelope carries an upper bound in sensitivity.
- Status ok with a coverage caveat (alternative considered: null, rejected because the recorded count is a meaningful database-matching number).
- Pieces counted, not good pieces: rejections are not subtracted.
- Bender 1 recorded 0 pieces and 0 running minutes that day (check scripts\15_bender1_days.py output).
