from datetime import datetime, timedelta, timezone

from app.common.intervals import is_valid_interval, overlaps

T = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def test_overlapping_intervals():
    assert overlaps(T, T + 2 * H, T + H, T + 3 * H)


def test_contained_interval_overlaps():
    assert overlaps(T + H, T + 2 * H, T, T + 3 * H)


def test_identical_interval_overlaps():
    assert overlaps(T, T + H, T, T + H)


def test_adjacent_intervals_do_not_overlap():
    # TC-EDGE-001: [10:00, 11:00) and [11:00, 12:00) are allowed together.
    assert not overlaps(T, T + H, T + H, T + 2 * H)
    assert not overlaps(T + H, T + 2 * H, T, T + H)


def test_separate_intervals_do_not_overlap():
    assert not overlaps(T, T + H, T + 3 * H, T + 4 * H)


def test_interval_validity():
    assert is_valid_interval(T, T + H)
    assert not is_valid_interval(T, T)
    assert not is_valid_interval(T + H, T)
