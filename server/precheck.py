# -*- coding: utf-8 -*-
"""本地校验 server/compose.yaml（不联网、不落密钥）。"""
import yaml

d = yaml.safe_load(open("server/compose.yaml", encoding="utf-8"))
svcs = d["services"]
assert set(svcs) == {"astrbot", "napcat"}, svcs.keys()
for name, s in svcs.items():
    assert s["restart"] in ("always", "unless-stopped"), name
    for p in s["ports"]:
        assert p.startswith("127.0.0.1:"), (name, p)

j = "\n".join(str(e) for e in svcs["napcat"]["environment"])
for k in ("MODE=reverse_ws", "ONEBOT_URL=ws://astrbot:6199/ws",
          "WEBUI_TOKEN=${NAPCAT_WEBUI_TOKEN}", "TZ=Asia/Shanghai"):
    assert k in j, k
assert "6199" not in "\n".join(svcs["astrbot"]["ports"]), "6199 不该对外暴露"
assert d["networks"]["miruku"]["driver"] == "bridge"
print("[precheck] OK: 两服务 / 端口仅 127.0.0.1 / napcat reverse_ws -> ws://astrbot:6199/ws / 6199 不出容器")
