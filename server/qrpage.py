#!/usr/bin/env python3
"""Miruku 手机扫码页（服务器侧，公网 HTTPS）

用途：QQ 掉线时用手机扫码登录，不必开电脑、不必连 SSH 隧道。
原理：容器里有 xwd + xdotool，没有 PIL/convert —— 自己把 XWD 转成 PNG（只用标准库 zlib）。

安全：
  - 只暴露「看屏幕 / 点一下 / 刷二维码」三件事，不提供 shell。
  - 首次启动生成随机 32 位 token，写 /opt/miruku/logs/qrpage-token；未带 token 一律 403。
  - 绑定 0.0.0.0 但由 systemd 启动；公网入口见 nginx（自签 TLS 或 Caddy）。

接口：
  GET  /?t=TOKEN                 扫码页
  GET  /shot?t=TOKEN&w=..        当前屏幕 JPEG 前的 PNG（自动缩放）
  POST /tap?t=TOKEN&x=..&y=..    在 (x,y) 点一下
  POST /refresh?t=TOKEN          点 QQ 登录窗的「刷新」按钮（按窗口坐标推算）
  GET  /healthz                  无 token 健康检查
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CONTAINER = "snowluma"
LOGDIR = pathlib.Path("/opt/miruku/logs")
TOKEN_FILE = LOGDIR / "qrpage-token"
PORT = int(os.environ.get("QRPAGE_PORT", "8663"))
# 默认只听 127.0.0.1：token 泄露就等于能操作 QQ 桌面，必须靠隧道/反代出去。
# 要通过反代暴露时用 QRPAGE_BIND=0.0.0.0（并确保有 TLS + 只在内网/隧道里）。
BIND = os.environ.get("QRPAGE_BIND", "127.0.0.1")

# 坐标校准（2026-11-01 实测）：xwd 截图里 QQ 窗口左边缘在 x=360，而
# `xdotool getwindowgeometry` 报 Position=600,210 —— 横坐标固定差 240，纵坐标一致。
# 该窗口不可 windowmove（移动无效），所以偏移稳定；若将来换分辨率/换桌面，用
# 环境变量 QRPAGE_TAP_OFFSET_X 覆盖即可（校准法：截图找窗口左边缘 E，令 offset = xdotool_Pos_x - E）。
TAP_OFFSET_X = int(os.environ.get("QRPAGE_TAP_OFFSET_X", "240"))

# 登录窗里「刷新」按钮相对 QQ 窗口左上角的位置（窗口 320x460，按钮在底部区域）
REFRESH_BTN = (150, 400)

_lock = threading.Lock()
_cache = {"t": 0.0, "png": b""}


# ---------------- 容器执行 ----------------
def cexec(cmd: str, timeout: int = 20) -> bytes:
    try:
        return subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "sh", "-c", cmd],
            capture_output=True, timeout=timeout).stdout
    except Exception:
        return b""


def container_alive() -> bool:
    try:
        out = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", CONTAINER],
                             capture_output=True, text=True, timeout=8).stdout.strip()
        return out == "running"
    except Exception:
        return False


# ---------------- XWD -> PNG ----------------
def xwd_to_png(raw: bytes, crop_box: tuple[int, int, int, int] | None = None) -> bytes:
    """把 XWD(ver 7, ZPixmap) 转成 PNG。只支持 24/32bpp，够用。

    XWDFileHeader（大端，共 100 字节）字段顺序：
      0 header_size  4 file_version  8 pixmap_format  12 pixmap_depth
     16 pixmap_width 20 pixmap_height 24 xoffset 28 byte_order
     32 bitmap_unit 36 bitmap_bit_order 40 bitmap_pad **44 bits_per_pixel**
     48 bytes_per_line 52 visual_class 56/60/64 rgb masks 68 bits_per_rgb
     72 colormap_entries **76 ncolors** 80/84 window_width/height 88/92 window_x/y 96 bdrwidth

    crop_box=(x,y,w,h) 只输出该矩形（原图像素坐标）。
    注意：裁剪后前端点击坐标要补回 (x,y)，响应头 X-Crop-X/Y 负责告知。
    """
    if len(raw) < 100:
        raise ValueError("XWD too short")

    def u32(off):
        return struct.unpack(">I", raw[off:off + 4])[0]

    if u32(0) < 100 or u32(4) != 7:
        raise ValueError(f"not XWD v7 (hdr={u32(0)} ver={u32(4)})")

    hdr_size = u32(0)
    width, height = u32(16), u32(20)
    bpp = u32(44)
    bpl = u32(48)
    ncolors = u32(76)

    if not width or not height or not bpl:
        raise ValueError("空图像")

    per_px = bpl // width if width else 4
    if per_px not in (3, 4):
        per_px = 4 if bpp >= 32 else 3

    pix_off = hdr_size + ncolors * 12
    if len(raw) < pix_off + height * bpl:
        raise ValueError("truncated XWD")

    # 先解出整屏 RGB
    width3 = width * 3
    full = bytearray(height * width3)
    for y in range(height):
        base = pix_off + y * bpl
        row = raw[base:base + width * per_px]
        off = y * width3
        if per_px == 4:
            full[off + 0:off + width3:3] = row[2::4]
            full[off + 1:off + width3:3] = row[1::4]
            full[off + 2:off + width3:3] = row[0::4]
        else:
            full[off + 0:off + width3:3] = row[2::3]
            full[off + 1:off + width3:3] = row[1::3]
            full[off + 2:off + width3:3] = row[0::3]

    crop_rect = (0, 0, width, height)
    if crop_box:
        bx, by, bw, bh = crop_box
        bx = max(0, min(bx, width - 1))
        by = max(0, min(by, height - 1))
        bw = min(bw, width - bx)
        bh = min(bh, height - by)
        if bw > 0 and bh > 0:
            crop_rect = (bx, by, bw, bh)
    cx, cy, cw, ch = crop_rect
    if (cw, ch) != (width, height):
        sub = bytearray(ch * cw * 3)
        for y in range(ch):
            s = ((cy + y) * width + cx) * 3
            sub[y * cw * 3:(y + 1) * cw * 3] = full[s:s + cw * 3]
        full, width, height = sub, cw, ch
    _last_crop[0] = crop_rect

    rows = []
    width3 = width * 3
    for y in range(height):
        rows.append(b"\x00" + bytes(full[y * width3:(y + 1) * width3]))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
           + chunk(b"IEND", b""))
    return png


_last_crop = [(0, 0, 0, 0)]


def grab_png(max_age: float = 1.0, mode: str = "auto") -> bytes:
    """截当前屏幕。mode=auto 裁到 QQ 窗口（手机上看码更大），full=整屏。缓存 1 秒。"""
    with _lock:
        key = mode
        if (time.time() - _cache["t"] < max_age and _cache["png"]
                and _cache.get("mode") == key):
            return _cache["png"]
        if not container_alive():
            raise RuntimeError("snowluma 容器未运行")
        raw = cexec("xwd -root -silent 2>/dev/null | cat")
        if not raw:
            raise RuntimeError("xwd 无输出")
        box = window_box() if mode != "full" else None
        png = xwd_to_png(raw, crop_box=box)
        _cache.update(t=time.time(), png=png, mode=key)
        return png


def window_box() -> tuple[int, int, int, int] | None:
    """QQ 窗口在**截图坐标系**里的矩形 (x, y, w, h)；找不到返回 None（=整屏）。

    实测：xdotool Position 比截图横坐标多 240px，纵坐标一致。
    优先取「登录窗」——扫码时二维码在登录窗里（约 320x460），裁它比裁聊天窗好用；
    没有登录窗（已登录）时退回面积最大的主窗口。
    """
    geo = cexec("xdotool search --name QQ 2>/dev/null | xargs -r -n1 xdotool getwindowgeometry"
                ).decode()
    main_win = None      # 主窗口：面积最大
    login_win = None     # 登录窗：窄而小
    for blk in geo.split("Window ")[1:]:
        m_pos = re.search(r"Position:\s*(-?\d+),(-?\d+)", blk)
        m_geo = re.search(r"Geometry:\s*(\d+)x(\d+)", blk)
        if not (m_pos and m_geo):
            continue
        w, h = int(m_geo.group(1)), int(m_geo.group(2))
        if w < 200 or h < 300:      # 过滤 10x10 / 1x1 / 18x18 托盘图标
            continue
        px, py = int(m_pos.group(1)), int(m_pos.group(2))
        area = w * h
        if main_win is None or area > main_win[0]:
            main_win = (area, px, py, w, h)
        if w <= 520 and 380 <= h <= 720:
            if login_win is None or area > login_win[0]:
                login_win = (area, px, py, w, h)
    best = login_win or main_win
    if not best:
        return None
    _, px, py, w, h = best
    return (max(0, px - TAP_OFFSET_X), max(0, py), w, h)


# ---------------- QQ 窗口操作 ----------------
def qq_window_id() -> str | None:
    out = cexec("xdotool search --name QQ 2>/dev/null | head -1").decode().strip()
    return out or None


def tap(screen_x: int, screen_y: int) -> str:
    """screen_x/y 是「截图里的像素坐标」；转成 xdotool 坐标再点。"""
    tx, ty = screen_x + TAP_OFFSET_X, screen_y
    cexec(f"xdotool mousemove {tx} {ty} click 1")
    return f"点了截图坐标 {screen_x},{screen_y} → 实际 {tx},{ty}"


def click_refresh() -> str:
    """按 QQ 登录窗位置推算「刷新」按钮并点击（截图坐标系）。"""
    geo = cexec("xdotool search --name QQ 2>/dev/null | xargs -r -n1 xdotool getwindowgeometry"
                ).decode()
    # 取面积最大的那个 QQ 窗口当作登录窗
    best = None
    for blk in geo.split("Window ")[1:]:
        m_pos = re.search(r"Position:\s*(-?\d+),(-?\d+)", blk)
        m_geo = re.search(r"Geometry:\s*(\d+)x(\d+)", blk)
        if not (m_pos and m_geo):
            continue
        w, h = int(m_geo.group(1)), int(m_geo.group(2))
        if w * h < 200 * 300:      # 过滤 10x10 / 1x1 之类的杂项窗口
            continue
        if h > 700:                # 主面板不是登录窗
            continue
        area = w * h
        if best is None or area > best[0]:
            best = (area, int(m_pos.group(1)), int(m_pos.group(2)), w, h)
    if not best:
        return "找不到 QQ 登录窗"
    _, px, py, w, h = best
    sx = px - TAP_OFFSET_X + REFRESH_BTN[0]
    sy = py + REFRESH_BTN[1]
    cexec(f"xdotool mousemove {sx} {sy} click 1")
    return f"点了刷新（窗口 {w}x{h} @ {px},{py}）→ 实际 {sx},{sy}"


def unmap_windows() -> str:
    """把缩在托盘里的 QQ 窗口 map 回来并激活。"""
    out = cexec("xdotool search --name QQ 2>/dev/null").decode().split()
    done = []
    for w in out:
        cexec(f"xdotool windowmap {w} 2>/dev/null; xdotool windowactivate {w} 2>/dev/null")
        done.append(w)
    if not done:
        return "没有 QQ 窗口"
    cexec("xdotool search --name QQ 2>/dev/null | xargs -r -n1 xdotool windowmap 2>/dev/null")
    return f"map 了 {len(done)} 个窗口"


# ---------------- token ----------------
def load_token() -> str:
    LOGDIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.is_file():
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    t = os.urandom(16).hex()
    TOKEN_FILE.write_text(t, encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)
    return t


TOKEN = load_token()

PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Miruku 扫码</title><style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#0d1117;color:#c9d1d9;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:9;display:flex;gap:8px;align-items:center;padding:10px 12px;
 background:#161b22;border-bottom:1px solid #30363d;flex-wrap:wrap}
header b{color:#e6edf3}
.sp{flex:1}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;
 padding:8px 12px;font-size:14px;cursor:pointer}
button:active{background:#30363d}
button.pri{background:#1f6feb;border-color:#1f6feb;color:#fff}
button.pri:active{background:#388bfd}
#msg{padding:6px 12px;font-size:13px;color:#8b949e;min-height:26px}
#wrap{position:relative;background:#000;text-align:center;touch-action:manipulation}
#shot{max-width:100%;display:block;margin:0 auto;image-rendering:auto}
#dot{position:absolute;width:18px;height:18px;margin:-9px 0 0 -9px;border:2px solid #f85149;
 border-radius:50%;display:none;pointer-events:none}
.hint{padding:10px 12px;font-size:13px;color:#8b949e;border-top:1px solid #30363d}
code{background:#21262d;padding:1px 5px;border-radius:4px;color:#c9d1d9}
</style></head><body>
<header>
  <b>Miruku 扫码</b><span class="sp"></span>
  <button onclick="shot()">刷新画面</button>
  <button class="pri" onclick="act('unmap')">唤出窗口</button>
  <button class="pri" onclick="act('refresh')">点刷新</button>
</header>
<div id="msg">点画面任意位置＝在那里点一下</div>
<div id="wrap"><img id="shot" alt="screen"><div id="dot"></div></div>
<div class="hint">
  掉线流程：<b>唤出窗口</b> → 关掉安全提醒弹窗（点它的「确认」）→ <b>点刷新</b> → 用手机 QQ 扫屏幕上的码。<br>
  不要重启容器，重启不会让登录态复活。
</div>
<script>
const T=new URLSearchParams(location.search).get('t')||'';
const $=s=>document.querySelector(s);
const img=$('#shot'),dot=$('#dot'),msg=$('#msg');
let loading=false, cropX=0, cropY=0;
function say(t){msg.textContent=t;}
async function shot(){
  if(loading)return; loading=true;
  try{
    const r=await fetch('/shot?t='+T+'&_='+Date.now(),{cache:'no-store'});
    if(!r.ok){say('截图失败：'+(await r.text()).slice(0,120));return;}
    cropX=parseInt(r.headers.get('X-Crop-X')||'0',10);
    cropY=parseInt(r.headers.get('X-Crop-Y')||'0',10);
    const b=await r.blob();
    img.src=URL.createObjectURL(b);
    say('画面已更新 '+new Date().toLocaleTimeString());
  }catch(e){say('截图失败：'+e);}finally{loading=false;}
}
async function act(a){
  say('执行中…');
  try{
    const r=await fetch('/'+a+'?t='+T,{method:'POST'});
    say(await r.text());
    setTimeout(shot,600);
  }catch(e){say('失败：'+e);}
}
img.addEventListener('click',async ev=>{
  const rect=img.getBoundingClientRect();
  const ix=Math.round((ev.clientX-rect.left)*img.naturalWidth/rect.width);
  const iy=Math.round((ev.clientY-rect.top)*img.naturalHeight/rect.height);
  const x=ix+cropX, y=iy+cropY;   // 补回裁剪偏移 → 原图坐标
  dot.style.display='block';
  dot.style.left=(ev.clientX-rect.left)+'px';
  dot.style.top=(ev.clientY-rect.top)+'px';
  say('点了 '+x+','+y+' …');
  try{
    const r=await fetch(`/tap?t=${T}&x=${x}&y=${y}`,{method:'POST'});
    say(await r.text());
    setTimeout(shot,800);
  }catch(e){say('失败：'+e);}
});
shot();
setInterval(()=>{if(!document.hidden)shot();},4000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _authed(self, q):
        return q.get("t", [""])[0] == TOKEN

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/healthz":
            return self._send(200, "ok")
        if not self._authed(q):
            return self._send(403, "forbidden")
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/shot":
            mode = "full" if q.get("full", ["0"])[0] in ("1", "true", "yes") else "auto"
            try:
                png = grab_png(mode=mode)
            except Exception as exc:  # noqa: BLE001
                return self._send(503, f"截图失败：{exc}")
            cx, cy = _last_crop[0][0], _last_crop[0][1]
            return self._send(200, png, "image/png",
                              {"X-Crop-X": str(cx), "X-Crop-Y": str(cy)})
        return self._send(404, "not found")

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authed(q):
            return self._send(403, "forbidden")
        try:
            if u.path == "/tap":
                x = int(q.get("x", ["0"])[0])
                y = int(q.get("y", ["0"])[0])
                return self._send(200, tap(x, y))
            if u.path == "/refresh":
                return self._send(200, click_refresh())
            if u.path == "/unmap":
                return self._send(200, unmap_windows())
        except Exception as exc:  # noqa: BLE001
            return self._send(500, f"失败：{exc}")
        return self._send(404, "not found")


def main():
    print(f"[qrpage] http://{BIND}:{PORT}/?t={TOKEN}")
    print(f"[qrpage] token 文件 {TOKEN_FILE}")
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
