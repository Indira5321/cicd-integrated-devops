import os
import secrets
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

load_dotenv()

REQUEST_COUNT = Counter(
    "app_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "app_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)
TASK_ACTIONS = Counter("app_task_actions_total", "Task actions", ["action"])
APP_STARTED_AT = datetime.now(timezone.utc).isoformat()
RECENT_REQUESTS = deque(maxlen=2000)
REQUESTS_LOCK = threading.Lock()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("APP_SECRET_KEY") or secrets.token_urlsafe(32),
        APP_SECRET_KEY=os.environ.get("APP_SECRET_KEY", ""),
        APP_USERNAME=os.environ.get("APP_USERNAME", ""),
        APP_PASSWORD=os.environ.get("APP_PASSWORD", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_REFRESH_EACH_REQUEST=False,
        DATABASE_PATH=os.environ.get(
            "DATABASE_PATH", str(Path(app.instance_path) / "tasks.sqlite")
        ),
        DEPLOY_SHA=os.environ.get("DEPLOY_SHA", "local"),
        DEPLOYED_AT=os.environ.get("DEPLOYED_AT", "local"),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE_PATH"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None):
        database = g.pop("db", None)
        if database is not None:
            database.close()

    with app.app_context():
        database = get_db()
        database.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )"""
        )
        database.commit()

    @app.before_request
    def start_timer():
        request.environ["request_started_at"] = time.perf_counter()

    def auth_is_configured():
        return all(
            app.config.get(key)
            for key in ("APP_SECRET_KEY", "APP_USERNAME", "APP_PASSWORD")
        )

    def validate_csrf():
        expected = session.get("csrf_token", "")
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            if request.path.startswith("/api/"):
                return jsonify(error="Invalid or missing CSRF token."), 400
            abort(400, description="Invalid or missing security token.")
        return None

    @app.before_request
    def require_authentication():
        public_endpoints = {"static", "login", "health", "metrics"}
        if request.endpoint in public_endpoints:
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                return validate_csrf()
            return None

        if not auth_is_configured():
            if request.path.startswith("/api/"):
                return jsonify(error="Application login is not configured."), 503
            return redirect(url_for("login"))

        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify(error="Authentication required."), 401
            return redirect(url_for("login", next=request.full_path))

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            return validate_csrf()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("username"):
            return redirect(url_for("dashboard"))

        csrf_token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
        if not auth_is_configured():
            return render_template(
                "login.html", csrf_token=csrf_token, setup_required=True
            ), 503

        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            valid_username = secrets.compare_digest(username, app.config["APP_USERNAME"])
            valid_password = secrets.compare_digest(password, app.config["APP_PASSWORD"])
            if valid_username and valid_password:
                next_path = request.args.get("next", "")
                parsed_next = urlsplit(next_path)
                session.clear()
                session.permanent = True
                session["username"] = username
                session["csrf_token"] = secrets.token_urlsafe(32)
                if next_path.startswith("/") and not next_path.startswith("//") and not parsed_next.netloc:
                    return redirect(next_path)
                return redirect(url_for("dashboard"))
            flash("The username or password did not match.")

        return render_template("login.html", csrf_token=csrf_token, setup_required=False)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.after_request
    def record_request(response):
        endpoint = request.endpoint or "unknown"
        REQUEST_COUNT.labels(request.method, endpoint, str(response.status_code)).inc()
        started_at = request.environ.get("request_started_at")
        if started_at is not None:
            duration = time.perf_counter() - started_at
            REQUEST_LATENCY.labels(request.method, endpoint).observe(duration)
            with REQUESTS_LOCK:
                RECENT_REQUESTS.append((time.time(), duration, response.status_code))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.endpoint not in {"static", "metrics", "health"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def dashboard():
        csrf_token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return render_template(
            "index.html", csrf_token=csrf_token, current_user=session["username"]
        )

    @app.get("/api/health")
    def health():
        return jsonify(status="healthy", timestamp=datetime.now(timezone.utc).isoformat())

    @app.get("/api/overview")
    def overview():
        row = get_db().execute(
            "SELECT COUNT(*) AS total, SUM(completed) AS completed FROM tasks"
        ).fetchone()
        total = row["total"]
        completed = row["completed"] or 0
        cutoff = time.time() - 60
        with REQUESTS_LOCK:
            recent = [sample for sample in RECENT_REQUESTS if sample[0] >= cutoff]
        durations = sorted(sample[1] for sample in recent)
        p95_index = max(0, int(len(durations) * 0.95) - 1)
        error_count = sum(sample[2] >= 500 for sample in recent)
        return jsonify(
            tasks_total=total,
            tasks_completed=completed,
            tasks_open=total - completed,
            requests_per_minute=len(recent),
            p95_latency_ms=round(durations[p95_index] * 1000) if durations else 0,
            error_rate=round(error_count / len(recent) * 100, 2) if recent else 0,
            error_count=error_count,
            deploy_sha=app.config["DEPLOY_SHA"],
            deployed_at=app.config["DEPLOYED_AT"],
            started_at=APP_STARTED_AT,
        )

    @app.get("/api/tasks")
    def list_tasks():
        rows = get_db().execute(
            "SELECT id, title, completed, created_at FROM tasks ORDER BY id DESC"
        ).fetchall()
        return jsonify(
            [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "completed": bool(row["completed"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        )

    @app.post("/api/tasks")
    def create_task():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        title = payload.get("title", "")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
            return jsonify(error="Title must contain 1 to 160 characters."), 400
        created_at = datetime.now(timezone.utc).isoformat()
        database = get_db()
        cursor = database.execute(
            "INSERT INTO tasks (title, created_at) VALUES (?, ?)",
            (title.strip(), created_at),
        )
        database.commit()
        TASK_ACTIONS.labels("created").inc()
        task = database.execute(
            "SELECT id, title, completed, created_at FROM tasks WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify(
            id=task["id"],
            title=task["title"],
            completed=bool(task["completed"]),
            created_at=task["created_at"],
        ), 201

    @app.patch("/api/tasks/<int:task_id>")
    def update_task(task_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        completed = payload.get("completed")
        if not isinstance(completed, bool):
            return jsonify(error="A boolean completed value is required."), 400
        database = get_db()
        cursor = database.execute(
            "UPDATE tasks SET completed = ? WHERE id = ?",
            (int(completed), task_id),
        )
        database.commit()
        if cursor.rowcount == 0:
            return jsonify(error="Task not found."), 404
        TASK_ACTIONS.labels("updated").inc()
        return jsonify(id=task_id, completed=completed)

    @app.delete("/api/tasks/<int:task_id>")
    def delete_task(task_id):
        database = get_db()
        cursor = database.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        database.commit()
        if cursor.rowcount == 0:
            return jsonify(error="Task not found."), 404
        TASK_ACTIONS.labels("deleted").inc()
        return jsonify(deleted=True)

    @app.get("/metrics")
    def metrics():
        return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
