#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Miruku 服务器管理面板（本地启动，数据全部经 SSH 从服务器取，不开任何公网端口）。

用法： python panel.py   （由 启动面板.bat 调用，也可单独跑，前提是隧道已在跑）

路由：
  GET /                    面板页面
  GET /api/status          服务器/服务/机器人状态（ssh 执行 server/panel-status.py）
  GET /api/logs?src=..&n=  容器日志（src=astrbot|napcat|heartbeat）
三个 WebUI（AstrBot / NapCat / noVNC）由 SSH 隧道映射到本机回环，页面里 iframe 内嵌。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SSH_HOST = os.environ.get("MIRUKU_SSH", "root@203.0.113.10")
PORT = int(os.environ.get("MIRUKU_PANEL_PORT", "8642"))
REMOTE_DIR = "/opt/miruku/server"

# Windows 下 ssh 走系统 OpenSSH；密钥交给 ssh-agent，本脚本不接触私钥
SSH_BASE = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", SSH_HOST]

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def ssh_run(cmd: str, timeout: int = 25) -> tuple[int, str, str]:
    try:
        p = subprocess.run(SSH_BASE + [cmd], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:  # noqa: BLE001
        return 1, "", f"{type(exc).__name__}: {exc}"


def cached(key: str, ttl: float, fn):
    with _lock:
        now = time.time()
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        val = fn()
        _cache[key] = (now, val)
        return val


def fetch_status():
    def go():
        rc, out, err = ssh_run(
            f"python3 {REMOTE_DIR}/panel-status.py")
        if rc != 0 or not out.strip():
            return {"error": (err or out or f"ssh rc={rc}")[:400]}
        try:
            return json.loads(out.strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001
            return {"error": f"解析失败 {exc}: {out[:200]}"}
    return cached("status", 8.0, go)


LOG_SOURCES = {
    "astrbot": "docker logs astrbot --tail {n} --timestamps 2>&1 | tail -n {n}",
    "napcat": "docker logs napcat --tail {n} --timestamps 2>&1 | grep -vE '^[0-9a-f]{{40,}}$' | tail -n {n}",
    "heartbeat": "tail -n {n} /var/log/miruku-heartbeat.log 2>&1",
    "journal": "journalctl -u miruku-heartbeat.service -n {n} --no-pager 2>&1 | tail -n {n}",
}


def fetch_logs(src: str, n: int):
    tpl = LOG_SOURCES.get(src)
    if not tpl:
        return {"error": f"未知日志源 {src}"}
    n = max(10, min(int(n or 200), 2000))

    def go():
        rc, out, err = ssh_run(tpl.format(n=n), timeout=30)
        text = out if out.strip() else (err or "")
        # 去 ANSI 色码
        import re
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
        text = re.sub(r"(\d{3})\d{4}(\d{3})", r"\1***\2", text)  # 日志里偶现的号码统一掩码
        return {"src": src, "lines": text.count("\n"), "text": text[-400_000:]}
    return cached(f"logs:{src}:{n}", 5.0, go)


PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Miruku 服务器面板</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#252a35;--fg:#dfe3ea;--dim:#8b93a3;
--ok:#3fb950;--bad:#f85149;--warn:#d29922;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 "Microsoft YaHei",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:#12151ce8;backdrop-filter:blur(6px);
border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
header b{font-size:15px}header .sp{flex:1}
button,a.tab{background:var(--card);border:1px solid var(--line);color:var(--fg);
padding:6px 12px;border-radius:8px;cursor:pointer;text-decoration:none;font-size:13px}
button:hover,a.tab:hover{border-color:var(--acc)}
main{padding:16px;max-width:1280px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.card h3{margin:0 0 10px;font-size:13px;color:var(--dim);font-weight:600;letter-spacing:.4px}
.kv{display:flex;justify-content:space-between;gap:12px;padding:3px 0;border-bottom:1px dashed #22262f}
.kv:last-child{border-bottom:0}.kv span:first-child{color:var(--dim)}
.pill{padding:1px 8px;border-radius:99px;font-size:12px}
.p-ok{background:#12351c;color:var(--ok)}.p-bad{background:#3a1214;color:var(--bad)}
.p-warn{background:#3a2c10;color:var(--warn)}
.bar{height:6px;background:#22262f;border-radius:3px;overflow:hidden;margin-top:4px}
.bar i{display:block;height:100%;background:var(--acc)}
pre{background:#0b0d12;border:1px solid var(--line);border-radius:8px;padding:10px;
max-height:420px;overflow:auto;font:12px/1.5 Consolas,monospace;white-space:pre-wrap;word-break:break-all}
.tabs{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.tabs .on{border-color:var(--acc);color:#fff;background:#1b2431}
section{display:none}section.on{display:block}
.frame{width:100%;height:calc(100vh - 132px);border:1px solid var(--line);
border-radius:12px;background:#fff}
.hint{color:var(--dim);font-size:12px;margin:6px 0}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
select,input{background:var(--card);border:1px solid var(--line);color:var(--fg);
padding:5px 8px;border-radius:7px}
</style></head><body>
<header>
  <b>Miruku 面板</b><span id="hostchip" class="hint">连接中…</span>
  <span class="sp"></span>
  <a class="tab on" href="#s" onclick="show('s',this)">状态</a>
  <a class="tab" href="#bot" onclick="show('bot',this)">机器人</a>
  <a class="tab" href="#log" onclick="show('log',this)">日志</a>
  <a class="tab" href="#ab" onclick="show('ab',this)">AstrBot</a>
  <a class="tab" href="#nc" onclick="show('nc',this)">NapCat·扫码</a>
  <a class="tab" href="#vn" onclick="show('vn',this)">noVNC</a>
  <button onclick="refresh(true)">刷新</button>
</header>
<main>
<section id="s" class="on">
  <div class="grid" id="statusGrid"></div>
  <div class="hint" id="lastErr"></div>
</section>
<section id="bot"><div class="grid" id="botGrid"></div></section>
<section id="log">
  <div class="row">
    <select id="logSrc">
      <option value="astrbot">AstrBot 容器</option>
      <option value="napcat">NapCat 容器</option>
      <option value="heartbeat">心跳</option>
      <option value="journal">心跳服务(journal)</option>
    </select>
    <select id="logN"><option>100</option><option selected>300</option><option>800</option><option>2000</option></select>
    <label><input type="checkbox" id="logAuto" checked> 自动跟随(10s)</label>
    <button onclick="loadLogs()">拉取</button>
    <button onclick="document.getElementById('logBox').textContent=''">清空视图</button>
  </div>
  <pre id="logBox">（未加载）</pre>
</section>
<section id="ab"><iframe class="frame" src="http://127.0.0.1:6185/"></iframe></section>
<section id="nc">
  <div class="hint">登录二维码在此页面（NapCat WebUI → 导航/Overview）。token：<code>见 面板凭据.txt</code>
  　若 iframe 空白请 <a style="color:var(--acc)" target="_blank" href="http://127.0.0.1:6099/webui/">新窗口打开</a></div>
  <iframe class="frame" src="http://127.0.0.1:6099/webui/"></iframe>
</section>
<section id="vn"><div class="hint">运维兜底桌面（QQ 在 Linux 下无窗口，扫码请用左边 NapCat 页）。密码见 面板凭据.txt</div>
  <iframe class="frame" src="http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale"></iframe></section>
</main>
<script>
const $=s=>document.querySelector(s);
function show(id,el){document.querySelectorAll('section').forEach(x=>x.classList.remove('on'));
 $('#'+id).classList.add('on');document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
 el.classList.add('on'); if(id==='log')loadLogs();}
const pill=(ok,t)=>`<span class="pill ${ok?'p-ok':'p-bad'}">${t||(ok?'在线':'离线')}</span>`;
const pw=(w,t)=>`<span class="pill ${w?'p-warn':'p-ok'}">${t}</span>`;
function kv(pairs){return pairs.map(([k,v])=>`<div class="kv"><span>${k}</span><span>${v}</span></div>`).join('');}
function card(t,html){return `<div class="card"><h3>${t}</h3>${html}</div>`;}
function banner(d){
  // QQ 掉线时给一条最显眼的红条。2026-10-27 的教训：容器 running、6199 连着，
  // 都不代表她在线——只有 NapCat 真有活动才算。那次漏看 3 小时才被人发现。
  if (d.needs_rescan) return `<div class="card" style="border-color:#f85149;background:#2b1113;margin-bottom:12px">
    <h3 style="color:#f85149">QQ 已掉线，需要重新扫码</h3>
    <div style="margin-top:6px">心跳在 <b>${d.needs_rescan}</b> 检测到 NapCat 长时间无活动。
    去 <b>NapCat·扫码</b> 页扫一次二维码即可恢复；<b>不要重启容器</b>——重启会让登录态失效，反而要重扫。</div>
    </div>`;
  if (d.last_status && d.last_status !== 'OK') return `<div class="card" style="border-color:#d29922;background:#2b2410;margin-bottom:12px">
    <h3 style="color:#d29922">心跳状态：${d.last_status}</h3>
    <div style="margin-top:6px">详见「日志 → 心跳」。若是 NO_WS_LINK 多为 AstrBot 侧问题；QQ_OFFLINE 才需要扫码。</div>
    </div>`;
  return '';
}
async function refresh(force){
 try{
  const r=await fetch('/api/status'+(force?'?t='+Date():''),{cache:'no-store'});
  const d=await r.json();
  if(d.error){$('#lastErr').textContent='状态获取失败：'+d.error;return;}
  $('#lastErr').textContent='';
  const h=d.host,s=d.services,l=d.link;
  $('#hostchip').textContent=`${h.hostname} · ${h.os} · ${h.ip}`;
  const memPct=Math.round(100*(h.mem_total_mb-h.mem_avail_mb)/h.mem_total_mb);
  const up=s.containers.astrbot.status==='running'&&s.containers.napcat.status==='running';
  $('#statusGrid').innerHTML=
   banner(d)+
   card('总览',kv([['机器人',up?pill(1,'运行中'):pill(0,'停了')],
     ['QQ 在线',d.needs_rescan?pill(0,'需扫码'):(d.last_status==='OK'?pill(1,'在线'):pw(true,d.last_status||'-'))],
     ['6199 链路',l.ws6199_established>=1?pill(1,'已连接'):pw(true,`未连接(${l.ws6199_established})`)],
     ['心跳',pill(d.last_status==='OK',d.last_status||'未知')],
     ['负载',(h.load||[]).join(' / ')||'-']]))+
   card('主机',kv([['系统',h.os],['内核',h.kernel],['CPU',h.cpu_cores+' 核'],
     ['运行时长',h.uptime||'-'],
     ['内存',`${h.mem_used_mb} / ${h.mem_total_mb} MB (用 ${memPct}%)`],
     ['可用',h.mem_avail_mb+' MB'],['Swap',h.swap_total_mb+' MB'],['磁盘',h.disk]]))+
   card('容器',kv(Object.entries(s.containers).map(([k,v])=>[k,
     `${pill(v.status==='running',v.status)} 重启${v.restarts}次`])))+
   card('系统服务',kv(Object.entries(s.systemd).map(([k,v])=>[k,pill(v==='active',v)])));
  const b=d.bot;
  $('#botGrid').innerHTML=
   card('平台与人格',kv([['人格',b.persona],
     ...b.platforms.map(p=>[p.id,`${p.type} ws=${p.ws} ${pill(!!p.enable,p.enable?'启用':'停用')}`])]))+
   card('模型',kv([...(b.providers||[]).map(p=>['会话模型',`${p.id} ${pill(!!p.enable,p.enable?'启用':'停用')}`]),
     ...(b.provider_sources||[]).map(p=>[`源 ${p.id}`,`${p.base} 凭据:${p.cred}`])]))+
   card('主动消息',kv([['开关',pill(!!b.proactive.enable)],
     ['收件人',(b.proactive.recipients||[]).join('<br>')||'-'],
     ['间隔',`${b.proactive.interval_minutes?.[0]}–${b.proactive.interval_minutes?.[1]} 分钟`],
     ['免打扰',b.proactive.quiet_hours],['未回复上限',b.proactive.max_unanswered===0?'不限制':b.proactive.max_unanswered],
     ['静默自动触发',b.proactive.auto_trigger?`开 · ${b.proactive.auto_trigger_after_minutes} 分钟`:'关'],
     ['排期任务',(b.jobs||[]).map(j=>`${j.umo}<br>下次 ${j.next} · 未回 ${j.unanswered}`).join('<br>')||'（当前无排期任务）']]))+
   card('知识库 / 插件',kv([['知识条目',b.knowledge.entries+' 条'],
     ['注入对象',b.knowledge.target_qq],
     ...(b.plugins||[]).map(p=>[p.replace('astrbot_plugin_',''),(b.plugin_versions||{})[p]||'-'])]));
 }catch(e){$('#lastErr').textContent='请求失败：'+e;}
}
async function loadLogs(){
 const src=$('#logSrc').value,n=$('#logN').value;
 $('#logBox').textContent='加载中…';
 const r=await fetch(`/api/logs?src=${src}&n=${n}`,{cache:'no-store'});
 const d=await r.json();
 $('#logBox').textContent=d.error?('失败：'+d.error):(d.text||'（空）');
 $('#logBox').scrollTop=$('#logBox').scrollHeight;
}
setInterval(()=>{if(!document.hidden)refresh();},15000);
setInterval(()=>{if(!document.hidden&&$('#s').classList.contains('on')===false&&$('#log').classList.contains('on')&&$('#logAuto').checked)loadLogs();},10000);
refresh();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静音
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif u.path == "/api/status":
            self._send(200, json.dumps(fetch_status(), ensure_ascii=False))
        elif u.path == "/api/logs":
            q = urllib.parse.parse_qs(u.query)
            self._send(200, json.dumps(
                fetch_logs(q.get("src", ["astrbot"])[0], int(q.get("n", ["300"])[0])),
                ensure_ascii=False))
        elif u.path == "/healthz":
            self._send(200, "ok", "text/plain; charset=utf-8")
        else:
            self._send(404, '{"error":"not found"}')


def main():
    print(f"[panel] http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
