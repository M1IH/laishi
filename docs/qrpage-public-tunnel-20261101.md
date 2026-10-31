# 公网扫码入口（电脑关机也能扫码）

日期：2026-11-01
起因：OTTO m08951 ——「可是大部分情况下我电脑是关着的，我在外面上课，然后掉线了，我就扫不了了吗」

## 问题

上一版（`docs/qrpage-and-panel-cred-20261101.md`）的扫码页走 **PC 面板中转**：

```
手机 ──> PC 面板 :8642/scan ──SSH──> 服务器 qrpage:8663
```

PC 一关机，整条链路断掉。而 OTTO 白天大部分时间 PC 是关的、人在外面，掉线就完全没法处理。

## 为什么这条隧道能成立

服务器（阿里云 `203.0.113.10`）对公网只开 22：

- `ufw` inactive、`iptables -P INPUT ACCEPT`（本地不拦）
- `ss -tlnp` 只有 22 + systemd-resolve 53 + 容器内 x11vnc 5900
- 本机测 80/443/8080/8443/8663/6185 全部 False、仅 22 True ⇒ **拦在阿里云安全组**

改安全组需要人工在控制台操作，而且等于把「能操作 QQ 桌面」的端口直接暴露到互联网。

**改用 Cloudflare 快速隧道**：`cloudflared` 从内网主动向 Cloudflare 建立出站连接（QUIC/TCP 443），公网通过 Cloudflare 边缘回源。**不需要开任何入站端口、不需要域名、不需要证书、不需要改安全组**。

```
手机任意网络 ──https──> xxx.trycloudflare.com ──CF边缘──> cloudflared(出站连接) ──> 127.0.0.1:8663 qrpage ──docker exec──> snowluma
```

## 部署物

### 1. cloudflared 二进制

`/opt/miruku/cloudflared`（v2026.10.7，40,274,445 字节）。

**坑**：GitHub releases 在这台机器上超时（`curl: (28) Failed to connect to github.com port 443 after 130732 ms`），`ghproxy.net`/`mirror.ghproxy.com` 也不通；**`gh-proxy.com` 可用**，但速度只有 ~120KB/s，40MB 会因 240s 超时被截断 —— 必须用 `curl -C -` 断点续传 + 循环重试直到文件达到完整大小：

```bash
curl -L -m 300 -C - -o /opt/miruku/cloudflared.new \
  "https://gh-proxy.com/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
# 校验：stat -c %s 必须 >= 40000000，否则继续续传
```

### 2. miruku-qr-tunnel.service

systemd 托管，`Restart=always`，`enable` 开机自启。`ExecStart` 指向 `/opt/miruku/server/qr-tunnel-run.sh`：

```bash
BASE=$(wc -l < "$LOG" 2>/dev/null || echo 0)   # 记住当前日志行数
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8663 &
for i in $(seq 1 60); do
  sleep 2
  U=$(tail -n +$((BASE+1)) "$LOG" | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1)
  [ -n "$U" ] && { printf '%s' "$U" > /opt/miruku/logs/qr-tunnel-url; break; }
done
wait $CF_PID
```

**关键坑**：最初版本是 `grep ... | tail -1` 全文件搜索 —— 日志里还留着**上一次**的旧 URL，重启后抓到旧域名，公网访问直接 530。改成「只从本次启动新写入的行里找」（`tail -n +$((BASE+1))`）才对。首次部署时就踩了这个：日志里同时有 `urban-same-wrapping-accommodate`（旧，530）和 `main-sox-suppliers-numbers`（新，200）。

### 3. URL 变更自动推送（server/qr-url-notify.sh）

快速隧道的域名**每次重启都变**，用户存下来的旧链接会失效。脚本对比 `qr-tunnel-url` 与 `qr-tunnel-url.last-pushed`，不同才推 Server酱，推成功才写 last-pushed（幂等）。

挂进 `heartbeat.sh` 末尾（5 分钟一跑）：

```bash
"$APP/server/qr-url-notify.sh" 2>/dev/null || true
```

**首次部署要先「钉住」当前 URL**，否则第一次跑就推一条：

```bash
cat /opt/miruku/logs/qr-tunnel-url > /opt/miruku/logs/qr-tunnel-url.last-pushed
```

### 4. 告警里带链接（server/heartbeat.sh）

`wechat_push()` 新增 `qr_public_url()`，把 `qr-tunnel-url` + `qrpage-token` 拼成完整可点链接塞进推送正文：

```
QQ 登录态失效，需要重新扫码。

[点这里手机扫码](https://xxx.trycloudflare.com/?t=xxxx)
（电脑关机也能用，手机任意网络）
```

隧道没起时降级为「公网扫码链接暂不可用（隧道未起），请开电脑用面板」，不会推一个坏链接。

### 5. 面板状态栏（panel/panel.py + server/panel-status.py）

`panel-status.py` 的 `cred.qrpage_public` 优先读 `/opt/miruku/logs/qr-tunnel-url`，回退旧的 `/opt/miruku/server/qrpage-base`；面板「扫码登录」卡片最上面新增一行「🌐 公网扫码（电脑关机也能用）」。

## 验证结果

| 项 | 结果 |
|---|---|
| `miruku-qrpage` | active / enabled |
| `miruku-qr-tunnel` | active / enabled |
| `miruku-heartbeat.timer` | active / enabled |
| 公网 `/healthz` | 200 `ok` |
| 公网 `/?t=TOKEN` | 200，3639 字节 HTML |
| 公网 `/shot` | 200，22780 字节 PNG |
| 公网 `/unmap`（POST） | 200，`map 了 9 个窗口` |
| 告警推送 | `{"code":0,...,"pushid":"65229853"}`，正文含可点链接 |
| 隧道重启后自动发现 | `OLD=herald-trail-est-signing` → `NEW=example-qr-tunnel`，`CHANGED` → 自动推送成功 |
| notify 幂等 | 连跑两次，日志只 1 行 |

当前地址（会随隧道重启变化，以面板状态栏 / 微信推送为准）：
`https://example-qr-tunnel.trycloudflare.com/?t=00000000000000000000000000000000`

## 安全说明（必须知道）

这等于把 **QQ 桌面操作入口**放到了公网，防护只有一道 token：

- token 是 `os.urandom(16).hex()`（128 位），只在 URL 里，`/healthz` 之外全部校验
- 无 token 访问返回 403（实测）
- token 会进手机浏览器历史；链接也在微信推送里（Server酱 本身是第三方服务）
- 没有 IP 白名单、没有失败次数限制、没有 HTTPS 客户端证书

**如果要更严**：Cloudflare 有 Access（需要域名 + 邮箱/OTP 验证），或者换成 `cloudflared tunnel run` 命名隧道 + Access。当前快速隧道是「够用且零成本」的取舍，OTTO 要求「在外面能扫」优先。

## 遗留

1. 快速隧道域名每天/每次重启都变，靠微信推送告知。要固定域名需要自己的域名 + Cloudflare 命名隧道（`cloudflared tunnel create` + DNS CNAME），大约多 15 分钟配置。
2. `cloudflared` 二进制是从 `gh-proxy.com` 拉的（GitHub 直连超时），没有校验签名/哈希。版本 v2026.10.7。
3. 服务器内存 1.7G，`cloudflared` 常驻约 40-60MB，实测可用内存仍在 500MB+。
4. `REFRESH_BTN=(150,400)` 仍未在真实掉线场景验证（当前 QQ 在线，登录窗不存在）。
