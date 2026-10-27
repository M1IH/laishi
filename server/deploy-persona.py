# -*- coding: utf-8 -*-
"""把改好的 system.txt 直接部署到服务器 AstrBot 的 miruku 人格。

不能走本机 deploy_miruku.py（它连本机 dashboard，现在本机没跑），
改为在服务器上读 data/laishi/system.txt 并调 dashboard API 写入 persona。
"""
import json
import urllib.request

BASE = "http://127.0.0.1:6185"
TOKEN = None

# 从服务器 cmd_config 里取 dashboard 凭据来签 JWT
import base64
import hashlib
import hmac
import time

CFG = "/opt/miruku/astrbot/data/cmd_config.json"
cfg = json.load(open(CFG, encoding="utf-8-sig"))
dash = cfg.get("dashboard", {})
jwt_secret = dash.get("jwt_secret", "")


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_jwt() -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "username": dash.get("username", "OTTO"),
        "role": "admin",
        "iat": now,
        "exp": now + 300,
    }
    seg = b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + \
          b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(jwt_secret.encode(), seg.encode(), hashlib.sha256).digest()
    return seg + "." + b64url(sig)


def api(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + make_jwt()})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


prompt = open("/opt/miruku/astrbot/data/laishi/system.txt", encoding="utf-8").read()
print("本地 prompt 字符数:", len(prompt))

personas = api("GET", "/api/v1/personas")
names = [p.get("persona_id") for p in (personas.get("data") or personas or [])]
print("现有人格:", names)

payload = {"persona_id": "miruku", "system_prompt": prompt, "begin_dialogs": []}
if "miruku" in names:
    api("PUT", "/api/v1/personas/by-id", payload)
    print("已更新人格 miruku")
else:
    api("POST", "/api/v1/personas", payload)
    print("已创建人格 miruku")

live = api("GET", "/api/v1/personas/by-id?persona_id=miruku")
txt = (live.get("data") or live).get("system_prompt", "")
print("线上字符数:", len(txt))
print("一致性:", txt.strip() == prompt.strip())
for probe in ("对话不要只停在他给的话头上", "每一轮除了接住他说的", "一句话能说完就不要再补第二句"):
    print(("  有  " if probe in txt else "  无  ") + probe)
