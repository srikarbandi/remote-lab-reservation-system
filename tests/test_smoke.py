def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_unknown_route_uses_error_contract(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    error = response.get_json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"]
    assert response.headers["X-Request-ID"] == error["request_id"]


def test_request_id_is_echoed(client):
    response = client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"
