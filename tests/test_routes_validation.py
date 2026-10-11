"""HTTP contract checks that need no database: authentication, JSON shape, field validation."""

from uuid import uuid4

import pytest

USER = {"X-Test-User": str(uuid4())}
ID = str(uuid4())

PROTECTED = [
    ("post", "/api/maintenance"),
    ("patch", f"/api/maintenance/{ID}"),
    ("delete", f"/api/maintenance/{ID}?expected_version=1"),
    ("post", f"/api/reservations/{ID}/usage"),
    ("get", f"/api/reports/utilization?lab_id={ID}&from_date=2026-10-01&to_date=2026-10-02"),
    ("get", "/api/notifications"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_endpoints_require_login(client, method, path):
    response = getattr(client, method)(path, json={})
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("path", ["/api/maintenance", f"/api/reservations/{ID}/usage"])
def test_non_json_body_is_400(client, path):
    response = client.post(path, data="not json", headers=USER)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "MALFORMED_JSON"


def valid_block():
    return {
        "equipment_id": ID,
        "start": "2026-10-20T10:00:00+05:30",
        "end": "2026-10-20T12:00:00+05:30",
        "reason": "Calibration",
    }


@pytest.mark.parametrize(
    ("change", "bad_field"),
    [
        ({"role": "Administrator"}, "role"),  # unknown writable field
        ({"start": "2026-10-20T10:00:00"}, "start"),  # no UTC offset
        ({"end": "next week"}, "end"),
        ({"equipment_id": "not-a-uuid"}, "equipment_id"),
        ({"reason": "   "}, "reason"),
        ({"reason": "x" * 501}, "reason"),
    ],
)
def test_maintenance_create_validation(client, change, bad_field):
    body = {**valid_block(), **change}
    response = client.post("/api/maintenance", json=body, headers=USER)
    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["code"] == "INVALID_FIELDS" and bad_field in error["fields"]
    assert error["request_id"]


def test_maintenance_create_missing_field(client):
    body = valid_block()
    del body["reason"]
    response = client.post("/api/maintenance", json=body, headers=USER)
    assert response.status_code == 422 and "reason" in response.get_json()["error"]["fields"]


def test_maintenance_update_needs_a_change_and_a_version(client):
    assert (
        client.patch(f"/api/maintenance/{ID}", json={"expected_version": 1}, headers=USER).status_code == 422
    )
    assert client.patch(f"/api/maintenance/{ID}", json={"reason": "x"}, headers=USER).status_code == 422


def test_maintenance_delete_needs_a_version(client):
    response = client.delete(f"/api/maintenance/{ID}", headers=USER)
    assert response.status_code == 400  # no query string and no JSON body


def test_usage_body_validation(client):
    path = f"/api/reservations/{ID}/usage"
    cases = [
        {"no_show": True},  # expected_version missing
        {"expected_version": 1, "no_show": "yes"},
        {"expected_version": 1, "used_start": "2026-10-15T10:00:00"},
        {"expected_version": 1, "status": "Completed"},  # unknown field
    ]
    for body in cases:
        assert client.post(path, json=body, headers=USER).status_code == 422, body


def test_report_query_validation(client):
    base = "/api/reports/utilization"
    assert client.get(base, headers=USER).status_code == 422
    assert (
        client.get(f"{base}?lab_id={ID}&from_date=2026-13-01&to_date=2026-10-02", headers=USER).status_code
        == 422
    )
    assert (
        client.get(f"{base}?lab_id=nope&from_date=2026-10-01&to_date=2026-10-02", headers=USER).status_code
        == 422
    )


def test_notification_paging_validation(client):
    assert client.get("/api/notifications?page=0", headers=USER).status_code == 422
    assert client.get("/api/notifications?page_size=101", headers=USER).status_code == 422


def test_database_outage_returns_503_contract(app):
    # Nothing listens on port 1, so the connection is refused immediately (SAD 4.3.5: 503, no internals leaked).
    app.config["DATABASE_URL"] = "postgresql://lab@127.0.0.1:1/none?connect_timeout=2"
    response = app.test_client().get("/api/notifications", headers=USER)
    assert response.status_code == 503
    error = response.get_json()["error"]
    assert error["code"] == "DATABASE_UNAVAILABLE"
    assert "127.0.0.1" not in error["message"]
