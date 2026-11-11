
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


def test_availability_requires_login(db_client):
    response = db_client.get(
        f"/api/equipment/{uuid4()}/availability?date={future_monday()}"
    )

    assert response.status_code == 401


def test_availability_invalid_date(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)

    response = db_client.get(
        f"/api/equipment/{equipment_id}/availability?date=wrong",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 422


def test_availability_unknown_equipment(db, db_client):
    user_id, lab_id, equipment_id = setup_equipment(db)

    response = db_client.get(
        f"/api/equipment/{uuid4()}/availability?date={future_monday()}",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 404


def test_availability_closed_override(db, db_client):
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


def test_duplicate_equipment_code(db, db_client):
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


def test_admin_edits_equipment(db, db_client):
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


def test_admin_deactivates_free_equipment(db, db_client):
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


def test_deactivation_with_pending_booking_is_blocked(db, db_client):
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


def test_student_cannot_manage_equipment(db, db_client):
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


def test_unauthenticated_equipment_create(db_client):
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