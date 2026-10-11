"""Unit tests for utilization maths. Covers TC-F-017 and TC-EDGE-006 (no database)."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.reporting.calculations import (
    bookable_minutes,
    intersect,
    merge_intervals,
    opening_windows,
    range_bounds,
    total_minutes,
    used_minutes,
    utilization_percent,
)

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
MONDAY = date(2026, 10, 12)  # 2026-10-12 is a Monday


def ist(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST).astimezone(UTC)


def weekday_9_to_5():
    return [(wd, time(9, 0), time(17, 0)) for wd in range(5)]


def test_srs_worked_example_50_percent():
    # SRS 6.1: 480 opening minutes - 60 maintenance minutes = 420 bookable; 210 used -> 50%.
    windows = opening_windows(IST, MONDAY, MONDAY, weekday_9_to_5(), [])
    assert total_minutes(windows) == 480
    maintenance = [(ist(MONDAY, 12), ist(MONDAY, 13))]
    bookable = bookable_minutes(windows, maintenance)
    assert bookable == 420
    start, end = range_bounds(IST, MONDAY, MONDAY)
    usage = [(ist(MONDAY, 10), ist(MONDAY, 12)), (ist(MONDAY, 14), ist(MONDAY, 15, 30))]  # 120 + 90 = 210
    used = used_minutes(usage, start, end)
    assert used == 210
    assert utilization_percent(used, bookable) == 50.0


def test_zero_bookable_minutes_is_not_applicable():
    assert utilization_percent(0, 0) is None
    assert utilization_percent(30, 0) is None


def test_fully_blocked_day_is_not_applicable():
    windows = opening_windows(IST, MONDAY, MONDAY, weekday_9_to_5(), [])
    bookable = bookable_minutes(windows, [(ist(MONDAY, 8), ist(MONDAY, 18))])
    assert bookable == 0
    assert utilization_percent(0, bookable) is None


def test_overlapping_maintenance_is_counted_once():
    windows = opening_windows(IST, MONDAY, MONDAY, weekday_9_to_5(), [])
    maintenance = [(ist(MONDAY, 10), ist(MONDAY, 12)), (ist(MONDAY, 11), ist(MONDAY, 13))]  # union = 3 h
    assert bookable_minutes(windows, maintenance) == 480 - 180


def test_maintenance_outside_opening_hours_is_ignored():
    windows = opening_windows(IST, MONDAY, MONDAY, weekday_9_to_5(), [])
    maintenance = [(ist(MONDAY, 18), ist(MONDAY, 20)), (ist(MONDAY, 6), ist(MONDAY, 8))]
    assert bookable_minutes(windows, maintenance) == 480


def test_maintenance_straddling_closing_time_is_clipped():
    windows = opening_windows(IST, MONDAY, MONDAY, weekday_9_to_5(), [])
    maintenance = [(ist(MONDAY, 16), ist(MONDAY, 20))]  # only 16:00-17:00 is inside opening hours
    assert bookable_minutes(windows, maintenance) == 420


def test_usage_is_clipped_to_the_selected_range():
    start, end = range_bounds(IST, MONDAY, MONDAY)
    usage = [(start - timedelta(hours=1), start + timedelta(hours=1))]  # 60 of 120 minutes inside
    assert used_minutes(usage, start, end) == 60


def test_usage_outside_range_counts_zero():
    start, end = range_bounds(IST, MONDAY, MONDAY)
    assert used_minutes([(end + timedelta(hours=1), end + timedelta(hours=2))], start, end) == 0


def test_weekend_has_no_opening_windows():
    saturday = date(2026, 10, 10)
    assert opening_windows(IST, saturday, saturday, weekday_9_to_5(), []) == []


def test_multi_day_range_sums_opening_minutes():
    # Mon 12 to Sun 18 Oct: five weekdays of 480 minutes.
    windows = opening_windows(IST, MONDAY, date(2026, 10, 18), weekday_9_to_5(), [])
    assert total_minutes(windows) == 5 * 480


def test_override_closed_all_day_replaces_weekly_hours():
    windows = opening_windows(IST, MONDAY, MONDAY, weekday_9_to_5(), [(MONDAY, None, None)])
    assert windows == []


def test_override_with_custom_hours_replaces_weekly_hours():
    windows = opening_windows(IST, MONDAY, MONDAY, weekday_9_to_5(), [(MONDAY, time(10), time(12))])
    assert total_minutes(windows) == 120


def test_split_opening_windows_on_one_day():
    weekly = [(0, time(9), time(12)), (0, time(14), time(17))]
    windows = opening_windows(IST, MONDAY, MONDAY, weekly, [])
    assert total_minutes(windows) == 360


def test_range_bounds_use_lab_midnight_not_utc_midnight():
    # TC-EDGE-006: local date 2026-10-12 starts at 2026-10-11 18:30 UTC and is half-open at the next midnight.
    start, end = range_bounds(IST, MONDAY, MONDAY)
    assert start == datetime(2026, 10, 11, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 10, 12, 18, 30, tzinfo=UTC)


def test_late_evening_ist_usage_lands_on_the_local_date():
    # 23:00 IST on Monday is 17:30 UTC Monday; 01:00 IST Tuesday is 19:30 UTC Monday.
    start, end = range_bounds(IST, MONDAY, MONDAY)
    usage = [(ist(MONDAY, 23), ist(MONDAY + timedelta(days=1), 1))]  # 60 minutes on Monday, 60 on Tuesday
    assert used_minutes(usage, start, end) == 60


def test_merge_intervals_merges_touching_and_drops_empty():
    a = datetime(2026, 1, 1, 9, tzinfo=UTC)
    h = timedelta(hours=1)
    merged = merge_intervals([(a + h, a + 2 * h), (a, a + h), (a + 5 * h, a + 5 * h)])
    assert merged == [(a, a + 2 * h)]


def test_intersect_disjoint_lists():
    a = datetime(2026, 1, 1, 9, tzinfo=UTC)
    h = timedelta(hours=1)
    left = [(a, a + 3 * h), (a + 5 * h, a + 7 * h)]
    right = [(a + h, a + 6 * h)]
    assert intersect(left, right) == [(a + h, a + 3 * h), (a + 5 * h, a + 6 * h)]
