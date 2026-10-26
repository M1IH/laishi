# -*- coding: utf-8 -*-
"""通过 dashboard webchat 接口发一条消息，触发完整 LLM 管线。

用于验证 context_guard v0.4.0 的清污在真实生产路径上生效
（EmotionAI on_llm_request → context_guard on_agent_done → 落库）。
不会打扰任何真实 QQ 联系人。
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


def b64(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def token(secret: str, user: str) -> str:
    h = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    p = b64(
        json.dumps(
            {"username": user, "iat": now, "exp": now + 600}, separators=(",", ":")
        ).encode()
    )
    sig = b64(hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"


def main() -> int:
    cfg = json.loads(CFG.read_text(encoding="utf-8-sig"))
    dash = cfg.get("dashboard") or {}
    tk = token(dash["jwt_secret"], dash.get("username") or "admin")

    msg = sys.argv[1] if len(sys.argv) > 1 else "随便聊一句，今天天气怎么样"
    sid = sys.argv[2] if len(sys.argv) > 2 else "scrub-test-001"
    payload = json.dumps(
        {"message": msg, "session_id": sid, "enable_streaming": False}
    ).encode()

    req = urllib.request.Request(
        f"{BASE}/api/v1/chat",
        method="POST",
        data=payload,
        headers={
            "Authorization": f"Bearer {tk}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read().decode("utf-8", "replace")
            print(f"[{resp.status}] {body[:600]}")
            return 0
    except urllib.error.HTTPError as exc:
        print(f"[HTTP {exc.code}] {exc.read().decode('utf-8', 'replace')[:600]}")
        return 1
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
