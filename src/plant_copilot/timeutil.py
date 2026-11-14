from datetime import date, datetime, timedelta

FMT = "%Y-%m-%d %H:%M:%S"
SHIFT_START_HOUR = 8


def parse_ts(s: str) -> datetime:
    """Naive plant-local timestamp text -> datetime. No timezone, by design."""
    return datetime.strptime(s, FMT)


def fmt_ts(dt: datetime) -> str:
    return dt.strftime(FMT)


def shift_of(dt: datetime) -> str:
    return "A" if 8 <= dt.hour < 20 else "B"


def plant_day_of(dt: datetime) -> date:
    return (dt - timedelta(hours=SHIFT_START_HOUR)).date()


def plant_day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, SHIFT_START_HOUR)
    return start, start + timedelta(days=1)


def calendar_day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=1)


def shift_bounds(d: date, shift: str) -> tuple[datetime, datetime]:
    day_start, _ = plant_day_bounds(d)
    if shift == "A":
        return day_start, day_start + timedelta(hours=12)
    if shift == "B":
        return day_start + timedelta(hours=12), day_start + timedelta(hours=24)
    raise ValueError(f"unknown shift {shift!r}")
