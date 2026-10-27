#!/usr/bin/env bash
# 部署「分时段主动消息节奏」
#   活跃：8:30-12:00 与 13:30-18:00，间隔 30-70 分钟一条
#   静默：0:00-8:30 / 12:00-13:30 / 18:00-24:00，一条都不发
#
# 为什么要改插件而不是只改配置：
#   插件自带的 utils/time_utils.py 里 is_quiet_time() 用 quiet_hours_str.split("-")
#   只切两段后 int()，所以只认 "1-7" 这种单个整点区间。写 "0-8:30,12-13:30,18-24"
#   会在 int("8:30") 处抛 ValueError，被 except 吞掉后 return False —— 结果是
#   “静默完全失效”，比不支持更糟。所以先装一份支持多段 + 半小时粒度的新解析器，
#   再让 scheduler 排期时直接跳过静默段，最后才写配置。
#
# 用法（在服务器上）：bash /root/deploy-proactive-hours.sh
# 失败时会在对应步骤 set -e 中断，配置保持原样，不会留下“静默失效”的中间态。
set -e

TU=/opt/miruku/astrbot/data/plugins/astrbot_plugin_proactive_chat/utils/time_utils.py
SS=/opt/miruku/astrbot/data/plugins/astrbot_plugin_proactive_chat/core/services/scheduler_service.py
CFG=/opt/miruku/astrbot/data/config/astrbot_plugin_proactive_chat_config.json

echo "== 0. 检查路径 =="
for p in "$TU" "$SS" "$CFG"; do
  test -f "$p" || { echo "  找不到 $p —— 路径不对，先确认插件目录名"; exit 1; }
done
echo "  三个路径都在"

