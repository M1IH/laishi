# -*- coding: utf-8 -*-
"""热重载 context_guard 插件（不重启 AstrBot 进程）。

读实例 data/cmd_config.json 的 dashboard jwt_secret/username 现签 HS256 token，
POST /api/v1/plugins/<name>/reload。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.request
from pathlib import Path

CORE = Path(
    r"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\core"
)
CFG = CORE / "data" / "cmd_config.json"
BASE = "http://127.0.0.1:6185"
PLUGIN = "astrbot_plugin_miruku_context_guard"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(secret: str, username: str) -> str:
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = b64(
        json.dumps(
            {"username": username, "iat": now, "exp": now + 600},
            separators=(",", ":"),
        ).encode()
    )
    signing = f"{header}.{payload}".encode()
    sig = b64(hmac.new(secret.encode(), signing, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def main() -> int:
    if not CFG.exists():
        print(f"[FAIL] 找不到 {CFG}")
        return 1
    cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
    dash = cfg.get("dashboard") or {}
    secret = dash.get("jwt_secret")
    user = dash.get("username") or "admin"
    if not secret:
        print("[FAIL] cmd_config.json 里没有 dashboard.jwt_secret")
        return 1

    token = make_token(secret, user)
    url = f"{BASE}/api/v1/plugins/{PLUGIN}/reload"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=b"{}",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            print(f"[{resp.status}] {body[:400]}")
            return 0 if resp.status == 200 else 1
    except urllib.error.HTTPError as exc:
        print(f"[HTTP {exc.code}] {exc.read().decode('utf-8', 'replace')[:400]}")
        return 1
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
