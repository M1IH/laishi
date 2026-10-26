#!/usr/bin/env bash
# 桌面兜底：Xvfb + openbox + x11vnc + noVNC，全部只绑 127.0.0.1
#
# 用途写清，别误会成扫码入口：Linux 无头栈里 QQ 没有窗口，扫码走
# **NapCat WebUI 的二维码页**。noVNC 只用于「WebUI 打不开 / 号被风控要看提示」的兜底。
# 每个 systemd 单元只跑一个前台进程，不玩 shell 后台技巧。
set -euo pipefail

PASS=/etc/miruku/vnc.pass
INFO=/etc/miruku/vnc.password
mkdir -p /etc/miruku

if [ ! -f "$PASS" ]; then
  PW="$(openssl rand -hex 3)"          # 8 位；x11vnc 密码上限 8 字符
  x11vnc -storepasswd "$PW" "$PASS" >/dev/null
  chmod 600 "$PASS"
  printf 'VNC_PASSWORD=%s\n' "$PW" > "$INFO"
  chmod 600 "$INFO"
  echo "[novnc] 新密码已生成（见 $INFO）"
else
  echo "[novnc] 沿用已有密码（$INFO）"
fi

WEBDIR=/usr/share/novnc
[ -f "$WEBDIR/vnc.html" ] || { echo "[FAIL] 缺 $WEBDIR/vnc.html（apt 装 novnc）"; exit 1; }

unit(){ printf '%s\n' "$2" > "/etc/systemd/system/$1"; }

unit miruku-xvfb.service '[Unit]
Description=Miruku fallback X server (Xvfb :99)
After=network.target

[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1280x800x24
Restart=on-failure
RestartSec=3
MemoryMax=150M

[Install]
WantedBy=multi-user.target'

unit miruku-desktop.service '[Unit]
Description=Miruku fallback WM (openbox)
After=miruku-xvfb.service
Requires=miruku-xvfb.service

[Service]
Environment=DISPLAY=:99
ExecStart=/usr/bin/openbox
Restart=on-failure
RestartSec=3
MemoryMax=120M

[Install]
WantedBy=multi-user.target'

unit miruku-vnc.service '[Unit]
Description=x11vnc on :99 (localhost only)
After=miruku-xvfb.service
Requires=miruku-xvfb.service

[Service]
ExecStart=/usr/bin/x11vnc -display :99 -rfbauth /etc/miruku/vnc.pass -localhost -forever -shared -noxdamage -rfbport 5900
Restart=on-failure
RestartSec=3
MemoryMax=120M

[Install]
WantedBy=multi-user.target'

unit miruku-novnc.service '[Unit]
Description=noVNC websockify 6080 -> 127.0.0.1:5900
After=miruku-vnc.service
Requires=miruku-vnc.service

[Service]
ExecStart=/usr/bin/websockify 127.0.0.1:6080 127.0.0.1:5900 --web=/usr/share/novnc
Restart=on-failure
RestartSec=3
MemoryMax=90M

[Install]
WantedBy=multi-user.target'

systemctl daemon-reload
systemctl enable --now miruku-xvfb.service miruku-desktop.service miruku-vnc.service miruku-novnc.service
sleep 4
for u in miruku-xvfb miruku-desktop miruku-vnc miruku-novnc; do
  printf '%s=%s ' "$u" "$(systemctl is-active "$u" || true)"
done
echo
ss -tln | grep -E '127\.0\.0\.1:(6080|5900)' || echo "[warn] 6080/5900 未监听：journalctl -u miruku-novnc"
echo "[novnc] 完成"
