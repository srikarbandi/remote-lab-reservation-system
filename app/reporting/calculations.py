"""Pure utilization maths (LAB-F-017, SRS 6.1, SAD 4.1.2). No database access.

Definitions:
    bookable minutes = opening minutes - union of maintenance minutes inside opening hours
    used minutes     = recorded actual usage, clipped to the selected date range
    utilization %    = 100 x used / bookable; undefined (None) when bookable is zero

All intervals are half-open [start, end) and timezone-aware.
"""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

Interval = tuple[datetime, datetime]


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """Sort and merge overlapping or touching intervals; drop empty ones."""
    merged: list[Interval] = []
    for start, end in sorted((s, e) for s, e in intervals if s < e):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def intersect(a: list[Interval], b: list[Interval]) -> list[Interval]:
    """Intersection of two lists that are each sorted and disjoint (see merge_intervals)."""
    result: list[Interval] = []
    i = j = 0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if start < end:
            result.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return result


def total_minutes(intervals: Iterable[Interval]) -> float:
    return sum((end - start).total_seconds() for start, end in intervals) / 60


def range_bounds(tz: ZoneInfo, from_date: date, to_date: date) -> Interval:
    """Half-open UTC interval covering the inclusive local dates (SAD 4.3.5)."""
    start = datetime.combine(from_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    return start, end


def opening_windows(
    tz: ZoneInfo,
    from_date: date,
    to_date: date,
    weekly: Iterable[tuple[int, time | None, time | None]],
    overrides: Iterable[tuple[date, time | None, time | None]],
) -> list[Interval]:
    """Opening intervals (UTC) for each local date in the inclusive range.

    ``weekly`` rows are (weekday, open, close) with Monday = 0. ``overrides`` rows are
    (date, open, close); if any override exists for a date it replaces the weekly rows
    for that date, and an override with no times means closed all day.
    """
    weekly_by_day: dict[int, list[tuple[time | None, time | None]]] = {}
    for weekday, opens, closes in weekly:
        weekly_by_day.setdefault(weekday, []).append((opens, closes))
    overrides_by_date: dict[date, list[tuple[time | None, time | None]]] = {}
    for day, opens, closes in overrides:
        overrides_by_date.setdefault(day, []).append((opens, closes))

    windows: list[Interval] = []
    day = from_date
    while day <= to_date:
        rows = overrides_by_date.get(day)
        if rows is None:
            rows = weekly_by_day.get(day.weekday(), [])
        for opens, closes in rows:
            if opens is None or closes is None or opens >= closes:
                continue
            windows.append(
                (
                    datetime.combine(day, opens, tzinfo=tz).astimezone(timezone.utc),
                    datetime.combine(day, closes, tzinfo=tz).astimezone(timezone.utc),
                )
            )
        day += timedelta(days=1)
    return merge_intervals(windows)


def bookable_minutes(windows: Iterable[Interval], maintenance: Iterable[Interval]) -> float:
    """Opening minutes minus the union of maintenance minutes that fall inside opening hours."""
    merged_windows = merge_intervals(windows)
    blocked = intersect(merged_windows, merge_intervals(maintenance))
    return total_minutes(merged_windows) - total_minutes(blocked)


def used_minutes(usage: Iterable[Interval], range_start: datetime, range_end: datetime) -> float:
    """Recorded usage minutes clipped to the selected range."""
    total = 0.0
    for start, end in usage:
        clipped_start = max(start, range_start)
        clipped_end = min(end, range_end)
        if clipped_start < clipped_end:
            total += (clipped_end - clipped_start).total_seconds() / 60
    return total


def utilization_percent(used: float, bookable: float) -> float | None:
    """100 x used / bookable, or None ("Not applicable") when bookable is zero."""
    if bookable <= 0:
        return None
    return 100.0 * used / bookable
