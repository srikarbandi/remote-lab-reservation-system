
from uuid import uuid4


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

    db.execute(
        """
        INSERT INTO equipment (lab_id, code, name, description, active)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (lab_id, "OSC101", "Oscilloscope", "Digital oscilloscope", True)
    )

    db.execute(
        """
        INSERT INTO equipment (lab_id, code, name, description, active)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (lab_id, "GEN101", "Signal Generator", "Signal generator", True)
    )

    return user_id, lab_id


def test_tc_f_003_catalogue(db, db_client):
    user_id, lab_id = setup_equipment(db)

    response = db_client.get(
        "/api/equipment",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_tc_f_004_search(db, db_client):
    user_id, lab_id = setup_equipment(db)

    response = db_client.get(
        "/api/equipment?name=osc",
        headers={"X-Test-User": str(user_id)}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Oscilloscope"
