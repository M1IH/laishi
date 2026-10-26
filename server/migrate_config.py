# -*- coding: utf-8 -*-
"""服务端配置迁移：把本机搬来的配置改成容器形态（就地写，绝不打印密钥值）。

四处必改（每条都有本机实测/源码依据，不靠猜）：
  1) 主动插件 web_admin.host：127.0.0.1 -> 0.0.0.0
     容器内绑回环的话，宿主的 127.0.0.1:4100 端口映射打不进去；
     心跳判据 ④ 与 switch_proactive_recipient.py 都依赖 4100。
     安全性不受影响：compose 只在宿主 127.0.0.1 暴露该端口。
  2) 知识插件 knowledge_root：Windows 绝对路径 -> 容器内目录
     （插件用 importlib 从该目录加载 inject.py/query.py，并把
      `knowledge_root / "miruku_knowledge.sqlite3"` 传给 build_block；
      见 main.py:54-64。）
  3) 观察插件同理（若含路径字段）。
  4) 主动插件 session_list：按 OTTO 决定 ③，云端首版只对**测试号**主动发；
     来世的被动回复照常。知识插件 target_qq **不改**——它管的是被动回复时的
     知识注入，正是为她准备的。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DATA = Path("/opt/miruku/astrbot/data")
CFGDIR = DATA / "config"
SRC = DATA / "laishi"        # 宿主侧（本脚本读 targets 用）
# 知识插件在**容器内**用 importlib 从 knowledge_root 加载 inject.py/query.py 与 sqlite，
# 挂载 ./astrbot/data -> /AstrBot/data，所以配置里必须写容器路径，不能写宿主路径。
KROOT_CONTAINER = "/AstrBot/data/knowledge"


def mask(v) -> str:
    return re.sub(r"(\d{3})\d{4}(\d{3})", r"\1***\2", str(v if v is not None else ""))


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def save(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    tgt_file = SRC / "proactive_targets.local.json"
    if not tgt_file.is_file():
        print("[FAIL] 缺 proactive_targets.local.json（测试号 UMO 来源）")
        return 2
    targets = {k: v for k, v in load(tgt_file).items() if not k.startswith("_")}
    if "test" not in targets:
        print("[FAIL] targets 里没有 test 键")
        return 2
    test_umo = targets["test"]
    test_qq = test_umo.split(":")[-1]

    # 1+4) 主动消息插件
    pa = CFGDIR / "astrbot_plugin_proactive_chat_config.json"
    cfg = load(pa)
    fs = cfg["friend_settings"]
    before = list(fs.get("session_list") or [])
    fs["session_list"] = [test_umo]
    cfg["web_admin"]["host"] = "0.0.0.0"
    save(pa, cfg)
    print(f"[proactive] session_list {[mask(x) for x in before]} -> {[mask(test_umo)]}")
    print(f"[proactive] web_admin.host -> 0.0.0.0 (port {cfg['web_admin'].get('port')})")
    sch = fs.get("schedule_settings") or {}
    ats = fs.get("auto_trigger_settings") or {}
    print(f"[proactive] schedule min/max={sch.get('min_interval_minutes')}/{sch.get('max_interval_minutes')} "
          f"quiet={sch.get('quiet_hours')} max_unanswered={sch.get('max_unanswered_times')} "
          f"auto_trigger={ats.get('enable_auto_trigger')}/{ats.get('auto_trigger_after_minutes')}m")
    print(f"[proactive] prompt 首行={fs.get('proactive_prompt','').splitlines()[0:1]}")

    # 2) 知识插件：只改 knowledge_root -> 容器路径；target_qq 保留来世（见文档字符串第 4 条）
    kp = CFGDIR / "astrbot_plugin_miruku_knowledge_config.json"
    kc = load(kp)
    old_root = kc.get("knowledge_root")
    kc["knowledge_root"] = KROOT_CONTAINER
    save(kp, kc)
    print(f"[knowledge] knowledge_root {mask(old_root)[:34]}… -> {kc['knowledge_root']}")
    print(f"[knowledge] target_qq 保持 {mask(kc.get('target_qq'))}（被动回复的知识注入按她走）")
    host_db = DATA / "knowledge" / "miruku_knowledge.sqlite3"
    print(f"[knowledge] 卷内实际文件: sqlite={'YES' if host_db.is_file() else 'MISSING'} "
          f"inject={'YES' if (DATA/'knowledge'/'inject.py').is_file() else 'MISSING'} "
          f"query={'YES' if (DATA/'knowledge'/'query.py').is_file() else 'MISSING'}")

    # 3) 其余自研插件配置（有路径字段才改）
    for name in ("astrbot_plugin_miruku_observer_config.json",
                 "astrbot_plugin_miruku_context_guard_config.json"):
        p = CFGDIR / name
        if not p.is_file():
            print(f"[skip] 无 {name}")
            continue
        d = load(p)
        changed = []
        for k, v in list(d.items()):
            if isinstance(v, str) and re.match(r"^[A-Za-z]:[\\/]", v):
                # Windows 路径在容器里无意义，统一改到卷内 laishi 子目录
                d[k] = f"/AstrBot/data/laishi/{Path(v.replace(chr(92), '/')).name}"
                changed.append(k)
        if changed:
            save(p, d)
        print(f"[{name.split('miruku_')[1][:9]}] 路径字段改写: {changed or '无'} "
              f"target_qq={mask(d.get('target_qq')) if 'target_qq' in d else '-'}")

    # 5) 只核对不改：平台连接形态与白名单
    #    注意：cmd_config 的 platform 条目是**扁平**字段（ws_reverse_host 直接挂在
    #    条目上，没有嵌套 config），早前用 p["config"] 读会得到 None，误报连不上。
    cmd = load(DATA / "cmd_config.json")
    for p in cmd.get("platform", []):
        c = p.get("config") if isinstance(p.get("config"), dict) else {}
        host = p.get("ws_reverse_host", c.get("ws_reverse_host"))
        port = p.get("ws_reverse_port", c.get("ws_reverse_port"))
        tok = p.get("ws_reverse_token", c.get("ws_reverse_token")) or ""
        print(f"[platform] type={p.get('type')} enable={p.get('enable')} ws_reverse="
              f"{host}:{port} token={'SET' if tok else 'empty'}")
        if str(host) not in ("0.0.0.0", "::", ""):
            print("   [warn] ws_reverse_host 非 0.0.0.0，跨容器可能连不上")
        if str(port) != "6199":
            print(f"   [warn] 端口不是 6199，compose 的 ONEBOT_URL 要跟着改")
    ps = cmd.get("platform_settings", {})
    print(f"[platform_settings] enable_id_white_list={ps.get('enable_id_white_list')} "
          f"whitelist={len(ps.get('id_whitelist') or [])} 项")
    print(f"[dashboard] user={cmd['dashboard'].get('username')} port={cmd['dashboard'].get('port')} "
          f"host={cmd['dashboard'].get('host')} pwd={'SET' if cmd['dashboard'].get('password') else 'EMPTY'}")
    print("[migrate] 完成（密钥值全程未打印）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
