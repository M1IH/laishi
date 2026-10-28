# -*- coding: utf-8 -*-
"""本地 SSH 执行代理（给 DSH 里的 AI 用，用户自己的会话里启动）。

背景：沙箱里的 shell 既读不到 ~/.ssh 下的私钥（CC Safety Net 拦 secret.home.ssh），
也连不上 Windows 的 ssh-agent 命名管道（ssh-add -l 报 Could not open a connection）。
但用户自己的普通 PowerShell 会话两样都能用。所以由用户启动本代理，
AI 通过 127.0.0.1 的 HTTP 接口间接执行服务器命令——私钥始终不经过 AI。

启动（普通 PowerShell，保持窗口开着即可）：
    python tools/local-shell.py

然后 AI 执行：
    curl -H "X-Token: <启动时打印的 token>" \
         "http://127.0.0.1:8643/run?cmd=docker+ps"

安全边界：
- 只监听 127.0.0.1；
- 必须带 X-Token（随机生成，写进 .local-shell-token，已 gitignore）；
- 只能跑「ssh root@203.0.113.10 <命令>」，不能跑别的本地命令；
- 单条命令 180s 超时，输出截断 200KB。
"""

import json
import os
import secrets
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 8643
SSH_HOST = "root@203.0.113.10"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".local-shell-token")
TIMEOUT = 180
MAX_OUT = 200_000


def load_token():
    path = os.path.abspath(TOKEN_FILE)
    if os.path.exists(path):
        tok = open(path, encoding="utf-8").read().strip()
        if tok:
            return tok
    tok = secrets.token_hex(16)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tok)
    return tok


TOKEN = load_token()


class Handler(BaseHTTPRequestHandler):
    server_version = "local-shell/1.0"

    def log_message(self, fmt, *args):  # 静音访问日志
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """POST /run：body 为 JSON {"cmd": "..."}，用于超长命令（GET 的 URL 有限长）。"""
        u = urlparse(self.path)
        if u.path != "/run":
            return self._json(404, {"error": "not found"})
        if self.headers.get("X-Token", "") != TOKEN:
            return self._json(403, {"error": "bad token"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json(400, {"error": "bad content-length"})
        if length <= 0 or length > 2_000_000:
            return self._json(400, {"error": f"bad body size {length}"})
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"error": f"bad json: {e}"})
        cmd = str(payload.get("cmd") or "")
        if not cmd.strip():
            return self._json(400, {"error": "empty cmd"})

        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", SSH_HOST, cmd]
        t0 = time.time()
        try:
            p = subprocess.run(argv, capture_output=True, timeout=TIMEOUT)
            out = (p.stdout or b"") + (p.stderr or b"")
            code = p.returncode
        except subprocess.TimeoutExpired:
            return self._json(504, {"error": f"timeout after {TIMEOUT}s"})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})

        text = out.decode("utf-8", "replace")
        truncated = len(text) > MAX_OUT
        if truncated:
            text = text[:MAX_OUT] + "\n...[truncated %d bytes]" % (len(out) - MAX_OUT)
        return self._json(200, {
            "ok": code == 0,
            "exit": code,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "truncated": truncated,
            "cmd": cmd[:200],
            "out": text,
        })

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            return self._json(200, {"ok": True, "ssh_host": SSH_HOST})
        if u.path != "/run":
            return self._json(404, {"error": "not found"})
        if self.headers.get("X-Token", "") != TOKEN:
            return self._json(403, {"error": "bad token"})

        cmd = (parse_qs(u.query).get("cmd") or [""])[0]
        if not cmd.strip():
            return self._json(400, {"error": "empty cmd"})

        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", SSH_HOST, cmd]
        t0 = time.time()
        try:
            p = subprocess.run(argv, capture_output=True, timeout=TIMEOUT)
            out = (p.stdout or b"") + (p.stderr or b"")
            code = p.returncode
        except subprocess.TimeoutExpired:
            return self._json(504, {"error": f"timeout after {TIMEOUT}s", "cmd": cmd})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"{type(e).__name__}: {e}", "cmd": cmd})

        text = out.decode("utf-8", "replace")
        truncated = len(text) > MAX_OUT
        if truncated:
            text = text[:MAX_OUT] + f"\n...[truncated {len(out) - MAX_OUT} bytes]"
        return self._json(200, {
            "ok": code == 0,
            "exit": code,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "truncated": truncated,
            "cmd": cmd,
            "out": text,
        })


def main():
    print(f"local-shell 已启动: http://{HOST}:{PORT}")
    print(f"  X-Token: {TOKEN}")
    print(f"  目标: {SSH_HOST}")
    print("  按 Ctrl+C 停止。")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
        sys.exit(0)
