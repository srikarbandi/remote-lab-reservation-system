
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def setup_equipment(db):
    user_id = uuid4()
    lab_id = uuid4()

    db.execute(
        "INSERT INTO users (id, identifier, password_hash) VALUES (%s, %s, %s)",
        (user_id, "shristi-test", "synthetic-test-hash")
    )

    db.execute(
        "INSERT INTO labs (id, name) VALUES (%s, %s)",
        (lab_id, "Electronics Lab")
    )

    equipment_id = db.execute(
        """
        INSERT INTO equipment (lab_id, code, name, description, active)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (lab_id, "OSC101", "Oscilloscope", "Digital oscilloscope", True)
    ).fetchone()["id"]

    db.execute(
        """
        INSERT INTO equipment (lab_id, code, name, description, active)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (lab_id, "GEN101", "Signal Generator", "Signal generator", True)
    )

    return user_id, lab_id, equipment_id


def future_monday():
    today = datetime.now(IST).date()
    days = (7 - today.weekday()) % 7
    return today + timedelta(days=days or 7)


def test_tc_f_003_catalogue(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)

    response = db_client.get(
        "/api/equipment",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_tc_f_004_search(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)

    response = db_client.get(
        "/api/equipment?name=osc",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Oscilloscope"


def test_tc_f_005_availability(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)
    day = future_monday()

    db.execute(
        """
        INSERT INTO lab_opening_intervals
        (lab_id, weekday, open_time, close_time)
        VALUES (%s, %s, %s, %s)
        """,
        (lab_id, day.weekday(), time(9), time(17))
    )

    db.execute(
        """
        INSERT INTO reservations
        (student_id, equipment_id, starts_at, ends_at, status, purpose)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            user_id, equipment_id,
            datetime.combine(day, time(10), IST),
            datetime.combine(day, time(11), IST),
            "Pending", "Testing"
        )
    )

    db.execute(
        """
        INSERT INTO maintenance_blocks
        (equipment_id, created_by, starts_at, ends_at, reason)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            equipment_id, user_id,
            datetime.combine(day, time(14), IST),
            datetime.combine(day, time(15), IST),
            "Calibration"
        )
    )

    response = db_client.get(
        f"/api/equipment/{equipment_id}/availability?date={day}",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["equipment_name"] == "Oscilloscope"
    assert data["timezone"] == "Asia/Kolkata"

    free = [
        (
            datetime.fromisoformat(slot["start"]).hour,
            datetime.fromisoformat(slot["end"]).hour
        )
        for slot in data["available"]
    ]

    assert free == [
        (9, 10),
        (11, 14),
        (15, 17)
    ]

    assert len(data["reserved"]) == 1
    assert len(data["maintenance"]) == 1


def test_tc_f_005_availability_requires_login(db_client):
    response = db_client.get(
        f"/api/equipment/{uuid4()}/availability?date={future_monday()}"
    )

    assert response.status_code == 401


def test_tc_f_005_availability_invalid_date(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)

    response = db_client.get(
        f"/api/equipment/{equipment_id}/availability?date=wrong",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 422


def test_tc_f_005_availability_unknown_equipment(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)

    response = db_client.get(
        f"/api/equipment/{uuid4()}/availability?date={future_monday()}",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 404


def test_tc_f_005_availability_closed_override(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)
    day = future_monday()

    db.execute(
        """
        INSERT INTO lab_opening_intervals
        (lab_id, weekday, open_time, close_time)
        VALUES (%s, %s, %s, %s)
        """,
        (lab_id, day.weekday(), time(9), time(17))
    )

    db.execute(
        """
        INSERT INTO lab_opening_intervals (lab_id, override_date)
        VALUES (%s, %s)
        """,
        (lab_id, day)
    )

    response = db_client.get(
        f"/api/equipment/{equipment_id}/availability?date={day}",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 200
    assert response.get_json()["available"] == []


def setup_admin(db):
    user_id = uuid4()
    lab_id = uuid4()

    db.execute(
        """
        INSERT INTO users (id, identifier, password_hash)
        VALUES (%s, %s, %s)
        """,
        (user_id, str(user_id), "test-hash")
    )

    db.execute(
        "INSERT INTO labs (id, name) VALUES (%s, %s)",
        (lab_id, str(lab_id))
    )

    db.execute(
        """
        INSERT INTO lab_memberships (user_id, lab_id, role)
        VALUES (%s, %s, 'Administrator')
        """,
        (user_id, lab_id)
    )

    return user_id, lab_id


def test_tc_f_013_admin_creates_equipment(db, db_client):
    admin_id, lab_id = setup_admin(db)

    response = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(admin_id)},
        json={
            "lab_id": str(lab_id),
            "code": "OSC200",
            "name": "Oscilloscope",
            "description": "Testing equipment"
        }
    )

    assert response.status_code == 201
    assert response.get_json()["code"] == "OSC200"


def test_tc_f_013_duplicate_equipment_code(db, db_client):
    admin_id, lab_id = setup_admin(db)

    payload = {
        "lab_id": str(lab_id),
        "code": "OSC200",
        "name": "Oscilloscope"
    }

    headers = {"X-Test-User": str(admin_id)}

    first = db_client.post("/api/equipment", headers=headers, json=payload)
    second = db_client.post("/api/equipment", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


def test_tc_f_013_admin_edits_equipment(db, db_client):
    admin_id, lab_id = setup_admin(db)

    created = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(admin_id)},
        json={
            "lab_id": str(lab_id),
            "code": "OSC201",
            "name": "Old Oscilloscope"
        }
    )

    assert created.status_code == 201
    equipment_id = created.get_json()["id"]

    response = db_client.patch(
        f"/api/equipment/{equipment_id}",
        headers={"X-Test-User": str(admin_id)},
        json={"name": "Digital Oscilloscope"}
    )

    assert response.status_code == 200
    assert response.get_json()["name"] == "Digital Oscilloscope"


def test_tc_f_013_admin_deactivates_free_equipment(db, db_client):
    admin_id, lab_id = setup_admin(db)

    created = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(admin_id)},
        json={
            "lab_id": str(lab_id),
            "code": "OSC202",
            "name": "Oscilloscope"
        }
    )

    assert created.status_code == 201
    equipment_id = created.get_json()["id"]

    response = db_client.patch(
        f"/api/equipment/{equipment_id}",
        headers={"X-Test-User": str(admin_id)},
        json={"active": False}
    )

    assert response.status_code == 200
    assert response.get_json()["active"] is False


