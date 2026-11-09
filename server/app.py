from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import current_version
from .config import AppConfig, load_config, resource_dir, save_update_config
from .db import Database
from .schemas import (
    AgentRolloutCreate, ApiKeyCreate, ApiKeyState, AssetDeleteRequest, AssetPatch, AssetRetireRequest,
    CampaignCreate, DepartmentCreate, DepartmentRename, DepartmentState, HeartbeatRequest,
    InventoryRequest, LoginRequest, PolicyUpdate, SetupRequest, UpdateConfigRequest,
    UpdateRollbackRequest, UserCreate, WallpaperExclusionCreate,
)
from .security import constant_time_equal, hash_password, random_token, token_hash, verify_password
from .store import asset_detail, effective_policy, iso, list_assets, pending_campaigns, save_inventory, upsert_identity, utc_now
from .updater import MAX_BUNDLE_BYTES, UpdateError, request_rollback, stage_release_bundle, update_root, update_state
from .agent_updates import (
    MAX_AGENT_BUNDLE_BYTES, AgentUpdateError, agent_release_root, store_agent_bundle, verify_agent_bundle,
)


SESSION_COOKIE = "hos_monitor_session"
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
MAX_WALLPAPER_BYTES = 10 * 1024 * 1024


def _csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _wallpaper_root(config: AppConfig) -> Path:
    path = (config.data_dir / "wallpaper").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wallpaper_payload(connection: sqlite3.Connection, config: AppConfig) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM wallpaper_settings WHERE id=1").fetchone()
    if row is None or not bool(row["enabled"]):
        return {"enabled": False, "revision": ""}
    image = _wallpaper_root(config) / str(row["filename"])
    if not image.is_file():
        return {"enabled": False, "revision": ""}
    return {
        "enabled": True,
        "revision": row["revision"],
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "mime_type": row["mime_type"],
        "file_extension": "png" if row["mime_type"] == "image/png" else "jpg",
        "style": row["style"],
        "locked": bool(row["locked"]),
        "download_url": f"/agent/v1/wallpaper/{row['revision']}",
        "updated_at": row["updated_at"],
    }


def _wallpaper_file(request: Request, revision: str) -> tuple[Path, str]:
    with _database(request).connect() as connection:
        row = connection.execute(
            "SELECT filename,mime_type,enabled,revision FROM wallpaper_settings WHERE id=1"
        ).fetchone()
    if row is None or not bool(row["enabled"]) or row["revision"] != revision:
        raise HTTPException(status_code=404, detail="wallpaper revision not found")
    path = _wallpaper_root(_config(request)) / str(row["filename"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="wallpaper file not found")
    return path, str(row["mime_type"])


def _database(request: Request) -> Database:
    return request.app.state.database


def _config(request: Request) -> AppConfig:
    return request.app.state.config


def _session_user(request: Request) -> dict[str, Any] | None:
    raw_token = request.cookies.get(SESSION_COOKIE, "")
    if not raw_token:
        return None
    database = _database(request)
    now = iso()
    with database.connect() as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
        row = connection.execute(
            """SELECT u.id,u.username,u.role,s.csrf_token,s.expires_at
               FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1""",
            (token_hash(raw_token), now),
        ).fetchone()
        return dict(row) if row else None


def require_user(request: Request) -> dict[str, Any]:
    user = _session_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    return user


def require_admin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return user


def verify_csrf(request: Request, user: dict[str, Any]) -> None:
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not constant_time_equal(supplied, user["csrf_token"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid CSRF token")


def require_agent(request: Request, x_agent_token: str = Header(default="")) -> None:
    if not x_agent_token or not constant_time_equal(x_agent_token, _config(request).agent_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid agent token")


def require_read_access(request: Request, x_api_key: str = Header(default="")) -> dict[str, Any]:
    database = _database(request)
    if x_api_key:
        now = iso()
        digest = token_hash(x_api_key)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT id,name,scope FROM api_keys WHERE key_hash=? AND enabled=1", (digest,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")
            connection.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now, row["id"]))
            return {"kind": "api_key", **dict(row)}
    user = _session_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key or login required")
    return {"kind": "user", **user}


def _create_session(database: Database, user_id: int, hours: int) -> tuple[str, str, str]:
    token = random_token()
    csrf = random_token(20)
    now = utc_now()
    expires = iso(now + timedelta(hours=hours))
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES (?,?,?,?,?)",
            (token_hash(token), user_id, csrf, expires, iso(now)),
        )
    return token, csrf, expires


def _confirm_admin_password(database: Database, user: dict[str, Any], password: str) -> None:
    with database.connect() as connection:
        row = connection.execute("SELECT password_hash FROM users WHERE id=? AND enabled=1", (user["id"],)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=403, detail="admin password is incorrect")


