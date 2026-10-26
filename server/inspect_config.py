# -*- coding: utf-8 -*-
"""生成迁移计划（只读检查，不打印任何凭据值）。"""
import json
import sys

cfg = json.load(open(sys.argv[1], encoding="utf-8-sig"))
platforms = cfg.get("platforms", [])
print(f"platforms: {len(platforms)} 条")
for i, p in enumerate(platforms):
    c = p.get("config", {})
    print(f"  [{i}] type={p.get('type')} active={p.get('active')}")
    for k in sorted(c):
        lk = k.lower()
        if any(t in lk for t in ("token", "secret", "password", "key")):
            print(f"        {k}: <{'SET' if c[k] else 'empty'}>")
        elif isinstance(c[k], (list, dict)):
            print(f"        {k}: {type(c[k]).__name__}(len={len(c[k])})")
        else:
            v = c[k]
            print(f"        {k}: {v!r}"[:90])

print(f"\nproviders: {len(cfg.get('providers', []))} 个")
for pr in cfg.get("providers", []):
    has_key = any(
        bool(pr.get(k)) for k in pr if any(t in k.lower() for t in ("key", "token", "secret"))
    )
    print(f"  id={pr.get('id')} type={pr.get('type')} active={pr.get('is_active')} "
          f"cred={'SET' if has_key else 'NONE'}")

print("\nplatform_settings:", sorted((cfg.get("platform_settings") or {}).keys()))
print("agent_runner.persona:", (cfg.get("agent_runner") or {}).get("config", {}).get("persona"))
print("tts enabled:", bool((cfg.get("tts_config") or {}).get("enable")))
print("streaming:", bool((cfg.get("provider_settings") or {}).get("streaming")))