def test_tc_f_013_deactivation_with_pending_booking_is_blocked(db, db_client):
    admin_id, lab_id = setup_admin(db)

    created = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(admin_id)},
        json={
            "lab_id": str(lab_id),
            "code": "OSC203",
            "name": "Oscilloscope"
        }
    )

    assert created.status_code == 201
    equipment_id = created.get_json()["id"]

    start = datetime.now(IST) + timedelta(days=2)
    end = start + timedelta(hours=1)

    db.execute(
        """
        INSERT INTO reservations
        (student_id, equipment_id, starts_at, ends_at, status, purpose)
        VALUES (%s, %s, %s, %s, 'Pending', 'Experiment')
        """,
        (admin_id, equipment_id, start, end)
    )

    response = db_client.patch(
        f"/api/equipment/{equipment_id}",
        headers={"X-Test-User": str(admin_id)},
        json={"active": False}
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ACTIVE_RESERVATIONS"


def test_tc_f_013_student_cannot_manage_equipment(db, db_client):
    student_id, lab_id, equipment_id = setup_equipment(db)

    response = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(student_id)},
        json={
            "lab_id": str(lab_id),
            "code": "NOTALLOWED",
            "name": "Unauthorized Equipment"
        }
    )

    assert response.status_code == 403


def test_tc_f_013_unauthenticated_equipment_create(db_client):
    response = db_client.post(
        "/api/equipment",
        json={
            "lab_id": str(uuid4()),
            "code": "OSC999",
            "name": "Oscilloscope"
        }
    )

    assert response.status_code == 401

def test_equipment_page_loads(client):
    response = client.get("/api/equipment/ui")

    assert response.status_code == 200
    assert b"Velvet OS" in response.data
    assert b"Laboratory Workspace" in response.data
    assert b"boardDate" in response.data
    assert b"scheduleEquipment" in response.data


