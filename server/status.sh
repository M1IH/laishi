#!/usr/bin/env bash
# 只读状态汇总（避免从 Windows 侧多层引号出错）
echo "== images =="
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' || true
echo "== pull processes =="
pgrep -af "docker pull" | sed 's/^/  /' || echo "  none"
echo "== containers =="
docker ps -a --format '{{.Names}} {{.Status}}' | sed 's/^/  /' || true
echo "== listeners =="
ss -tln | awk '{print "  "$4}' | grep -E ':(22|4100|5900|6080|6099|6185|6199)$' || echo "  (none of ours)"
echo "== mem =="
free -m | awk 'NR<4{print "  "$0}'
echo "== systemd desktop units =="
for u in miruku-xvfb miruku-desktop miruku-vnc miruku-novnc; do
  printf '  %s=%s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null || echo unknown)"
done
echo "== disk =="
df -h / | awk 'NR==2{print "  "$4" avail of "$2}'