echo ""
echo "== 1. 备份并替换 time_utils.py（多段 + 半小时粒度解析器）=="
cp -a "$TU" "$TU.bak.$(date +%Y%m%d%H%M%S)"
cat > "$TU.b64" <<'B64_EOF'
IiIi5pe26Ze05bel5YW35Ye95pWw5qih5Z2X44CCIiIiCgpmcm9tIF9fZnV0dXJlX18gaW1wb3J0IGFubm90YXRpb25zCgppbXBvcnQgem9uZWluZm8KZnJvbSBkYXRldGltZSBpbXBvcnQgZGF0ZXRpbWUKCiMg5Lit5paH5pif5pyf5ZCN56ew77yM57Si5byV5LiOIGRhdGV0aW1lLndlZWtkYXkoKSDlr7npvZDvvIgwPeWRqOS4gO+8iQpfV0VFS0RBWV9OQU1FU19aSCA9ICgi5ZGo5LiAIiwgIuWRqOS6jCIsICLlkajkuIkiLCAi5ZGo5ZubIiwgIuWRqOS6lCIsICLlkajlha0iLCAi5ZGo5pelIikKCiMg5LiA5aSp55qE5YiG6ZKf5pWw77yb57uT5p2f56uv5YaZIDI0IOaXtueUqOWug+ihqOekuuKAnOW9k+WkqeacgOWQjuS4gOWIhumSn+S5i+WQjuKAnQpfREFZX01JTlVURVMgPSAxNDQwCgoKZGVmIF9wYXJzZV9oaG1tKHZhbHVlOiBzdHIpIC0+IGludDoKICAgICIiIuaKiiAiOCIgLyAiMDgiIC8gIjg6MzAiIC8gIjI0IiDop6PmnpDmiJDlvZPml6XliIbpkp/mlbDvvIgwLi4xNDQw77yJ44CCIiIiCiAgICB0ZXh0ID0gc3RyKHZhbHVlKS5zdHJpcCgpCiAgICBpZiBub3QgdGV4dDoKICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJlbXB0eSB0aW1lIikKICAgIGlmICI6IiBpbiB0ZXh0OgogICAgICAgIGhvdXJfdGV4dCwgbWludXRlX3RleHQgPSB0ZXh0LnNwbGl0KCI6IiwgMSkKICAgICAgICBob3VyLCBtaW51dGUgPSBpbnQoaG91cl90ZXh0KSwgaW50KG1pbnV0ZV90ZXh0KQogICAgZWxzZToKICAgICAgICBob3VyLCBtaW51dGUgPSBpbnQodGV4dCksIDAKICAgIGlmIGhvdXIgPT0gMjQ6CiAgICAgICAgaWYgbWludXRlICE9IDA6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoZiJpbnZhbGlkIHRpbWU6IHt2YWx1ZSFyfSIpCiAgICAgICAgcmV0dXJuIF9EQVlfTUlOVVRFUwogICAgaWYgbm90IDAgPD0gaG91ciA8PSAyMyBvciBub3QgMCA8PSBtaW51dGUgPD0gNTk6CiAgICAgICAgcmFpc2UgVmFsdWVFcnJvcihmImludmFsaWQgdGltZToge3ZhbHVlIXJ9IikKICAgIHJldHVybiBob3VyICogNjAgKyBtaW51dGUKCgpkZWYgcGFyc2VfcXVpZXRfc3BhbnMocXVpZXRfaG91cnNfc3RyOiBzdHIpIC0+IGxpc3RbdHVwbGVbaW50LCBpbnRdXToKICAgICIiIuaKiuWFjeaJk+aJsOmFjee9ruino+aekOaIkOiLpeW5siAo5byA5aeL5YiG6ZKfLCDnu5PmnZ/liIbpkp8pIOWMuumXtOOAggoKICAgIOWFvOWuueaXp+eahOWNleauteaVtOeCueWGmeazle+8iCIxLTci44CBIjIzLTYi77yJ77yM5Lmf5pSv5oyB5aSa5q615LiO5Y2K5bCP5pe257KS5bqm77yMCiAgICDmrrXkuYvpl7TnlKjpgJflj7fliIbpmpTvvIznq6/ngrnlhpnmiJAgIkgiIOaIliAiSDpNTSLvvIznu5PmnZ/nq6/lhYHorrjlhpkgMjQg6KGo56S65b2T5aSp5pyr5bC+77yaCgogICAgICAgIDAtODozMCwxMi0xMzozMCwxOC0yNAoKICAgIOWNleautemdnuazleaXtui3s+i/h+ivpeaute+8jOS4jeW9seWTjeWFtuS9meauteOAggogICAgIiIiCiAgICBzcGFuczogbGlzdFt0dXBsZVtpbnQsIGludF1dID0gW10KICAgIGZvciBjaHVuayBpbiBzdHIocXVpZXRfaG91cnNfc3RyIG9yICIiKS5zcGxpdCgiLCIpOgogICAgICAgIGNodW5rID0gY2h1bmsuc3RyaXAoKQogICAgICAgIGlmIG5vdCBjaHVuayBvciAiLSIgbm90IGluIGNodW5rOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHN0YXJ0X3RleHQsIGVuZF90ZXh0ID0gY2h1bmsuc3BsaXQoIi0iLCAxKQogICAgICAgIHRyeToKICAgICAgICAgICAgc3RhcnQgPSBfcGFyc2VfaGhtbShzdGFydF90ZXh0KQogICAgICAgICAgICBlbmQgPSBfcGFyc2VfaGhtbShlbmRfdGV4dCkKICAgICAgICBleGNlcHQgKFZhbHVlRXJyb3IsIFR5cGVFcnJvcik6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgc3RhcnQgPT0gZW5kOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIHN0YXJ0ID49IF9EQVlfTUlOVVRFUyBvciBlbmQgPiBfREFZX01JTlVURVM6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgc3BhbnMuYXBwZW5kKChzdGFydCwgZW5kKSkKICAgIHJldHVybiBzcGFucwoKCmRlZiBfaW5fc3BhbnMobWludXRlX29mX2RheTogaW50LCBzcGFuczogbGlzdFt0dXBsZVtpbnQsIGludF1dKSAtPiBib29sOgogICAgIiIi5Yik5pat5p+Q5YiG6ZKf55qE5YGP56e75piv5ZCm6JC95Zyo5Lu75LiA5YWN5omT5omw5Yy66Ze05YaF44CCIiIiCiAgICBtaW51dGVfb2ZfZGF5ICU9IF9EQVlfTUlOVVRFUwogICAgZm9yIHN0YXJ0LCBlbmQgaW4gc3BhbnM6CiAgICAgICAgaWYgc3RhcnQgPD0gZW5kOgogICAgICAgICAgICAjIOWQjOaXpeWMuumXtO+8jOS+i+WmgiAxLTcKICAgICAgICAgICAgaWYgc3RhcnQgPD0gbWludXRlX29mX2RheSA8IGVuZDoKICAgICAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgZWxzZToKICAgICAgICAgICAgIyDot6jlpKnljLrpl7TvvIzkvovlpoIgMjMtNgogICAgICAgICAgICBpZiBtaW51dGVfb2ZfZGF5ID49IHN0YXJ0IG9yIG1pbnV0ZV9vZl9kYXkgPCBlbmQ6CiAgICAgICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgcmV0dXJuIEZhbHNlCgoKZGVmIGlzX3F1aWV0X21pbnV0ZShtaW51dGVfb2ZfZGF5OiBpbnQsIHF1aWV0X2hvdXJzX3N0cjogc3RyKSAtPiBib29sOgogICAgIiIi5Yik5patIGRheSDlhoXmn5DliIbpkp/mmK/lkKblpITkuo7lhY3miZPmibDml7bmrrXvvIjkuI4gaXNfcXVpZXRfdGltZSDlkIzkuIDlpZfop4TliJnvvInjgIIiIiIKICAgIHNwYW5zID0gcGFyc2VfcXVpZXRfc3BhbnMocXVpZXRfaG91cnNfc3RyKQogICAgaWYgbm90IHNwYW5zOgogICAgICAgIHJldHVybiBGYWxzZQogICAgcmV0dXJuIF9pbl9zcGFucyhtaW51dGVfb2ZfZGF5LCBzcGFucykKCgpkZWYgaXNfcXVpZXRfdGltZShxdWlldF9ob3Vyc19zdHI6IHN0ciwgdHo6IHpvbmVpbmZvLlpvbmVJbmZvIHwgTm9uZSkgLT4gYm9vbDoKICAgICIiIuajgOafpeW9k+WJjeaXtumXtOaYr+WQpuWkhOS6juWFjeaJk+aJsOaXtuauteOAggoKICAgIOaUr+aMgeWkmuauteS4juWNiuWwj+aXtueykuW6pu+8jOS+i+WmgiAiMC04OjMwLDEyLTEzOjMwLDE4LTI0IuOAggogICAg6YWN572u5pW05L2T6Z2e5rOV5pe25oyJ4oCc6Z2e5YWN5omT5omw4oCd5aSE55CG77yM6YG/5YWN6K+v6Zi75pat5Li75Yqo5raI5oGv44CCCiAgICAiIiIKICAgIHRyeToKICAgICAgICBub3cgPSBkYXRldGltZS5ub3codHopIGlmIHR6IGVsc2UgZGF0ZXRpbWUubm93KCkKICAgIGV4Y2VwdCAoVmFsdWVFcnJvciwgVHlwZUVycm9yKToKICAgICAgICByZXR1cm4gRmFsc2UKICAgIHJldHVybiBpc19xdWlldF9taW51dGUobm93LmhvdXIgKiA2MCArIG5vdy5taW51dGUsIHF1aWV0X2hvdXJzX3N0cikKCgpkZWYgbmV4dF9hY3RpdmVfb2Zmc2V0KAogICAgcXVpZXRfaG91cnNfc3RyOiBzdHIsCiAgICBub3dfbWludXRlOiBpbnQsCiAgICBtYXhfbG9va2FoZWFkOiBpbnQgPSBfREFZX01JTlVURVMsCikgLT4gaW50IHwgTm9uZToKICAgICIiIui/lOWbnuS7jiBub3dfbWludXRlIOi1t++8jOWkmuWwkeWIhumSn+WQjui/m+WFpeS4i+S4gOS4quWPr+WPkemAgeaXtuWIu+OAggoKICAgIOaMieWIhumSn+eykuW6puWQkeWJjeaJvu+8jOacgOWkmueciyBtYXhfbG9va2FoZWFkIOWIhumSn++8iOm7mOiupOS4gOaVtOWkqe+8ieOAggogICAg5rKh5pyJ5Lu75L2V5Y+v5Y+R6YCB5pe25Yi777yI5L6L5aaC5YWo5aSp5YWN5omT5omw77yJ5pe26L+U5ZueIE5vbmXjgIIKICAgICIiIgogICAgc3BhbnMgPSBwYXJzZV9xdWlldF9zcGFucyhxdWlldF9ob3Vyc19zdHIpCiAgICBpZiBub3Qgc3BhbnM6CiAgICAgICAgcmV0dXJuIDAKICAgIGZvciBvZmZzZXQgaW4gcmFuZ2UoMCwgbWF4X2xvb2thaGVhZCArIDEpOgogICAgICAgIGlmIG5vdCBfaW5fc3BhbnMobm93X21pbnV0ZSArIG9mZnNldCwgc3BhbnMpOgogICAgICAgICAgICByZXR1cm4gb2Zmc2V0CiAgICByZXR1cm4gTm9uZQoKCmRlZiBmb3JtYXRfY3VycmVudF90aW1lKHR6OiB6b25laW5mby5ab25lSW5mbyB8IE5vbmUgPSBOb25lKSAtPiBzdHI6CiAgICAiIiLov5Tlm57luKbkuK3mlofmmJ/mnJ/nmoTml7bpl7TlrZfnrKbkuLLvvIzkvovlpoIgMjAyNuW5tDA15pyIMTLml6Ug5ZGo5LqMIDA5OjUz44CCCgogICAg5pif5pyf5L+h5oGv55u05o6l55SxIGRhdGV0aW1lIOiuoeeul+W+l+WHuu+8jOmBv+WFjeaooeWei+iHquihjOeUseaXpeacn+WPjeaOqOaYn+acn+WHoOiAjOeul+mUmeOAggogICAgIiIiCiAgICBub3cgPSBkYXRldGltZS5ub3codHopIGlmIHR6IGVsc2UgZGF0ZXRpbWUubm93KCkKICAgIHdlZWtkYXkgPSBfV0VFS0RBWV9OQU1FU19aSFtub3cud2Vla2RheSgpXQogICAgcmV0dXJuIGYie25vdy5zdHJmdGltZSgnJVnlubQlbeaciCVk5pelJyl9IHt3ZWVrZGF5fSB7bm93LnN0cmZ0aW1lKCclSDolTScpfSIK
B64_EOF
base64 -d "$TU.b64" > "$TU.new" && mv "$TU.new" "$TU" && rm -f "$TU.b64"
echo "  已替换：$TU （$(wc -c < "$TU") 字节）"

