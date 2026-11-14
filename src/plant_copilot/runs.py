from plant_copilot.minutes import STOPPED_PLANNED


def _make_run(grid, start_idx, length):
    end_idx = start_idx + length  # exclusive
    return {
        "start": grid[start_idx][0],
        "last_minute": grid[end_idx - 1][0],
        "minutes": length,
        "before": grid[start_idx - 1][1] if start_idx > 0 else None,
        "after": grid[end_idx][1] if end_idx < len(grid) else None,
        "touches_window_start": start_idx == 0,
        "touches_window_end": end_idx == len(grid),
    }


def find_runs(grid, target=STOPPED_PLANNED):
    """Gaps-and-islands over an ordered, contiguous minute grid.

    Returns one dict per run of consecutive minutes whose state == target.
    Any other state (RUNNING, NOT_PLANNED, UNKNOWN) ends a run.
    """
    runs = []
    run_start = None
    for i, (_text, state) in enumerate(grid):
        if state == target:
            if run_start is None:
                run_start = i
        elif run_start is not None:
            runs.append(_make_run(grid, run_start, i - run_start))
            run_start = None
    if run_start is not None:
        runs.append(_make_run(grid, run_start, len(grid) - run_start))
    return runs


def count_state(grid, state, lo_text, hi_text):
    """Number of minutes in [lo_text, hi_text) whose state matches. Text compare is safe: fixed-width timestamps."""
    return sum(1 for text, s in grid if lo_text <= text < hi_text and s == state)
