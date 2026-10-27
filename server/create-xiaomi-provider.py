# -*- coding: utf-8 -*-
"""创建 xiaomi provider（mimo-v2.6-flash），供表情插件当情感判断模型。

API 结构（实测）：
  GET  /api/v1/providers -> {status, data:{providers:[{provider, api_base, key,
                                id, provider_source_id, model, enable, ...}]}}
  新增时按同样形状 POST 一个对象进去。
key 从 provider_sources 里已有的 xiaomi 源继承（用户已填过），不重打明文。
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.request

BASE = "http://127.0.0.1:6185"
CFG = "/opt/miruku/astrbot/data/cmd_config.json"
cfg = json.load(open(CFG, encoding="utf-8-sig"))
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
    with urllib.request.urlopen(req, timeout=40) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


# 1) 取 xiaomi 源的凭据（不打印明文）
src = None
for s in cfg.get("provider_sources", []):
    if s.get("id") == "xiaomi":
        src = s
        break
if not src:
    raise SystemExit("[FAIL] cmd_config 里没有 xiaomi 源")

key_val = src.get("key")
if isinstance(key_val, list) and key_val:
    key_list = key_val
elif isinstance(key_val, str) and key_val:
    key_list = [key_val]
else:
    raise SystemExit("[FAIL] xiaomi 源里没有 key")
print("xiaomi 源: api_base =", src.get("api_base"), "| key 已配置")

# 2) 查现有 providers
resp = api("GET", "/api/v1/providers")
providers = (resp.get("data") or {}).get("providers", [])
print("现有 providers:", [p.get("id") for p in providers])

already = [p for p in providers if p.get("provider_source_id") == "xiaomi"]
if already:
    print("已存在 xiaomi provider:", [p.get("id") for p in already])
    target = already[0]["id"]
else:
    model = "mimo-v2.6-flash"
    newp = {
        "provider": "xiaomi",
        "type": "xiaomi_chat_completion",
        "provider_type": "chat_completion",
        "key": key_list,
        "api_base": src.get("api_base") or "https://api.xiaomimimo.com/v1",
        "timeout": 120,
        "proxy": "",
        "custom_headers": {},
        "id": f"xiaomi/{model}",
        "enable": True,
        "provider_source_id": "xiaomi",
        "model": model,
        "modalities": ["text"],
        "custom_extra_body": {},
        "max_context_tokens": 128000,
    }
    print("创建:", newp["id"])
    out = api("POST", "/api/v1/providers", newp)
    print("  返回:", json.dumps(out, ensure_ascii=False)[:250])
    resp2 = api("GET", "/api/v1/providers")
    ids = [p.get("id") for p in (resp2.get("data") or {}).get("providers", [])]
    print("  回读:", ids)
    target = f"xiaomi/{model}" if f"xiaomi/{model}" in ids else (ids[-1] if ids else None)

print("\n目标 provider_id =", target)
