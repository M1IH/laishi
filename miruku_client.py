"""Shared AstrBot dashboard client for the Miruku project.

Concentrates the logic that was previously duplicated across the four
operational scripts:

- locating the running AstrBot Launcher instance (INSTANCE)
- discovering the WebUI dashboard URL and port (dashboard_url)
- reading cmd_config.json and signing a short-lived HS256 JWT (get_token)
- issuing authenticated API requests (api) and reusable auth headers (headers)

Nothing here changes behaviour; the existing scripts are rewritten to import
from this module instead of each carrying its own copy.
"""

import datetime
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jwt
import psutil


ROOT = Path(__file__).resolve().parent


def _setting(name):
    """Read an environment override, then a simple project-local .env value."""
    if name in os.environ:
        return os.environ[name].strip()
    path = ROOT / ".env"
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def instance_path():
    """Resolve the AstrBot core directory from the environment or .env."""
    configured = _setting("ASTRBOT_CORE")
    if not configured:
        raise RuntimeError("Set ASTRBOT_CORE in the environment or project .env")
    path = Path(configured).expanduser()
    if not (path / "main.py").is_file():
        raise RuntimeError("ASTRBOT_CORE does not point to an AstrBot core directory")
    return path


INSTANCE = instance_path()


def dashboard_url():
    """Discover the running AstrBot WebUI base URL (http://127.0.0.1:<port>)."""
    override = _setting("ASTRBOT_DASHBOARD")
    if override:
        return override.rstrip("/")
    main_path = str(INSTANCE / "main.py").lower()
    for process in psutil.process_iter(["cmdline"]):
        try:
            command = " ".join(process.info["cmdline"] or []).lower()
            if main_path not in command:
                continue
            for connection in process.net_connections(kind="tcp"):
                if (
                    connection.status == psutil.CONN_LISTEN
                    and connection.laddr.ip in ("127.0.0.1", "0.0.0.0")
                ):
                    candidate = f"http://127.0.0.1:{connection.laddr.port}"
                    try:
                        with urlopen(candidate + "/api/v1/system-config", timeout=2):
                            return candidate
                    except HTTPError as error:
                        if error.code in (401, 403):
                            return candidate
                    except OSError:
                        continue
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    raise RuntimeError("AstrBot Dashboard is not running; start the Launcher instance first")


BASE = dashboard_url()


def _dashboard_config():
    config_path = INSTANCE / "data" / "cmd_config.json"
    return json.loads(config_path.read_text(encoding="utf-8-sig"))["dashboard"]


def get_token():
    """Sign a 5-minute HS256 JWT from the local dashboard credentials."""
    dashboard = _dashboard_config()
    return jwt.encode(
        {
            "username": dashboard["username"],
            "exp": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=5),
        },
        dashboard["jwt_secret"],
        algorithm="HS256",
    )


def auth_headers(token=None):
    """Authorization-only headers for requests that set their own body encoding
    (multipart file uploads, JSON via ``json=``)."""
    return {"Authorization": "Bearer " + (token or get_token())}


def json_headers(token=None):
    """Authorization + JSON Content-Type headers for raw-body urllib requests."""
    return {
        "Authorization": "Bearer " + (token or get_token()),
        "Content-Type": "application/json",
    }


def api(method, path, token, payload=None):
    """Issue an authenticated request against /api/v1 and unwrap ``data``."""
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        BASE + "/api/v1" + path,
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"{method} {path} failed: HTTP {error.code}") from error
    if result.get("status") not in ("ok", "success"):
        raise RuntimeError(f"{method} {path} failed: {result.get('message', 'unknown error')}")
    return result.get("data")


def latest_private_session(qq, max_age_minutes=30):
    """Return ``(updated_at, user_id)`` for the most recent QQ private session.

    Raises RuntimeError when no session exists or the latest is older than
    ``max_age_minutes``. Couples to AstrBot's internal data_v4.db schema in one
    place only, so a schema migration is a single-point fix.
    """
    if not str(qq).isdecimal():
        raise RuntimeError("--qq must be a QQ number")
    user_id = f"miruku:FriendMessage:{qq}"
    database_path = INSTANCE / "data" / "data_v4.db"
    if not database_path.is_file():
        raise RuntimeError("AstrBot data_v4.db is missing from the configured instance")
    try:
        with closing(sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)) as database:
            columns = {
                column[1]
                for column in database.execute("PRAGMA table_info(conversations)")
            }
            required = {"updated_at", "user_id", "platform_id"}
            if not required.issubset(columns):
                raise RuntimeError(
                    "AstrBot conversations schema changed; verify the instance version"
                )
            row = database.execute(
                "SELECT updated_at, user_id FROM conversations "
                "WHERE platform_id = 'miruku' AND user_id = ? ORDER BY updated_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
    except sqlite3.Error as error:
        raise RuntimeError("Could not read AstrBot conversations from data_v4.db") from error
    if not row:
        raise RuntimeError("No recent private conversation exists for the specified test QQ")
    try:
        updated_at = datetime.datetime.fromisoformat(row[0])
    except (TypeError, ValueError) as error:
        raise RuntimeError("AstrBot conversation timestamp format changed") from error
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=datetime.timezone.utc)
    age = datetime.datetime.now(datetime.timezone.utc) - updated_at
    if age > datetime.timedelta(minutes=max_age_minutes):
        raise RuntimeError(
            f"The latest QQ private conversation is older than {max_age_minutes} minutes"
        )
    return row[0], row[1]
