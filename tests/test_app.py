import re

import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "test.sqlite"),
            "DEPLOY_SHA": "test-build",
            "DEPLOYED_AT": "2026-09-26T12:00:00Z",
            "APP_SECRET_KEY": "test-app-secret-key",
            "APP_USERNAME": "operator",
            "APP_PASSWORD": "test-password",
        }
    )
    test_client = app.test_client()
    with test_client.session_transaction() as user_session:
        user_session["username"] = "operator"
        user_session["csrf_token"] = "test-csrf-token"
    return test_client


def csrf_headers():
    return {"X-CSRF-Token": "test-csrf-token"}


def test_health_and_overview(client):
    assert client.get("/api/health").json["status"] == "healthy"
    overview = client.get("/api/overview").json
    assert overview["deploy_sha"] == "test-build"
    assert overview["deployed_at"] == "2026-09-26T12:00:00Z"
    assert overview["tasks_total"] == 0
    assert overview["requests_per_minute"] >= 1
    assert overview["p95_latency_ms"] >= 0
    assert overview["error_count"] == 0


def test_task_lifecycle(client):
    created = client.post(
        "/api/tasks", json={"title": "Ship the pipeline"}, headers=csrf_headers()
    )
    assert created.status_code == 201
    task_id = created.json["id"]

    assert client.get("/api/tasks").json[0]["title"] == "Ship the pipeline"
    assert client.patch(
        f"/api/tasks/{task_id}", json={"completed": True}, headers=csrf_headers()
    ).json["completed"]
    overview = client.get("/api/overview").json
    assert overview["tasks_completed"] == 1
    assert overview["tasks_open"] == 0

    assert client.delete(
        f"/api/tasks/{task_id}", headers=csrf_headers()
    ).json["deleted"]
    assert client.get("/api/tasks").json == []


def test_invalid_tasks_are_rejected(client):
    headers = csrf_headers()
    assert client.post("/api/tasks", json={"title": "   "}, headers=headers).status_code == 400
    assert client.post("/api/tasks", json={"title": "x" * 161}, headers=headers).status_code == 400
    assert client.post("/api/tasks", json=[{"title": "not an object"}], headers=headers).status_code == 400
    assert client.patch("/api/tasks/99", json=[], headers=headers).status_code == 400
    assert client.patch("/api/tasks/99", json={"completed": "yes"}, headers=headers).status_code == 400
    assert client.patch("/api/tasks/99", json={"completed": True}, headers=headers).status_code == 404


def test_login_protects_dashboard_and_api(client):
    with client.session_transaction() as user_session:
        user_session.clear()

    assert client.get("/").status_code == 302
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.get("/metrics").status_code == 200

    login_page = client.get("/login")
    csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', login_page.data).group(1).decode()
    assert client.post(
        "/login",
        data={"username": "operator", "password": "wrong", "csrf_token": csrf_token},
    ).status_code == 200
    assert client.post(
        "/login",
        data={"username": "operator", "password": "test-password", "csrf_token": csrf_token},
    ).status_code == 302
    assert client.get("/").status_code == 200
    with client.session_transaction() as user_session:
        csrf_token = user_session["csrf_token"]
    assert client.post("/logout", data={"csrf_token": csrf_token}).status_code == 302
    assert client.get("/api/tasks").status_code == 401


def test_task_mutations_require_csrf(client):
    response = client.post("/api/tasks", json={"title": "No token"})
    assert response.status_code == 400
    assert response.json["error"] == "Invalid or missing CSRF token."


def test_prometheus_metrics_endpoint(client):
    client.get("/api/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b"app_http_requests_total" in response.data
