"""Utilization report against a real database. Covers TC-F-017 and TC-EDGE-006."""

from datetime import date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from lab_factories import add_reservation, add_usage, add_weekly_opening, seed_world

from app.common.errors import ApiError
from app.reporting import services

IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=IST)  # Wednesday; Monday is in the past


def ist(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


@pytest.fixture()
def world(db):
    w = seed_world(db)
    for weekday in range(5):  # Monday-Friday, 09:00-17:00 = 480 minutes a day
        add_weekly_opening(db, w.l1, weekday, time(9), time(17))
    return w


def report(new_conn, world, actor=None, lab=None, start=MONDAY, end=MONDAY, now=NOW):
    return services.utilization_report(new_conn(), actor or world.admin1, lab or world.l1, start, end, now)


def row_for(result, code):
    return next(item for item in result["equipment"] if item["code"] == code)


def add_maintenance(db, equipment, start, end, by):
    db.execute(
        "INSERT INTO maintenance_blocks (equipment_id, created_by, starts_at, ends_at, reason) "
        "VALUES (%s, %s, %s, %s, 'test')",
        (equipment, by, start, end),
    )


def test_tc_f_017_srs_worked_example_gives_50_percent(new_conn, world, db):
    add_maintenance(db, world.e1, ist(MONDAY, 12), ist(MONDAY, 13), world.tech1)
    r1 = add_reservation(db, world.student1, world.e1, ist(MONDAY, 10), ist(MONDAY, 12), "Completed")
    r2 = add_reservation(db, world.student1, world.e1, ist(MONDAY, 14), ist(MONDAY, 16), "Completed")
    add_usage(db, r1, ist(MONDAY, 10), ist(MONDAY, 12), 120, world.tech1)
    add_usage(db, r2, ist(MONDAY, 14), ist(MONDAY, 15, 30), 90, world.tech1)

    e1 = row_for(report(new_conn, world), "E1")
    assert (e1["bookable_minutes"], e1["used_minutes"]) == (420, 210)
    assert e1["utilization_percent"] == 50.0 and e1["utilization_label"] == "50.0%"
    assert e1["unrecorded_reservations"] == 0


def test_equipment_with_no_activity_reports_zero_percent(new_conn, world):
    e2 = row_for(report(new_conn, world), "E2")
    assert (e2["bookable_minutes"], e2["used_minutes"], e2["utilization_percent"]) == (480, 0, 0.0)


def test_zero_bookable_minutes_displays_not_applicable(new_conn, world, db):
    add_maintenance(db, world.e1, ist(MONDAY, 8), ist(MONDAY, 18), world.tech1)  # blocks the whole day
    e1 = row_for(report(new_conn, world), "E1")
    assert e1["bookable_minutes"] == 0
    assert e1["utilization_percent"] is None and e1["utilization_label"] == "Not applicable"


def test_closed_lab_has_no_applicable_utilization(new_conn, world, db):
    saturday = date(2026, 10, 10)
    e1 = row_for(report(new_conn, world, start=saturday, end=saturday), "E1")
    assert e1["bookable_minutes"] == 0 and e1["utilization_label"] == "Not applicable"


def test_date_override_closes_the_lab(new_conn, world, db):
    db.execute(
        "INSERT INTO lab_opening_intervals (lab_id, override_date) VALUES (%s, %s)", (world.l1, MONDAY)
    )
    assert row_for(report(new_conn, world), "E1")["bookable_minutes"] == 0


def test_approved_ended_reservation_without_usage_is_unrecorded_not_used(new_conn, world, db):
    add_reservation(db, world.student1, world.e1, ist(MONDAY, 10), ist(MONDAY, 12), "Approved")
    e1 = row_for(report(new_conn, world), "E1")
    assert e1["unrecorded_reservations"] == 1
    assert e1["used_minutes"] == 0


def test_no_show_counts_as_recorded_with_zero_used(new_conn, world, db):
    r = add_reservation(db, world.student1, world.e1, ist(MONDAY, 10), ist(MONDAY, 12), "Completed")
    db.execute(
        "INSERT INTO usage_records (reservation_id, used_minutes, recorded_by) VALUES (%s, 0, %s)",
        (r, world.tech1),
    )
    e1 = row_for(report(new_conn, world), "E1")
    assert e1["unrecorded_reservations"] == 0 and e1["used_minutes"] == 0


def test_future_approved_reservation_is_not_unrecorded(new_conn, world, db):
    friday = date(2026, 10, 16)
    add_reservation(db, world.student1, world.e1, ist(friday, 10), ist(friday, 12), "Approved")
    e1 = row_for(report(new_conn, world, start=MONDAY, end=NOW.date()), "E1")
    assert e1["unrecorded_reservations"] == 0


def test_usage_is_clipped_to_the_range(new_conn, world, db):
    sunday = date(2026, 10, 11)
    r = add_reservation(db, world.student1, world.e1, ist(sunday, 23), ist(MONDAY, 11), "Completed")
    add_usage(db, r, ist(sunday, 23), ist(MONDAY, 11), 720, world.tech1)
    # SAD 4.1.2: usage is clipped to the selected date range (not to opening hours), so the
    # Monday part is 00:00-11:00 = 660 minutes and Sunday's 23:00-24:00 is excluded.
    assert row_for(report(new_conn, world), "E1")["used_minutes"] == 660


def test_multi_day_range(new_conn, world):
    e2 = row_for(report(new_conn, world, start=MONDAY, end=date(2026, 10, 13)), "E2")
    assert e2["bookable_minutes"] == 960


def test_only_the_labs_own_equipment_is_listed(new_conn, world):
    codes = [item["code"] for item in report(new_conn, world)["equipment"]]
    assert codes == ["E1", "E2"]


def test_only_the_lab_administrator_may_view(new_conn, world):
    for who in (world.tech1, world.student1, world.admin2, world.disabled_admin):
        with pytest.raises(ApiError) as caught:
            report(new_conn, world, actor=who)
        assert caught.value.status == 403


def test_unknown_lab_is_404(new_conn, world):
    with pytest.raises(ApiError) as caught:
        report(new_conn, world, lab=uuid4())
    assert caught.value.status == 404


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 10, 13), date(2026, 10, 12)),  # from after to
        (date(2026, 10, 12), date(2026, 10, 15)),  # ends after "today" (Wed 14 Oct)
        (date(2025, 1, 1), date(2026, 10, 12)),  # longer than 366 days
    ],
)
def test_invalid_ranges_are_rejected(new_conn, world, start, end):
    with pytest.raises(ApiError) as caught:
        report(new_conn, world, start=start, end=end)
    assert (caught.value.status, caught.value.code) == (422, "INVALID_RANGE")


def test_today_is_allowed_as_the_last_date(new_conn, world):
    assert report(new_conn, world, start=NOW.date(), end=NOW.date())["to_date"] == "2026-10-14"


def test_response_names_the_lab_timezone(new_conn, world):
    result = report(new_conn, world)
    assert result["timezone"] == "Asia/Kolkata" and result["from_date"] == "2026-10-12"