echo ""
echo "== 2. 给 scheduler_service.py 打补丁（排期直接跳过静默段）=="
PATCHED=$(grep -c "next_active_offset" "$SS" || true)
if [ "$PATCHED" != "0" ]; then
  echo "  已打过补丁，跳过"
else
  cp -a "$SS" "$SS.bak.$(date +%Y%m%d%H%M%S)"
  python3 - "$SS" <<'PYEOF'
import io, sys
path = sys.argv[1]
src = io.open(path, encoding="utf-8").read()

old_import = "from ..domain.session_key import is_friend_type"
new_import = old_import + "\nfrom ..utils.time_utils import next_active_offset"
if src.count(old_import) != 1:
    raise SystemExit("  !! 导入锚点不唯一，中止（插件版本可能不同）")
if src.count(new_import) != 0:
    raise SystemExit("  !! 补丁已存在，中止")

old_body = (
    "        random_interval = random.randint(min_interval, max_interval)\n"
    "        scheduled_at = time.time()\n"
    "        next_trigger_time = scheduled_at + random_interval\n"
    "        run_date = datetime.fromtimestamp(next_trigger_time, tz=plugin.timezone)\n"
)
new_body = (
    "        random_interval = random.randint(min_interval, max_interval)\n"
    "        scheduled_at = time.time()\n"
    "        next_trigger_time = scheduled_at + random_interval\n"
    "        # 随机出来的时刻若落在免打扰时段，整体推到下一个可发送时刻，\n"
    "        # 免得\"排到 12:10 -> GATE 拦下 -> 再随机一次\"来回抖。\n"
    "        quiet_hours_str = schedule_conf.get(\"quiet_hours\", \"\") or \"\"\n"
    "        if quiet_hours_str:\n"
    "            candidate = datetime.fromtimestamp(next_trigger_time, tz=plugin.timezone)\n"
    "            minute_of_day = candidate.hour * 60 + candidate.minute\n"
    "            offset = next_active_offset(quiet_hours_str, minute_of_day)\n"
    "            if offset:\n"
    "                next_trigger_time += offset * 60\n"
    "        run_date = datetime.fromtimestamp(next_trigger_time, tz=plugin.timezone)\n"
)
if src.count(old_body) != 1:
    raise SystemExit("  !! 排期代码锚点不唯一或已改，中止（插件版本可能不同）")

