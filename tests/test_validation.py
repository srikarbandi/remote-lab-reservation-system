"""Unit tests for request validation helpers (LAB-SR-005, SAD 4.3.5)."""

from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from app.common.errors import ApiError
from app.common.validation import (
    check_fields,
    clean_text,
    parse_date,
    parse_datetime,
    parse_int,
    parse_page,
    parse_uuid,
)


def status_and_fields(call):
    with pytest.raises(ApiError) as caught:
        call()
    return caught.value.status, caught.value.fields


def test_check_fields_accepts_exact_set():
    check_fields({"a": 1, "b": 2}, {"a", "b"})
    check_fields({"a": 1}, {"a"}, {"b"})


def test_check_fields_rejects_unknown_and_missing():
    status, fields = status_and_fields(lambda: check_fields({"a": 1, "role": "Administrator"}, {"a", "b"}))
    assert status == 422
    assert fields == {"b": "This field is required.", "role": "Unexpected field."}


def test_parse_datetime_requires_offset_and_returns_utc():
    parsed = parse_datetime("2026-10-15T10:00:00+05:30", "start")
    assert parsed == datetime(2026, 10, 15, 4, 30, tzinfo=timezone.utc)
    assert parsed.utcoffset().total_seconds() == 0


def test_parse_datetime_rejects_naive_and_garbage():
    for value in ("2026-10-15T10:00:00", "tomorrow", "", 5, None):
        assert status_and_fields(lambda v=value: parse_datetime(v, "start"))[0] == 422


def test_parse_date_is_strict():
    assert parse_date("2026-10-15", "from_date") == date(2026, 10, 15)
    for value in ("20261015", "2026-13-01", "2026-02-30", "15-10-2026", 20261015):
        assert status_and_fields(lambda v=value: parse_date(v, "from_date"))[0] == 422


def test_parse_uuid():
    text = "123e4567-e89b-12d3-a456-426614174000"
    assert parse_uuid(text, "id") == UUID(text)
    assert status_and_fields(lambda: parse_uuid("not-a-uuid", "id"))[0] == 422
    assert status_and_fields(lambda: parse_uuid(7, "id"))[0] == 422


def test_clean_text_trims_and_bounds():
    assert clean_text("  calibration  ", "reason") == "calibration"
    assert clean_text("x" * 500, "reason") == "x" * 500
    for value in ("", "   ", "x" * 501, 5):
        assert status_and_fields(lambda v=value: clean_text(v, "reason"))[0] == 422


def test_parse_int_rejects_bool_and_bounds():
    assert parse_int("3", "n", minimum=1) == 3
    assert status_and_fields(lambda: parse_int(True, "n"))[0] == 422
    assert status_and_fields(lambda: parse_int(0, "n", minimum=1))[0] == 422
    assert status_and_fields(lambda: parse_int("abc", "n"))[0] == 422


def test_parse_page_defaults_and_caps():
    assert parse_page({}) == (1, 20)
    assert parse_page({"page": "2", "page_size": "100"}) == (2, 100)
    assert status_and_fields(lambda: parse_page({"page_size": "101"}))[0] == 422
    assert status_and_fields(lambda: parse_page({"page": "0"}))[0] == 422
