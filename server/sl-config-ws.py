#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SnowLuma 反向 WS 对接 AstrBot（2026-10-29 DeepSeek）
用法：在服务器上跑 python3 /root/sl-config-ws.py <uin>
作用：往 /var/lib/docker/volumes/qq-gateway-data/_data/config/onebot_<uin>.json
     的 networks.wsClients 注入 ws://astrbot:6199/ws（幂等），打印 accessToken。
"""
import json, sys, glob, os, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CFG_DIR = "/var/lib/docker/volumes/qq-gateway-data/_data/config"
TARGET_URL = "ws://astrbot:6199/ws"

def main():
    uin = sys.argv[1] if len(sys.argv) > 1 else None
    paths = []
    if uin:
        paths.append(os.path.join(CFG_DIR, f"onebot_{uin}.json"))
    else:
        paths = sorted(glob.glob(os.path.join(CFG_DIR, "onebot_*.json")))
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        # 账号配置还没生成，退而写全局 onebot.json
        paths = [os.path.join(CFG_DIR, "onebot.json")]
        if not os.path.isfile(paths[0]):
            print("FAIL: 没有任何 onebot 配置文件"); sys.exit(1)
        print("NOTE: 账号配置未生成，改写全局 onebot.json")

    for path in paths:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        cfg = json.loads(raw)
        nets = cfg.setdefault("networks", {})
        clients = nets.setdefault("wsClients", [])
        if any(c.get("url") == TARGET_URL for c in clients):
            print(f"SKIP {os.path.basename(path)}: wsClients 已含 {TARGET_URL}")
        else:
            clients.append({"url": TARGET_URL, "role": "Universal", "reconnectIntervalMs": 5000})
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            print(f"OK   {os.path.basename(path)}: 已注入 wsClients -> {TARGET_URL}")
        # 打印 token 供核对（AstrBot 侧 token 应为空，SnowLuma 留空即可）
        tok = (cfg.get("networks", {}).get("wsServers") or [{}])[0].get("accessToken", "")
        acc = [c.get("accessToken", "") for c in cfg.get("networks", {}).get("wsClients", [])]
        print(f"     file={os.path.basename(path)} wsServers.token={'SET' if tok else '(空)'} wsClients.token={acc}")

if __name__ == "__main__":
    main()