def _agent_update_payload(
    connection: sqlite3.Connection, config: AppConfig, asset_id: int, department: str,
    agent_version: str, report_release_id: int | None, report_status: str,
    report_error: str, now: str,
) -> dict[str, Any]:
    if report_release_id is not None and report_status:
        receipt = connection.execute(
            """SELECT rr.rollout_id FROM agent_rollout_receipts rr
               JOIN agent_rollouts r ON r.id=rr.rollout_id
               WHERE rr.asset_id=? AND r.release_id=? ORDER BY r.id DESC LIMIT 1""",
            (asset_id, report_release_id),
        ).fetchone()
        if receipt is not None:
            safe_status = report_status if report_status in {"pending", "downloading", "installing", "applied", "failed"} else "failed"
            connection.execute(
                """UPDATE agent_rollout_receipts SET status=?,error_message=?,updated_at=?
                   WHERE rollout_id=? AND asset_id=?""",
                (safe_status, report_error[:500], now, receipt["rollout_id"], asset_id),
            )

    rollout = connection.execute(
        """SELECT r.id AS rollout_id,ar.id AS release_id,ar.version,ar.filename,ar.sha256,ar.size_bytes
           FROM agent_rollouts r JOIN agent_releases ar ON ar.id=r.release_id
           WHERE ar.enabled=1 AND r.expires_at>? AND (
             r.target_type='all' OR
             (r.target_type='department' AND r.target_value=?) OR
             (r.target_type='asset' AND r.target_value=?))
           ORDER BY r.id DESC LIMIT 1""",
        (now, department, str(asset_id)),
    ).fetchone()
    if rollout is None:
        return {"enabled": False}
    if agent_version == rollout["version"]:
        connection.execute(
            """INSERT INTO agent_rollout_receipts
               (rollout_id,asset_id,delivered_at,status,error_message,updated_at)
               VALUES (?,?,?,'applied','',?)
               ON CONFLICT(rollout_id,asset_id) DO UPDATE SET status='applied',error_message='',updated_at=excluded.updated_at""",
            (rollout["rollout_id"], asset_id, now, now),
        )
        return {"enabled": False}
    receipt = connection.execute(
        "SELECT status FROM agent_rollout_receipts WHERE rollout_id=? AND asset_id=?",
        (rollout["rollout_id"], asset_id),
    ).fetchone()
    if receipt is not None and receipt["status"] in {"applied", "failed"}:
        return {"enabled": False}
    release_file = agent_release_root(config) / str(rollout["filename"])
    if not release_file.is_file():
        return {"enabled": False}
    connection.execute(
        """INSERT INTO agent_rollout_receipts
           (rollout_id,asset_id,delivered_at,status,error_message,updated_at)
           VALUES (?,?,?,'pending','',?)
           ON CONFLICT(rollout_id,asset_id) DO UPDATE SET updated_at=excluded.updated_at""",
        (rollout["rollout_id"], asset_id, now, now),
    )
    return {
        "enabled": True, "release_id": int(rollout["release_id"]), "version": rollout["version"],
        "sha256": rollout["sha256"], "size_bytes": int(rollout["size_bytes"]),
        "download_url": f"/agent/v1/update/{rollout['release_id']}",
    }


def _set_session_cookie(response: Response, token: str, config: AppConfig) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=config.session_hours * 3600,
        httponly=True, secure=config.cookie_secure, samesite="strict", path="/",
    )


