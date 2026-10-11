"""Unit tests for usage recording rules. Covers TC-F-016 (no database)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.common.errors import ApiError
from app.usage.rules import compute_usage

UTC = timezone.utc
START = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
END = START + timedelta(hours=2)
AFTER = END + timedelta(minutes=1)


def run(**kwargs):
    args = dict(reservation_start=START, reservation_end=END, reservation_status="Approved", now=AFTER)
    args.update(kwargs)
    return compute_usage(
        args.pop("reservation_start"),
        args.pop("reservation_end"),
        args.pop("reservation_status"),
        args.pop("now"),
        **args,
    )


def error_of(**kwargs) -> ApiError:
    with pytest.raises(ApiError) as caught:
        run(**kwargs)
    return caught.value


def test_valid_usage_returns_whole_minutes():
    result = run(used_start=START + timedelta(minutes=5), used_end=START + timedelta(minutes=95))
    assert result.used_minutes == 90


def test_usage_may_equal_the_full_reservation():
    assert run(used_start=START, used_end=END).used_minutes == 120


def test_partial_minutes_round_down():
    assert run(used_start=START, used_end=START + timedelta(minutes=10, seconds=59)).used_minutes == 10


def test_no_show_is_zero_minutes_with_no_timestamps():
    result = run(no_show=True)
    assert (result.used_start, result.used_end, result.used_minutes) == (None, None, 0)


def test_no_show_with_times_is_rejected():
    assert error_of(no_show=True, used_start=START, used_end=END).status == 422


def test_missing_times_without_no_show_is_rejected():
    error = error_of()
    assert error.status == 422
    assert set(error.fields) == {"used_start", "used_end"}


def test_only_one_time_given_names_the_missing_field():
    assert set(error_of(used_start=START).fields) == {"used_end"}


def test_start_must_be_before_end():
    assert error_of(used_start=END - timedelta(minutes=5), used_end=END - timedelta(minutes=5)).status == 422
    assert error_of(used_start=END, used_end=START).status == 422


def test_usage_longer_than_reservation_is_rejected():
    assert error_of(used_start=START - timedelta(minutes=1), used_end=END).status == 422
    assert error_of(used_start=START, used_end=END + timedelta(minutes=1)).status == 422


@pytest.mark.parametrize("status", ["Pending", "Rejected", "Cancelled", "Completed"])
def test_only_approved_reservations_can_be_completed(status):
    error = error_of(reservation_status=status, no_show=True)
    assert (error.status, error.code) == (409, "INVALID_STATE")


def test_cannot_record_before_the_reservation_ends():
    error = error_of(now=END - timedelta(seconds=1), no_show=True)
    assert (error.status, error.code) == (409, "RESERVATION_NOT_ENDED")


def test_recording_exactly_at_the_end_is_allowed():
    assert run(now=END, no_show=True).used_minutes == 0
