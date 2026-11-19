from uuid import UUID

import pytest

from app import create_app
from app.auth.passwords import hash_password

BASE = "https://localhost"
PUBLIC_ENDPOINTS = {"auth.csrf_route", "equipment.ui"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SAMPLE_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture()
def route_app(pg_url, db):
    db.execute(
        "INSERT INTO users (identifier, password_hash) VALUES (%s, %s)",
        ("route-check", hash_password("RouteCheck2026!")),
    )

    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "route-check-test-secret",
            "DATABASE_URL": pg_url,
            "AUTH_COOKIE_SECURE": True,
        }
    )


def api_routes(app):
    adapter = app.url_map.bind("localhost", url_scheme="https")
    routes = []

    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue

        if rule.rule == "/api/equipment/ui":
            continue

        if rule.endpoint in PUBLIC_ENDPOINTS:
            continue

        values = {}

        for name in rule.arguments:
            converter = rule._converters[name]
            kind = type(converter).__name__

            if kind == "IntegerConverter":
                values[name] = 1
            elif kind == "FloatConverter":
                values[name] = 1.0
            else:
                values[name] = SAMPLE_ID

        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            url = adapter.build(rule.endpoint, values, method=method)
            routes.append((method, url, rule.endpoint))

    assert routes, "No API routes were discovered."
    return routes


def sign_in(client):
    csrf_response = client.get("/api/auth/csrf", base_url=BASE)
    assert csrf_response.status_code == 200

    response = client.post(
        "/api/auth/login",
        base_url=BASE,
        json={
            "identifier": "route-check",
            "password": "RouteCheck2026!",
        },
        headers={
            "X-CSRF-Token": csrf_response.get_json()["csrf_token"]
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["csrf_token"]


def test_protected_api_routes_reject_anonymous_requests(route_app):
    failures = []
    checked = 0

    for method, url, endpoint in api_routes(route_app):
        if endpoint == "auth.login_route":
            continue

        client = route_app.test_client()
        headers = {}

        if endpoint == "auth.logout_route":
            csrf = client.get(
                "/api/auth/csrf", base_url=BASE
            ).get_json()["csrf_token"]
            headers["X-CSRF-Token"] = csrf

        response = client.open(
            url,
            method=method,
            base_url=BASE,
            json={} if method in UNSAFE_METHODS else None,
            headers=headers,
        )
        checked += 1

        if response.status_code != 401:
            failures.append(
                f"{method} {url}: expected 401, got "
                f"{response.status_code}: {response.get_data(as_text=True)}"
            )

    assert checked > 0
    assert not failures, "\n".join(failures)


def test_api_writes_reject_missing_csrf_with_real_session(route_app):
    client = route_app.test_client()
    sign_in(client)
    failures = []
    checked = 0

    for method, url, endpoint in api_routes(route_app):
        if method not in UNSAFE_METHODS:
            continue

        response = client.open(
            url,
            method=method,
            base_url=BASE,
            json={},
        )
        checked += 1
        data = response.get_json(silent=True) or {}

        if (
            response.status_code != 403
            or data.get("error", {}).get("code") != "CSRF_FAILED"
        ):
            failures.append(
                f"{method} {url}: expected CSRF_FAILED/403, got "
                f"{response.status_code}: {response.get_data(as_text=True)}"
            )

    assert checked > 0
    assert not failures, "\n".join(failures)
    assert client.get("/api/auth/me", base_url=BASE).status_code == 200


def test_login_rejects_missing_csrf_without_session(route_app):
    client = route_app.test_client()
    response = client.post(
        "/api/auth/login",
        base_url=BASE,
        json={
            "identifier": "route-check",
            "password": "RouteCheck2026!",
        },
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "CSRF_FAILED"