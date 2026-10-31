# 手机扫码页 + 面板凭证栏 + 面板掉线误判修复

日期：2026-11-01
提出人：OTTO（「我这边显示已经掉线，然后每次 novnc 扫码都要凭证，能不能把凭证搞到这个状态栏里，然后再弄个手机也可以扫码的网页」）

## 一、面板误报掉线（与心跳同源的老 bug）

### 现象
面板顶部红条「QQ 已掉线，需要在 noVNC 里重新扫码」，总览卡 QQ 显示「掉线·需扫码」，但机器人当时正常收发消息。

### 根因
`server/panel-status.py` 用的是日志法：

```python
last_hook = sh('docker exec snowluma sh -c "grep -hE \'login detected|awaiting login\' /app/data/logs/*.log" | tail -3')
qq_online = ("login detected" in last_hook)
```

而 SnowLuma 在 2026-10-31 13:03:01 **同一秒**打了两条：

```
13:03:01 OK   [Hook] login detected: PID=25627 UIN=10000004   <- 主进程，真登录
13:03:01 INFO [Hook] awaiting login: PID=13666                   <- 2 天前的 --relaunch 残留进程
```

`tail` 稳定取到后者 → 永久判掉线。与 heartbeat v3 的误报是**同一个僵尸进程**造成的，两处独立实现、同一个坑。

### 修复
改为优先问 SnowLuma 的 OneBot HTTP 接口（`get_status` → `data.online`，再用 `get_login_info` 取 uin），日志法降级为接口不可用时的兜底（且兜底只 grep `login detected`，不再被 `awaiting` 覆盖）。

验证（同一时刻、新旧版对照）：

| 版本 | 输出 |
|---|---|
| 旧（线上） | `online: false`, detail `13:03:01 INFO [Hook] awaiting login: PID=13666` |
| 新 | `online: true`, detail `SnowLuma 接口：online=true uin=376***147` |

### 教训
**同一个上游日志里既有「当前状态」又有「历史事件」时，不要用 `tail` 取最后一条**。要么问权威接口，要么按语义过滤（本项目里 `login detected` 是事件、`awaiting login` 也可能是别的进程的历史回声，两者不可混排比较时间）。

## 二、凭证进面板状态栏

新增 `cred` 段输出（`server/panel-status.py`）：

- `novnc_password`：直接读容器 `/app/data/config/vnc-password`（21 字符明文）。这也是 x11vnc 的密码来源，之前写在本地 `面板凭据.txt` 里，容易丢。
- `novnc_url`、`snowluma_webui`、`snowluma_must_change_pw`（`webui.json` 的 `mustChangePassword`，首启为 true）。
- `qrpage_token` / `qrpage_local`：扫码页 token（见下节）。

面板「状态」页新增**扫码登录**卡片，掉线横幅里也直接给密码和手机链接。

> 安全取舍：OTTO 明确要求凭证显示在面板里（面板本身只听 127.0.0.1 或局域网，靠 SSH 隧道连服务器）。**扫码页的 token 等价于「能看、能点 QQ 桌面」**，所以 `qrpage.py` 默认 `QRPAGE_BIND=127.0.0.1`，不直接暴露到公网。

## 三、手机扫码页

### 为什么不是改安全组
服务器（阿里云）只对公网开放 22，6185/6081/5099/8663 全部不可达（`Test-NetConnection` 全 False），本地 `ufw` inactive、iptables 全 ACCEPT ⇒ 拦在云安全组。开一个公网端口等于把「能操作 QQ 桌面」的入口暴露出去，不值得。

**采用 PC 面板中转**：手机与 PC 同 WiFi → 访问 `http://<PC局域网IP>:8642/scan` → 面板通过已建立的 SSH 通道向服务器取图/发点击。

```
手机浏览器 ──HTTP──> PC 面板 :8642 /scan ──SSH──> 服务器 qrpage :8663 ──docker exec──> snowluma(xwd/xdotool)
```

面板为此新增 `/scan`、`/scan/shot`、`/scan/tap`、`/scan/refresh`、`/scan/unmap` 五个路由，`main()` 默认绑 `MIRUKU_PANEL_BIND`（`panel-start.ps1` 里设为 `0.0.0.0`）。

### server/qrpage.py
独立 systemd 服务 `miruku-qrpage`，绑 `127.0.0.1:8663`，token 持久化在 `/opt/miruku/logs/qrpage-token`（`os.urandom(16).hex()`，chmod 600），除 `/healthz` 外全部校验 `?t=TOKEN`。

