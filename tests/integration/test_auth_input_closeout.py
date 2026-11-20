import logging
from datetime import datetime, timedelta, timezone

import pytest
from lab_factories import add_weekly_opening
from test_auth_security_closeout import PASSWORD, signed_client
from test_auth_security_closeout import security_world as security_world

BASE = "https://localhost"
PAYLOADS = [
    "' OR '1'='1",
    "<script>alert('closeout')</script>",
]


@pytest.mark.parametrize("identifier", PAYLOADS)
def test_injection_identifier_cannot_login(db, security_world, identifier):
    _, app = security_world
    client = app.test_client()
    csrf = client.get(
        "/api/auth/csrf", base_url=BASE
    ).get_json()["csrf_token"]

    response = client.post(
        "/api/auth/login",
        base_url=BASE,
        json={"identifier": identifier, "password": PASSWORD},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 401, response.get_json()
    assert client.get_cookie("lab_session") is None
    assert db.execute(
        "SELECT count(*) AS n FROM sessions"
    ).fetchone()["n"] == 0


@pytest.mark.parametrize("search", PAYLOADS)
def test_search_payload_is_literal_data(db, security_world, search):
    _, app = security_world
    client, _ = signed_client(app, "s1")
    before = db.execute(
        "SELECT * FROM equipment ORDER BY id"
    ).fetchall()

    response = client.get(
        "/api/equipment",
        base_url=BASE,
        query_string={"name": search},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["items"] == []
    assert db.execute(
        "SELECT * FROM equipment ORDER BY id"
    ).fetchall() == before


@pytest.mark.parametrize("purpose", PAYLOADS)
def test_booking_payload_stays_data_and_logs_exclude_secrets(
    db, security_world, purpose, caplog, capsys
):
    world, app = security_world
    caplog.set_level(logging.DEBUG)
    client, csrf = signed_client(app, "s1")
    session_token = client.get_cookie("lab_session").value

    start = (
        datetime.now(timezone.utc) + timedelta(days=2)
    ).replace(hour=5, minute=0, second=0, microsecond=0)

    add_weekly_opening(db, world.l1, start.weekday())

    response = client.post(
        "/api/reservations",
        base_url=BASE,
        json={
            "equipment_id": str(world.e1),
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
            "purpose": purpose,
        },
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "input-closeout-booking",
        },
    )

    assert response.status_code == 201, response.get_json()
    reservation_id = response.get_json()["id"]

    rows = db.execute(
        "SELECT id, student_id, purpose FROM reservations"
    ).fetchall()

    assert len(rows) == 1
    assert str(rows[0]["id"]) == reservation_id
    assert rows[0]["student_id"] == world.student1
    assert rows[0]["purpose"] == purpose

    history = client.get(
        "/api/reservations?scope=mine", base_url=BASE
    )

    assert history.status_code == 200
    assert history.mimetype == "application/json"
    assert history.get_json()["items"][0]["purpose"] == purpose

    events = db.execute(
        "SELECT * FROM audit_events WHERE actor_id = %s",
        (world.student1,),
    ).fetchall()

    assert any(
        event["action"] == "reservation.submit" for event in events
    )

    captured = capsys.readouterr()
    recorded = caplog.text + captured.out + captured.err + str(events)

    for secret in (PASSWORD, session_token, csrf):
        assert secret not in recorded

    assert db.execute(
        "SELECT count(*) AS n FROM equipment"
    ).fetchone()["n"] == 3