def test_velvet_os_reservation_form(client):
    response = client.get("/api/equipment/ui")

    assert response.status_code == 200
    assert b"reservationForm" in response.data
    assert b"bookingPurpose" in response.data
    assert b"bookingSubmit" in response.data
    assert b"/api/reservations" in response.data
    assert b"Idempotency-Key" in response.data


def test_velvet_os_admin_approval_queue(client):
    response = client.get("/api/equipment/ui")

    assert response.status_code == 200
    assert b'id="approvalLab"' in response.data
    assert b'id="refreshApprovals"' in response.data
    assert b'id="approvalList"' in response.data
    assert b"scope=lab" in response.data
    assert b"status=Pending" in response.data
    assert b"expected_version:reservation.version" in response.data
    assert b"/decision" in response.data
    assert b"Enter a reason before rejecting." in response.data


def test_tc_f_004_search_term_too_long(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)

    response = db_client.get(
        "/api/equipment",
        query_string={"name": "a" * 501},
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_FIELDS"

def test_tc_f_005_inactive_equipment_has_no_available_slots(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)
    day = future_monday()

    db.execute(
        """
        INSERT INTO lab_opening_intervals
        (lab_id, weekday, open_time, close_time)
        VALUES (%s, %s, %s, %s)
        """,
        (lab_id, day.weekday(), time(9), time(17))
    )

    db.execute(
        "UPDATE equipment SET active = false WHERE id = %s",
        (equipment_id,)
    )

    response = db_client.get(
        f"/api/equipment/{equipment_id}/availability?date={day}",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["active"] is False
    assert data["available"] == []

def test_tc_f_003_catalogue_filters_by_lab(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)

    response = db_client.get(
        "/api/equipment",
        query_string={"lab_id": str(lab_id)},
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 2
    assert all(item["lab_id"] == str(lab_id) for item in data["items"])


def test_tc_f_013_rejects_invalid_description(db, db_client):
    admin_id, lab_id = setup_admin(db)

    response = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(admin_id)},
        json={
            "lab_id": str(lab_id),
            "code": "OSC300",
            "name": "Oscilloscope",
            "description": "a" * 501
        }
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_FIELDS"


def test_tc_f_013_rejects_unknown_lab(db, db_client):
    admin_id, lab_id = setup_admin(db)

    response = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(admin_id)},
        json={
            "lab_id": str(uuid4()),
            "code": "OSC301",
            "name": "Oscilloscope"
        }
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "LAB_NOT_FOUND"


def test_tc_f_013_rejects_empty_equipment_update(db, db_client):
    admin_id, lab_id = setup_admin(db)

    created = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(admin_id)},
        json={
            "lab_id": str(lab_id),
            "code": "OSC302",
            "name": "Oscilloscope"
        }
    )

    assert created.status_code == 201
    equipment_id = created.get_json()["id"]

    response = db_client.patch(
        f"/api/equipment/{equipment_id}",
        headers={"X-Test-User": str(admin_id)},
        json={}
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_FIELDS"

def test_tc_f_013_rejects_invalid_updated_description(db, db_client):
    admin_id, lab_id = setup_admin(db)

    created = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(admin_id)},
        json={
            "lab_id": str(lab_id),
            "code": "OSC303",
            "name": "Oscilloscope"
        }
    )

    assert created.status_code == 201
    equipment_id = created.get_json()["id"]

    response = db_client.patch(
        f"/api/equipment/{equipment_id}",
        headers={"X-Test-User": str(admin_id)},
        json={"description": "a" * 501}
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_FIELDS"


def test_tc_f_013_rejects_invalid_active_value(db, db_client):
    admin_id, lab_id = setup_admin(db)

    created = db_client.post(
        "/api/equipment",
        headers={"X-Test-User": str(admin_id)},
        json={
            "lab_id": str(lab_id),
            "code": "OSC304",
            "name": "Oscilloscope"
        }
    )

    assert created.status_code == 201
    equipment_id = created.get_json()["id"]

    response = db_client.patch(
        f"/api/equipment/{equipment_id}",
        headers={"X-Test-User": str(admin_id)},
        json={"active": "false"}
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_FIELDS"