def create_app(config_path: str | Path | None = None) -> FastAPI:
    config = load_config(config_path)
    database = Database(config.database_path)
    database.initialize(iso())
    app = FastAPI(
        title="HosMonitor", version=current_version(),
        description="On-premise IT asset monitoring and read-only integration API",
        docs_url=None, redoc_url=None,
    )
    app.state.config = config
    app.state.database = database

    static_dir = resource_dir() / "server" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        maintenance = update_root(app.state.config) / "maintenance.json"
        if maintenance.exists() and request.url.path not in {"/health", "/api/ui/updates/status"}:
            return JSONResponse({"detail": "system update is in progress"}, status_code=503,
                                headers={"Retry-After": "15"})
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                length = int(request.headers.get("content-length", "0") or 0)
            except ValueError:
                return JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
            if request.url.path == "/api/ui/updates/import":
                request_limit = MAX_BUNDLE_BYTES
            elif request.url.path == "/api/ui/agent-updates/releases":
                request_limit = MAX_AGENT_BUNDLE_BYTES
            else:
                request_limit = 16 * 1024 * 1024
            if length > request_limit:
                return JSONResponse({"detail": "request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "time": iso(), "version": current_version()}

    @app.get("/control/v1/status", include_in_schema=False)
    def local_control_status(request: Request):
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            raise HTTPException(status_code=403, detail="local control only")
        with _database(request).connect() as connection:
            assets = list_assets(connection, page=1, page_size=10_000)
        return {
            "status": "ok", "version": current_version(), "port": _config(request).port,
            "agents_registered": assets["total"],
            "agents_online": sum(1 for item in assets["items"] if item["online"]),
            "time": iso(),
        }

    @app.get("/api/ui/bootstrap")
    def bootstrap(request: Request):
        with _database(request).connect() as connection:
            setup_required = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        user = _session_user(request)
        return {"setup_required": setup_required, "user": user, "version": current_version()}

    @app.post("/api/ui/setup", status_code=201)
    def setup(payload: SetupRequest, request: Request, response: Response):
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            raise HTTPException(status_code=403, detail="first setup is allowed from server localhost only")
        database = _database(request)
        now = iso()
        try:
            password_hash = hash_password(payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with database.transaction() as connection:
            if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 0:
                raise HTTPException(status_code=409, detail="setup already completed")
            cursor = connection.execute(
                "INSERT INTO users(username,password_hash,role,created_at) VALUES (?,?, 'admin',?)",
                (payload.username.strip(), password_hash, now),
            )
            user_id = int(cursor.lastrowid)
        token, csrf, expires = _create_session(database, user_id, _config(request).session_hours)
        _set_session_cookie(response, token, _config(request))
        return {"username": payload.username.strip(), "role": "admin", "csrf_token": csrf, "expires_at": expires}

    @app.post("/api/ui/login")
    def login(payload: LoginRequest, request: Request, response: Response):
        database = _database(request)
        with database.connect() as connection:
            row = connection.execute(
                "SELECT id,username,password_hash,role FROM users WHERE username=? AND enabled=1",
                (payload.username.strip(),),
            ).fetchone()
        if row is None or not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="invalid username or password")
        token, csrf, expires = _create_session(database, int(row["id"]), _config(request).session_hours)
        _set_session_cookie(response, token, _config(request))
        return {"username": row["username"], "role": row["role"], "csrf_token": csrf, "expires_at": expires}

    @app.post("/api/ui/logout")
    def logout(request: Request, response: Response, user: dict[str, Any] = Depends(require_user)):
        verify_csrf(request, user)
        raw = request.cookies.get(SESSION_COOKIE, "")
        if raw:
            with _database(request).connect() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(raw),))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/ui/session")
    def session(user: dict[str, Any] = Depends(require_user)):
        return user

    @app.post("/agent/v1/heartbeat", dependencies=[Depends(require_agent)])
    def agent_heartbeat(payload: HeartbeatRequest, request: Request):
        database = _database(request)
        now = iso()
        with database.transaction() as connection:
            asset_id = upsert_identity(connection, payload, now)
            connection.execute(
                """INSERT INTO monitor_observations(asset_id,monitor_type,observed_at,status,severity,payload_json)
                   VALUES (?,'heartbeat',?,'online','info','{}')
                   ON CONFLICT(asset_id,monitor_type) DO UPDATE SET
                     observed_at=excluded.observed_at,status='online',severity='info',payload_json='{}'""",
                (asset_id, now),
            )
            asset = connection.execute("SELECT department,retired_at FROM assets WHERE id=?", (asset_id,)).fetchone()
            policy = effective_policy(connection, asset["department"])
            if asset["retired_at"] is not None:
                campaigns = []
                wallpaper = {"enabled": False, "revision": ""}
                agent_update = {"enabled": False}
            else:
                campaigns = pending_campaigns(connection, asset_id, asset["department"], now)
                excluded = connection.execute(
                    "SELECT 1 FROM wallpaper_exclusions WHERE asset_id=?", (asset_id,)
                ).fetchone() is not None
                wallpaper = {"enabled": False, "revision": ""} if excluded else _wallpaper_payload(
                    connection, _config(request)
                )
                agent_update = _agent_update_payload(
                    connection, _config(request), asset_id, asset["department"], payload.agent_version,
                    payload.agent_update_release_id, payload.agent_update_status, payload.agent_update_error, now,
                )
        return {
            "asset_id": asset_id, "server_time": now, "policy": policy,
            "collect_requests": campaigns, "wallpaper": wallpaper, "agent_update": agent_update,
        }

    @app.get("/agent/v1/update/{release_id}", dependencies=[Depends(require_agent)])
    def download_agent_update(release_id: int, request: Request):
        with _database(request).connect() as connection:
            row = connection.execute(
                "SELECT filename FROM agent_releases WHERE id=? AND enabled=1", (release_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Agent release not found")
        path = agent_release_root(_config(request)) / str(row["filename"])
        if not path.is_file() or path.parent != agent_release_root(_config(request)):
            raise HTTPException(status_code=404, detail="Agent release file not found")
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @app.get("/agent/v1/wallpaper/{revision}", dependencies=[Depends(require_agent)])
    def agent_wallpaper(revision: str, request: Request):
        if not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise HTTPException(status_code=404, detail="wallpaper revision not found")
        path, mime_type = _wallpaper_file(request, revision)
        return FileResponse(path, media_type=mime_type, filename=path.name)

    @app.post("/agent/v1/inventory", dependencies=[Depends(require_agent)])
    def agent_inventory(payload: InventoryRequest, request: Request):
        asset_id = save_inventory(_database(request), payload)
        return {"ok": True, "asset_id": asset_id, "received_at": iso()}

    @app.get("/api/v1/assets")
    def public_assets(
        request: Request, _: dict[str, Any] = Depends(require_read_access),
        search: str = "", department: str = "", os_name: str = "",
        online: bool | None = None, retired: bool = False, page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ):
        with _database(request).connect() as connection:
            return list_assets(connection, search=search, department=department, os_name=os_name,
                               online=online, retired=retired, page=page, page_size=page_size)

    @app.get("/api/v1/assets/{asset_id}")
    def public_asset(asset_id: int, request: Request, _: dict[str, Any] = Depends(require_read_access)):
        with _database(request).connect() as connection:
            result = asset_detail(connection, asset_id)
        if result is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return result

    @app.get("/api/v1/monitor-types")
    def public_monitor_types(request: Request, _: dict[str, Any] = Depends(require_read_access)):
        with _database(request).connect() as connection:
            return {"items": [dict(row) for row in connection.execute(
                "SELECT name,display_name,schema_version,enabled FROM monitor_types ORDER BY name"
            )]}

    @app.get("/api/ui/dashboard")
    def dashboard(request: Request, _: dict[str, Any] = Depends(require_user)):
        with _database(request).connect() as connection:
            assets = list_assets(connection, page=1, page_size=10_000)
            departments = [row[0] for row in connection.execute(
                "SELECT name FROM departments WHERE enabled=1 ORDER BY name COLLATE NOCASE"
            )]
            retired_total = int(connection.execute(
                "SELECT COUNT(*) FROM assets WHERE retired_at IS NOT NULL"
            ).fetchone()[0])
        items = assets["items"]
        return {
            "total": assets["total"],
            "online": sum(1 for item in items if item["online"]),
            "offline": sum(1 for item in items if not item["online"]),
            "disk_warning": sum(1 for item in items if item["min_disk_free_percent"] is not None and item["min_disk_free_percent"] < 15),
            "ram_warning": sum(1 for item in items if item["ram_used_percent"] >= 85),
            "retired": retired_total,
            "departments": departments,
        }

    @app.patch("/api/ui/assets/{asset_id}")
    def update_asset(payload: AssetPatch, asset_id: int, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        with _database(request).connect() as connection:
            department = payload.department.strip()
            if department and connection.execute(
                "SELECT 1 FROM departments WHERE name=? AND enabled=1", (department,)
            ).fetchone() is None:
                raise HTTPException(status_code=422, detail="department must be selected from the active list")
            cursor = connection.execute(
                "UPDATE assets SET display_name=?,asset_tag=?,department=?,metadata_locked=1 WHERE id=?",
                (payload.display_name.strip(), payload.asset_tag.strip(), department, asset_id),
            )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="asset not found")
        return {"ok": True}

    @app.post("/api/ui/assets/{asset_id}/retire")
    def retire_asset(
        payload: AssetRetireRequest, asset_id: int, request: Request,
        user: dict[str, Any] = Depends(require_admin),
    ):
        verify_csrf(request, user)
        with _database(request).transaction() as connection:
            asset = connection.execute("SELECT retired_at FROM assets WHERE id=?", (asset_id,)).fetchone()
            if asset is None:
                raise HTTPException(status_code=404, detail="asset not found")
            if asset["retired_at"] is not None:
                raise HTTPException(status_code=409, detail="asset is already retired")
            connection.execute(
                "UPDATE assets SET retired_at=?,retired_by=?,retired_reason=? WHERE id=?",
                (iso(), user["id"], payload.reason.strip(), asset_id),
            )
        return {"ok": True}

    @app.post("/api/ui/assets/{asset_id}/restore")
    def restore_asset(asset_id: int, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        with _database(request).connect() as connection:
            cursor = connection.execute(
                "UPDATE assets SET retired_at=NULL,retired_by=NULL,retired_reason='' WHERE id=? AND retired_at IS NOT NULL",
                (asset_id,),
            )
            exists = connection.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone()
        if cursor.rowcount == 0:
            if exists is None:
                raise HTTPException(status_code=404, detail="asset not found")
            raise HTTPException(status_code=409, detail="asset is not retired")
        return {"ok": True}

    @app.delete("/api/ui/assets/{asset_id}")
    def delete_asset(
        payload: AssetDeleteRequest, asset_id: int, request: Request,
        user: dict[str, Any] = Depends(require_admin),
    ):
        verify_csrf(request, user)
        if payload.confirmation.strip() != "DELETE":
            raise HTTPException(status_code=422, detail="confirmation must be DELETE")
        _confirm_admin_password(_database(request), user, payload.admin_password)
        with _database(request).transaction() as connection:
            asset = asset_detail(connection, asset_id)
            if asset is None:
                raise HTTPException(status_code=404, detail="asset not found")
            if not asset["retired"]:
                raise HTTPException(status_code=409, detail="asset must be retired before permanent deletion")
            if asset["online"]:
                raise HTTPException(status_code=409, detail="online asset cannot be permanently deleted")
            connection.execute("DELETE FROM assets WHERE id=?", (asset_id,))
        return {"ok": True, "deleted_asset_id": asset_id}

    @app.get("/api/ui/departments")
    def departments(request: Request, _: dict[str, Any] = Depends(require_user)):
        with _database(request).connect() as connection:
            rows = connection.execute(
                """SELECT d.id,d.name,d.enabled,d.created_at,
                   (SELECT COUNT(*) FROM assets a WHERE a.department=d.name AND a.retired_at IS NULL) AS asset_count
                   FROM departments d ORDER BY d.enabled DESC,d.name COLLATE NOCASE"""
            ).fetchall()
        return {"items": [{**dict(row), "enabled": bool(row["enabled"])} for row in rows]}

    @app.post("/api/ui/departments", status_code=201)
    def create_department(payload: DepartmentCreate, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="department name is required")
        try:
            with _database(request).connect() as connection:
                if connection.execute(
                    "SELECT 1 FROM department_aliases WHERE alias=? COLLATE NOCASE", (name,)
                ).fetchone() is not None:
                    raise HTTPException(status_code=409, detail="department name is reserved by a previous name")
                cursor = connection.execute(
                    "INSERT INTO departments(name,enabled,created_at) VALUES (?,1,?)", (name, iso())
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="department already exists") from exc
        return {"id": cursor.lastrowid, "name": name, "enabled": True}

    @app.patch("/api/ui/departments/{department_id}")
    def update_department_state(
        payload: DepartmentState, department_id: int, request: Request,
        user: dict[str, Any] = Depends(require_admin),
    ):
        verify_csrf(request, user)
        with _database(request).connect() as connection:
            cursor = connection.execute(
                "UPDATE departments SET enabled=? WHERE id=?", (int(payload.enabled), department_id)
            )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="department not found")
        return {"ok": True}

    @app.put("/api/ui/departments/{department_id}/name")
    def rename_department(
        payload: DepartmentRename, department_id: int, request: Request,
        user: dict[str, Any] = Depends(require_admin),
    ):
        verify_csrf(request, user)
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="department name is required")
        try:
            with _database(request).transaction() as connection:
                row = connection.execute(
                    "SELECT name FROM departments WHERE id=?", (department_id,)
                ).fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="department not found")
                old_name = str(row["name"])
                if name == old_name:
                    return {"ok": True, "id": department_id, "name": name}
                if connection.execute(
                    "SELECT 1 FROM departments WHERE id<>? AND name=? COLLATE NOCASE",
                    (department_id, name),
                ).fetchone() is not None:
                    raise HTTPException(status_code=409, detail="department already exists")
                if connection.execute(
                    "SELECT 1 FROM department_aliases WHERE alias=? COLLATE NOCASE", (name,)
                ).fetchone() is not None:
                    raise HTTPException(status_code=409, detail="department name is reserved by a previous name")
                connection.execute(
                    "INSERT INTO department_aliases(department_id,alias,created_at) VALUES (?,?,?)",
                    (department_id, old_name, iso()),
                )
                connection.execute("UPDATE departments SET name=? WHERE id=?", (name, department_id))
                connection.execute("UPDATE assets SET department=? WHERE department=?", (name, old_name))
                connection.execute(
                    "UPDATE policies SET scope_value=? WHERE scope_type='department' AND scope_value=?",
                    (name, old_name),
                )
                connection.execute(
                    "UPDATE campaigns SET target_value=? WHERE target_type='department' AND target_value=?",
                    (name, old_name),
                )
                connection.execute(
                    "UPDATE agent_rollouts SET target_value=? WHERE target_type='department' AND target_value=?",
                    (name, old_name),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="department rename conflicts with existing data") from exc
        return {"ok": True, "id": department_id, "name": name, "previous_name": old_name}

    @app.get("/api/ui/wallpaper")
    def wallpaper_settings(request: Request, _: dict[str, Any] = Depends(require_user)):
        with _database(request).connect() as connection:
            row = connection.execute("SELECT * FROM wallpaper_settings WHERE id=1").fetchone()
            statuses = {
                str(item["wallpaper_status"] or "pending"): int(item["total"])
                for item in connection.execute(
                    """SELECT a.wallpaper_status,COUNT(*) total FROM assets a
                       WHERE a.retired_at IS NULL AND NOT EXISTS (
                         SELECT 1 FROM wallpaper_exclusions w WHERE w.asset_id=a.id
                       ) GROUP BY a.wallpaper_status"""
                )
            }
            excluded_count = int(connection.execute(
                """SELECT COUNT(*) FROM wallpaper_exclusions w
                   JOIN assets a ON a.id=w.asset_id WHERE a.retired_at IS NULL"""
            ).fetchone()[0])
        result = dict(row) if row is not None else {"enabled": 0, "revision": ""}
        result["enabled"] = bool(result.get("enabled"))
        result["locked"] = bool(result.get("locked", 1))
        result["statuses"] = statuses
        result["excluded_count"] = excluded_count
        result["image_url"] = (
            f"/api/ui/wallpaper/image/{result['revision']}" if result["enabled"] and result.get("revision") else ""
        )
        return result

    @app.get("/api/ui/wallpaper/image/{revision}")
    def wallpaper_image(revision: str, request: Request, _: dict[str, Any] = Depends(require_user)):
        path, mime_type = _wallpaper_file(request, revision)
        return FileResponse(path, media_type=mime_type)

    @app.post("/api/ui/wallpaper")
    async def upload_wallpaper(request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"image/jpeg", "image/png"}:
            raise HTTPException(status_code=415, detail="wallpaper must be a JPG or PNG image")
        body = await request.body()
        if not body or len(body) > MAX_WALLPAPER_BYTES:
            raise HTTPException(status_code=413, detail="wallpaper must be between 1 byte and 10 MB")
        if content_type == "image/png" and not body.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=422, detail="invalid PNG image")
        if content_type == "image/jpeg" and not body.startswith(b"\xff\xd8\xff"):
            raise HTTPException(status_code=422, detail="invalid JPEG image")

        digest = hashlib.sha256(body).hexdigest()
        extension = "png" if content_type == "image/png" else "jpg"
        filename = f"wallpaper-{digest[:16]}.{extension}"
        root = _wallpaper_root(_config(request))
        destination = root / filename
        temporary = root / f".{filename}.tmp"
        temporary.write_bytes(body)
        os.replace(temporary, destination)
        now = iso()
        with _database(request).connect() as connection:
            connection.execute(
                """UPDATE wallpaper_settings SET enabled=1,revision=?,filename=?,mime_type=?,
                   sha256=?,size_bytes=?,style='fill',locked=1,updated_by=?,updated_at=? WHERE id=1""",
                (digest, filename, content_type, digest, len(body), user["id"], now),
            )
        for old in root.glob("wallpaper-*"):
            if old != destination and old.is_file():
                old.unlink(missing_ok=True)
        return {"ok": True, "revision": digest, "size_bytes": len(body), "updated_at": now}

    @app.delete("/api/ui/wallpaper")
    def disable_wallpaper(request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        with _database(request).connect() as connection:
            connection.execute(
                "UPDATE wallpaper_settings SET enabled=0,updated_by=?,updated_at=? WHERE id=1",
                (user["id"], iso()),
            )
        return {"ok": True}

    @app.get("/api/ui/wallpaper/exclusions")
    def wallpaper_exclusions(
        request: Request, search: str = Query("", max_length=200),
        _: dict[str, Any] = Depends(require_user),
    ):
        term = search.strip()
        with _database(request).connect() as connection:
            items = [dict(row) for row in connection.execute(
                """SELECT a.id AS asset_id,a.display_name,a.hostname,a.asset_tag,a.machine_id,
                          a.department,w.reason,w.created_at,u.username AS created_by
                   FROM wallpaper_exclusions w
                   JOIN assets a ON a.id=w.asset_id
                   JOIN users u ON u.id=w.created_by
                   ORDER BY COALESCE(NULLIF(a.display_name,''),a.hostname) COLLATE NOCASE"""
            ).fetchall()]
            candidates: list[dict[str, Any]] = []
            if term:
                pattern = f"%{term}%"
                candidates = [dict(row) for row in connection.execute(
                    """SELECT a.id AS asset_id,a.display_name,a.hostname,a.asset_tag,a.machine_id,a.department
                       FROM assets a
                       WHERE a.retired_at IS NULL
                         AND NOT EXISTS (SELECT 1 FROM wallpaper_exclusions w WHERE w.asset_id=a.id)
                         AND (a.display_name LIKE ? OR a.hostname LIKE ? OR a.asset_tag LIKE ? OR a.machine_id LIKE ?)
                       ORDER BY COALESCE(NULLIF(a.display_name,''),a.hostname) COLLATE NOCASE
                       LIMIT 20""",
                    (pattern, pattern, pattern, pattern),
                ).fetchall()]
        return {"items": items, "candidates": candidates, "total": len(items)}

    @app.post("/api/ui/wallpaper/exclusions", status_code=201)
    def create_wallpaper_exclusion(
        payload: WallpaperExclusionCreate, request: Request,
        user: dict[str, Any] = Depends(require_admin),
    ):
        verify_csrf(request, user)
        with _database(request).transaction() as connection:
            asset = connection.execute(
                "SELECT retired_at FROM assets WHERE id=?", (payload.asset_id,)
            ).fetchone()
            if asset is None:
                raise HTTPException(status_code=404, detail="asset not found")
            if asset["retired_at"] is not None:
                raise HTTPException(status_code=409, detail="retired asset already receives no wallpaper policy")
            try:
                connection.execute(
                    "INSERT INTO wallpaper_exclusions(asset_id,reason,created_by,created_at) VALUES (?,?,?,?)",
                    (payload.asset_id, payload.reason.strip(), user["id"], iso()),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="asset is already excluded") from exc
        return {"ok": True, "asset_id": payload.asset_id}

    @app.delete("/api/ui/wallpaper/exclusions/{asset_id}")
    def delete_wallpaper_exclusion(
        asset_id: int, request: Request, user: dict[str, Any] = Depends(require_admin),
    ):
        verify_csrf(request, user)
        with _database(request).connect() as connection:
            cursor = connection.execute("DELETE FROM wallpaper_exclusions WHERE asset_id=?", (asset_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="wallpaper exclusion not found")
        return {"ok": True, "asset_id": asset_id}

    @app.get("/api/ui/export.csv")
    def export_assets(request: Request, _: dict[str, Any] = Depends(require_user)):
        with _database(request).connect() as connection:
            result = list_assets(connection, page=1, page_size=10_000)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["display_name", "asset_tag", "hostname", "department", "online", "last_seen", "os_name", "os_version", "agent_version", "ipv4"])
        for item in result["items"]:
            writer.writerow([_csv_safe(value) for value in [
                item["display_name"], item["asset_tag"], item["hostname"], item["department"], item["online"],
                item["last_seen"], item["os_name"], item["os_version"], item["agent_version"], item["primary_ipv4"],
            ]])
        content = "\ufeff" + output.getvalue()
        return StreamingResponse(iter([content]), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": "attachment; filename=hos-monitor-assets.csv"})

    @app.get("/api/ui/policies")
    def get_policies(request: Request, _: dict[str, Any] = Depends(require_user)):
        with _database(request).connect() as connection:
            items = [dict(row) for row in connection.execute("SELECT * FROM policies ORDER BY scope_type,scope_value")]
        for item in items:
            item["daily_enabled"] = bool(item["daily_enabled"])
        return {"items": items}

    @app.put("/api/ui/policies")
    def put_policy(payload: PolicyUpdate, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        if not TIME_PATTERN.fullmatch(payload.daily_time):
            raise HTTPException(status_code=422, detail="daily_time must be HH:MM")
        scope_value = payload.scope_value.strip() if payload.scope_type == "department" else ""
        if payload.scope_type == "department" and not scope_value:
            raise HTTPException(status_code=422, detail="department scope requires scope_value")
        with _database(request).connect() as connection:
            if payload.scope_type == "department" and connection.execute(
                "SELECT 1 FROM departments WHERE name=? AND enabled=1", (scope_value,)
            ).fetchone() is None:
                raise HTTPException(status_code=422, detail="department must be selected from the active list")
            connection.execute(
                """INSERT INTO policies(scope_type,scope_value,heartbeat_seconds,online_threshold_seconds,
                   boot_delay_seconds,daily_enabled,daily_time,updated_at) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(scope_type,scope_value) DO UPDATE SET
                   heartbeat_seconds=excluded.heartbeat_seconds,
                   online_threshold_seconds=excluded.online_threshold_seconds,
                   boot_delay_seconds=excluded.boot_delay_seconds,daily_enabled=excluded.daily_enabled,
                   daily_time=excluded.daily_time,updated_at=excluded.updated_at""",
                (payload.scope_type, scope_value, payload.heartbeat_seconds, payload.online_threshold_seconds,
                 payload.boot_delay_seconds, int(payload.daily_enabled), payload.daily_time, iso()),
            )
        return {"ok": True}

    @app.post("/api/ui/campaigns", status_code=201)
    def create_campaign(payload: CampaignCreate, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        value = payload.target_value.strip()
        if payload.target_type != "all" and not value:
            raise HTTPException(status_code=422, detail="target_value is required")
        now = utc_now()
        with _database(request).connect() as connection:
            if payload.target_type == "department" and connection.execute(
                "SELECT 1 FROM departments WHERE name=? AND enabled=1", (value,)
            ).fetchone() is None:
                raise HTTPException(status_code=422, detail="department must be selected from the active list")
            cursor = connection.execute(
                "INSERT INTO campaigns(target_type,target_value,created_by,created_at,expires_at) VALUES (?,?,?,?,?)",
                (payload.target_type, value, user["id"], iso(now), iso(now + timedelta(hours=24))),
            )
        return {"id": cursor.lastrowid, "expires_at": iso(now + timedelta(hours=24))}

    @app.get("/api/ui/campaigns")
    def campaigns(request: Request, _: dict[str, Any] = Depends(require_user)):
        with _database(request).connect() as connection:
            rows = connection.execute(
                """SELECT c.*,u.username,
                   (SELECT COUNT(*) FROM campaign_receipts r WHERE r.campaign_id=c.id) delivered,
                   (SELECT COUNT(*) FROM campaign_receipts r WHERE r.campaign_id=c.id AND r.completed_at IS NOT NULL) completed
                   FROM campaigns c JOIN users u ON u.id=c.created_by ORDER BY c.id DESC LIMIT 50"""
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    @app.get("/api/ui/users")
    def users(request: Request, _: dict[str, Any] = Depends(require_admin)):
        with _database(request).connect() as connection:
            return {"items": [dict(row) for row in connection.execute(
                "SELECT id,username,role,enabled,created_at FROM users ORDER BY username"
            )]}

    @app.post("/api/ui/users", status_code=201)
    def create_user(payload: UserCreate, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        try:
            encoded = hash_password(payload.password)
            with _database(request).connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO users(username,password_hash,role,created_at) VALUES (?,?,?,?)",
                    (payload.username.strip(), encoded, payload.role, iso()),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="username already exists") from exc
        return {"id": cursor.lastrowid, "username": payload.username.strip(), "role": payload.role}

    @app.get("/api/ui/api-keys")
    def api_keys(request: Request, _: dict[str, Any] = Depends(require_admin)):
        with _database(request).connect() as connection:
            items = [dict(row) for row in connection.execute(
                "SELECT id,name,key_prefix,scope,enabled,created_at,last_used_at FROM api_keys ORDER BY name"
            )]
        return {"items": items}

    @app.post("/api/ui/api-keys", status_code=201)
    def create_api_key(payload: ApiKeyCreate, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        secret = "hm_" + random_token(32)
        try:
            with _database(request).connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO api_keys(name,key_prefix,key_hash,created_at) VALUES (?,?,?,?)",
                    (payload.name.strip(), secret[:12], token_hash(secret), iso()),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="API key name already exists") from exc
        return {"id": cursor.lastrowid, "name": payload.name.strip(), "api_key": secret}

    @app.patch("/api/ui/api-keys/{key_id}")
    def set_api_key_state(payload: ApiKeyState, key_id: int, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        with _database(request).connect() as connection:
            cursor = connection.execute("UPDATE api_keys SET enabled=? WHERE id=?", (int(payload.enabled), key_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="API key not found")
        return {"ok": True}

    @app.post("/api/ui/api-keys/{key_id}/rotate")
    def rotate_api_key(key_id: int, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        secret = "hm_" + random_token(32)
        with _database(request).connect() as connection:
            cursor = connection.execute(
                "UPDATE api_keys SET key_prefix=?,key_hash=?,enabled=1,last_used_at=NULL WHERE id=?",
                (secret[:12], token_hash(secret), key_id),
            )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="API key not found")
        return {"id": key_id, "api_key": secret}

    @app.post("/api/ui/agent-updates/releases", status_code=201)
    async def upload_agent_release(
        request: Request, user: dict[str, Any] = Depends(require_admin),
        x_admin_password: str = Header(default=""),
    ):
        verify_csrf(request, user)
        _confirm_admin_password(_database(request), user, x_admin_password)
        body = await request.body()
        try:
            metadata = verify_agent_bundle(_config(request), body)
            path = store_agent_bundle(
                _config(request), body, str(metadata["version"]), str(metadata["sha256"])
            )
            with _database(request).connect() as connection:
                cursor = connection.execute(
                    """INSERT INTO agent_releases
                       (version,filename,sha256,size_bytes,uploaded_by,uploaded_at)
                       VALUES (?,?,?,?,?,?)""",
                    (metadata["version"], path.name, metadata["sha256"], metadata["size_bytes"], user["id"], iso()),
                )
            return {"id": cursor.lastrowid, **metadata}
        except AgentUpdateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Agent version or release already exists") from exc

    @app.get("/api/ui/agent-updates")
    def list_agent_updates(request: Request, _: dict[str, Any] = Depends(require_admin)):
        with _database(request).connect() as connection:
            releases = [dict(row) for row in connection.execute(
                """SELECT ar.id,ar.version,ar.sha256,ar.size_bytes,ar.enabled,ar.uploaded_at,u.username AS uploaded_by
                   FROM agent_releases ar JOIN users u ON u.id=ar.uploaded_by ORDER BY ar.id DESC"""
            )]
            rollouts = [dict(row) for row in connection.execute(
                """SELECT r.id,r.release_id,ar.version,r.target_type,r.target_value,r.created_at,r.expires_at,
                   u.username AS created_by,
                   COUNT(rr.asset_id) AS delivered,
                   SUM(CASE WHEN rr.status='applied' THEN 1 ELSE 0 END) AS applied,
                   SUM(CASE WHEN rr.status='failed' THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN rr.status IN ('pending','downloading','installing') THEN 1 ELSE 0 END) AS pending
                   FROM agent_rollouts r JOIN agent_releases ar ON ar.id=r.release_id
                   JOIN users u ON u.id=r.created_by
                   LEFT JOIN agent_rollout_receipts rr ON rr.rollout_id=r.id
                   GROUP BY r.id ORDER BY r.id DESC LIMIT 50"""
            )]
        for item in releases:
            item["enabled"] = bool(item["enabled"])
        return {"releases": releases, "rollouts": rollouts}

    @app.post("/api/ui/agent-updates/rollouts", status_code=201)
    def create_agent_rollout(
        payload: AgentRolloutCreate, request: Request, user: dict[str, Any] = Depends(require_admin),
    ):
        verify_csrf(request, user)
        _confirm_admin_password(_database(request), user, payload.admin_password)
        if payload.confirmation != "UPDATE AGENT":
            raise HTTPException(status_code=422, detail="type UPDATE AGENT to confirm")
        target_value = payload.target_value.strip()
        now_value = utc_now()
        with _database(request).transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM agent_releases WHERE id=? AND enabled=1", (payload.release_id,)
            ).fetchone() is None:
                raise HTTPException(status_code=404, detail="Agent release not found")
            if payload.target_type == "all":
                target_value = ""
            elif payload.target_type == "department":
                if not target_value or connection.execute(
                    "SELECT 1 FROM departments WHERE name=? AND enabled=1", (target_value,)
                ).fetchone() is None:
                    raise HTTPException(status_code=422, detail="select an active department")
            elif not target_value.isdigit() or connection.execute(
                "SELECT 1 FROM assets WHERE id=?", (int(target_value or 0),)
            ).fetchone() is None:
                raise HTTPException(status_code=422, detail="Asset ID not found")
            cursor = connection.execute(
                """INSERT INTO agent_rollouts
                   (release_id,target_type,target_value,created_by,created_at,expires_at)
                   VALUES (?,?,?,?,?,?)""",
                (payload.release_id, payload.target_type, target_value, user["id"], iso(now_value),
                 iso(now_value + timedelta(days=7))),
            )
        return {"id": cursor.lastrowid, "expires_at": iso(now_value + timedelta(days=7))}

    @app.get("/api/ui/updates/config")
    def get_update_config(request: Request, _: dict[str, Any] = Depends(require_admin)):
        config = _config(request)
        return {
            "enabled": config.update_enabled,
            "backup_retention": config.update_backup_retention,
            "public_key_available": config.update_public_key_path.is_file(),
            "server_service_name": config.server_service_name,
        }

    @app.put("/api/ui/updates/config")
    def put_update_config(payload: UpdateConfigRequest, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        _confirm_admin_password(_database(request), user, payload.admin_password)
        try:
            request.app.state.config = save_update_config(
                _config(request), enabled=payload.enabled, backup_retention=payload.backup_retention,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/ui/updates/import", status_code=202)
    async def import_update(
        request: Request,
        user: dict[str, Any] = Depends(require_admin),
        x_admin_password: str = Header(default=""),
        x_update_confirmation: str = Header(default=""),
    ):
        verify_csrf(request, user)
        _confirm_admin_password(_database(request), user, x_admin_password)
        if x_update_confirmation != "UPDATE":
            raise HTTPException(status_code=422, detail="type UPDATE to confirm")
        try:
            content_length = int(request.headers.get("content-length", "0") or 0)
            if content_length > MAX_BUNDLE_BYTES:
                raise UpdateError("release bundle is larger than 210 MB")
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_BUNDLE_BYTES:
                    raise UpdateError("release bundle is larger than 210 MB")
            return stage_release_bundle(_config(request), bytes(body), user["username"])
        except UpdateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid Content-Length") from exc

    @app.get("/api/ui/updates/status")
    def updater_status(request: Request, _: dict[str, Any] = Depends(require_user)):
        return {"current_version": current_version(), **update_state(_config(request))}

    @app.get("/api/ui/updates/history")
    def update_history(request: Request, _: dict[str, Any] = Depends(require_admin)):
        with _database(request).connect() as connection:
            rows = connection.execute(
                """SELECT id,from_version,to_version,release_tag,action,status,started_by,
                   started_at,completed_at,backup_path,error_message
                   FROM system_updates ORDER BY id DESC LIMIT 30"""
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    @app.post("/api/ui/updates/rollback", status_code=202)
    def rollback_update(payload: UpdateRollbackRequest, request: Request, user: dict[str, Any] = Depends(require_admin)):
        verify_csrf(request, user)
        _confirm_admin_password(_database(request), user, payload.admin_password)
        if payload.confirmation != "ROLLBACK":
            raise HTTPException(status_code=422, detail="type ROLLBACK to confirm")
        with _database(request).connect() as connection:
            row = connection.execute(
                "SELECT backup_path FROM system_updates WHERE id=? AND status='completed' AND backup_path IS NOT NULL",
                (payload.update_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="rollback backup not found")
        try:
            return request_rollback(_config(request), Path(row["backup_path"]), user["username"])
        except (UpdateError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()