src = src.replace(old_import, new_import).replace(old_body, new_body)
io.open(path, "w", encoding="utf-8").write(src)
print("  补丁已写入")
PYEOF
  # 语法自检，坏了立刻回滚
  if ! python3 -m py_compile "$SS"; then
    echo "  !! 编译失败，回滚"
    mv "$SS.bak."* "$SS" 2>/dev/null || true
    exit 1
  fi
  echo "  语法自检通过"
fi

echo ""
echo "== 3. 写配置：活跃时段更密 + 三段静默 =="
python3 - <<'PYEOF'
import json
p = "/opt/miruku/astrbot/data/config/astrbot_plugin_proactive_chat_config.json"
d = json.load(open(p, encoding="utf-8-sig"))
f = d["friend_settings"]
s = f.setdefault("schedule_settings", {})
a = f.setdefault("auto_trigger_settings", {})

before = (
    s.get("min_interval_minutes"),
    s.get("max_interval_minutes"),
    s.get("quiet_hours"),
    a.get("auto_trigger_after_minutes"),
)

# 间隔 25-55 分钟：原来 30-75 是按全天摊的，早上那两小时平均只落 4 条。
# 现在消息全挤进 8.5 小时里，间隔收到 25-55（均 40），上午约 5 条、下午约 7 条，
# 每条间隔体感更密，又不至于变成连环催。
s["min_interval_minutes"] = 25
s["max_interval_minutes"] = 55
# 三段静默（前闭后开，端点 24 = 当天末尾）：
#   0:00-8:30 睡前+早课 / 12:00-13:30 午休 / 18:00-24:00 晚课后到睡前
s["quiet_hours"] = "0-8:30,12-13:30,18-24"
# 他 60 分钟没说话就主动找一次（撞上静默就不发，等下一个活跃时刻）
a["auto_trigger_after_minutes"] = 60
a["enable_auto_trigger"] = True
# 不限制"对方没回复"的次数（之前 OTTO 的决定，保持）
s["max_unanswered_times"] = 0