**XWD → PNG 全自己写**：容器里只有 `xwd`，没有 `convert`/PIL/ImageMagick，宿主也没有。XWD v7 头字段（大端，100 字节）：

| 偏移 | 字段 | 偏移 | 字段 |
|---|---|---|---|
| 0 | header_size | 48 | bytes_per_line |
| 4 | file_version（必须 7） | 52 | visual_class |
| 8 | pixmap_format（2=ZPixmap） | 56/60/64 | rgb masks |
| 12 | pixmap_depth | 68 | bits_per_rgb |
| 16 | pixmap_width | 72 | colormap_entries |
| 20 | pixmap_height | 76 | **ncolors** |
| 24 | xoffset | 80/84 | window_width/height |
| 28 | byte_order | 88/92 | window_x/y |
| 32 | bitmap_unit | 96 | bdrwidth |
| 36 | bitmap_bit_order | 44 | **bits_per_pixel** |
| 40 | bitmap_pad | | |

像素起点 `pix_off = header_size + ncolors*12`。**坑**：X 报 `bits_per_pixel=24` 但 `bytes_per_line/width = 4`（BGRX 补齐），所以按 `per_px = bpl // width` 判断，再交换通道转 RGB。PNG 每行前置 filter byte `\x00`，IDAT 用 `zlib.compress(level=6)`，每 chunk 附 `zlib.crc32(tag+data)`。

**坐标校准（关键实测）**：`xdotool getwindowgeometry` 报的 `Position` 与 xwd 截图坐标**横坐标固定差 240px**、纵坐标一致。验证方式：`xdotool windowmove` 移动该窗口后用截图 diff 确认窗口没动（偏移稳定）、再在假设坐标点击确认会话项高亮。可用 `QRPAGE_TAP_OFFSET_X` 覆盖。

**裁剪**：默认裁到 QQ 窗口（登录态优先选 320x460 的登录窗，已登录时退回面积最大的主窗口），手机上看码更大；`?full=1` 给整屏 1920x1080。裁剪偏移通过响应头 `X-Crop-X`/`X-Crop-Y` 回传，前端点击时补回。

**接口**：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/` | 移动端页面（粘性按钮 + 4 秒自动刷新 + 点击红点） |
| GET | `/shot?full=0/1` | PNG + `X-Crop-X/Y` |
| POST | `/tap?x=&y=` | 在截图坐标点一下（内部补 240 偏移） |
| POST | `/refresh` | 推算登录窗「刷新」按钮并点击 |
| POST | `/unmap` | 把托盘里的 QQ 窗口 map 回来 |
| GET | `/healthz` | 免鉴权健康检查 |

### server/qr-proxy-helper.sh
面板要用 `ssh` 拿二进制 + 响应头，而 `ssh` 只回 stdout。这个 helper 输出**固定 40 字节 ASCII 头**（`CROP <x> <y> HTTP <code>` 右补空格）+ 原始 PNG，面板按 40 字节切开。`QR_FULL=1` 环境变量切整屏。

### 实测
| 项 | 结果 |
|---|---|
| `systemctl is-active miruku-qrpage` | active |
| 监听 | `127.0.0.1:8663` |
| `/scan` | 200，3279 字节 |
| `/scan/shot` | 200，22774 字节，`X-Crop 560,300`，320x460 登录窗 |
| `/scan/shot?full=1` | 200，73204 字节，1920x1080 |
| 无 token 访问 | 403 |
| 局域网 `http://192.168.1.10:8642/scan` | 200 |

## 四、遗留

1. `REFRESH_BTN = (150, 400)` 是按窗口尺寸推算的「刷新」按钮相对位置，**还没在真实掉线场景下验证过**（当前 QQ 在线，登录窗不存在）。掉线时应先点「唤出窗口」→ 截图确认按钮位置 → 必要时用 `QRPAGE_*` 或改常量。
2. 面板绑 `0.0.0.0` 意味着同一局域网内任何设备都能打开面板首页（含凭证卡片）。家庭 WiFi 可接受；如果在公共网络用，应改回 `127.0.0.1` 只走隧道。
3. 扫码页目前无 HTTPS（局域网 HTTP）。token 在 URL 里，会留在手机浏览器历史。
4. 点「刷新」之外的操作（关闭安全提醒弹窗）仍需人工在画面上点，没做自动识别。
