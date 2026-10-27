# -*- coding: utf-8 -*-
"""探查 AstrBot providers API 的真实返回结构，再决定怎么建 xiaomi provider。"""
import base64
import hashlib
import hmac
import json
import time
import urllib.request

BASE = "http://127.0.0.1:6185"
cfg = json.load(open("/opt/miruku/astrbot/data/cmd_config.json", encoding="utf-8-sig"))
dash = cfg.get("dashboard", {})
secret = dash.get("jwt_secret", "")


def b64(x: bytes) -> str:
    return base64.urlsafe_b64encode(x).rstrip(b"=").decode()


def jwt() -> str:
    now = int(time.time())
    seg = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()) + "." + \
          b64(json.dumps({"username": dash.get("username", "OTTO"), "role": "admin",
                          "iat": now, "exp": now + 600}, separators=(",", ":")).encode())
    return seg + "." + b64(hmac.new(secret.encode(), seg.encode(), hashlib.sha256).digest())


def api(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + jwt()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


for path in ("/api/v1/providers", "/api/v1/provider/sources", "/api/v1/providers/sources"):
    print("=" * 12, path)
    try:
        raw = api("GET", path)
        print("  原始:", raw[:600])
    except Exception as e:
        code = getattr(e, "code", "")
        detail = ""
        try:
            detail = e.read()[:200].decode("utf-8", "replace")
        except Exception:
            pass
        print("  ERR", code, (detail or type(e).__name__)[:150])