json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print("  间隔:     {}-{} -> {}-{} 分钟".format(before[0], before[1], 25, 55))
print("  静默:     {} -> {}".format(before[2], s["quiet_hours"]))
print("  静默触发: {} -> {} 分钟".format(before[3], a["auto_trigger_after_minutes"]))
print("  最大未回复: {}".format(s["max_unanswered_times"]))
PYEOF

echo ""
echo "== 4. 重启 astrbot =="
docker restart astrbot >/dev/null 2>&1
for i in $(seq 1 24); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:6185/api/v1/system-config 2>/dev/null || echo 000)
  case "$code" in 401|200) echo "  就绪 t+$((i*5))s"; break ;; esac
done

echo ""
echo "== 5. 验证新解析器（1=静默，0=可发）=="
cd /opt/miruku/astrbot/data/plugins/astrbot_plugin_proactive_chat && python3 -c "
import sys
sys.path.insert(0, '.')
from utils.time_utils import is_quiet_minute, next_active_offset
q = '0-8:30,12-13:30,18-24'
def hh(m):
    return '%02d:%02d' % (m // 60, m % 60)
row = []
for m in (0, 480, 510, 540, 719, 720, 810, 840, 1079, 1080, 1200, 1439):
    row.append('%s:%d' % (hh(m), 1 if is_quiet_minute(m, q) else 0))
print('  ' + '  '.join(row))
print('  期望:  08:30/12:00/13:30/18:00 这四个边界上应为 0，其它列出时刻应为 1')
for m in (0, 720, 810, 1080, 1439):
    off = next_active_offset(q, m)
    print('  {} 起 -> {}'.format(hh(m), ('+%d 分钟' % off) if off is not None else '全天静默，无处可发'))
"

echo ""
echo "== 6. 当前排期 =="
curl -s --max-time 8 http://127.0.0.1:4100/api/jobs | python3 -c "
import sys, json, datetime
d = json.load(sys.stdin)
jobs = d.get('jobs', [])
now = datetime.datetime.now()
for j in jobs:
    nxt = (j.get('next_run_time') or '')[:19]
    try:
        t = datetime.datetime.fromisoformat(nxt)
        print('  下次: {} ({} 分钟后)'.format(nxt, round((t - now).total_seconds() / 60)))
    except Exception:
        print('  下次: {}'.format(nxt))
print('  jobs 数: {}'.format(len(jobs)))
"

echo ""
echo "== 完成 =="
echo "  回滚：把 time_utils.py / scheduler_service.py 的 .bak.* 复制回去，"
echo "        再把 schedule_settings.quiet_hours 改回原值，重启 astrbot 即可。"
