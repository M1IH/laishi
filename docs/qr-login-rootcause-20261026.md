# 「每次启动都要重新扫码」根因定位

> 排查人：DeepSeek　2026-10-26　触发：OTTO 明确「频繁掉线 = 每次启动都要重新扫码，后期想部署到服务器」
> 边界：**只读排查，未改任何配置、未重启、未碰 NapCat 副本、未发 QQ。**

---

## 一、结论

**这不是「掉线」，是「快速登录凭据压根不归机器人号所有」。**

根因只有一条，而且证据是硬的：

> `C:\Users\OTTO\AppData\Roaming\QQ\auth\login.enc`（NTQQ 记住「下次免扫」的唯一凭据文件）里**只有一条记录**，
> 它属于 **OTTO 的日常号 304****45**（`isQuickLogin: true`），**不是机器人号 376****47**。

再加上你刚确认的「我自己用的 QQ 每天都开着」和 §二 的进程事实，链条就闭合了：

**两个 QQ 共用同一份 `AppData\Roaming\QQ`，而这份 profile 里的快速登录凭据被你日常号占着。机器人号每次启动读到的都是「别人的、或空的」凭据 → 只能扫码。**

---

## 二、证据链（逐条可复核）

### 2.1 login.enc 里只有一个账号，且是你自己的

文件 `AppData\Roaming\QQ\auth\login.enc`，362 字节，最后写入 **2026-10-26 08:33:33**（今天开机时）：

```
顶层: list，元素数 = 1
字段: uin / nickName / faceUrl / facePath / loginType / isQuickLogin / isAutoLogin / isUserLogin
uin  = 304****45   ← OTTO 日常号（不是机器人号 376****47）
loginType   = 1
isQuickLogin = True     ← 「记住了、下次免扫」只对这个号成立
isAutoLogin  = False
isUserLogin  = True
```

**判读**：`isQuickLogin=True` 意味着**你日常那个号**下次可以免扫；这份文件里**没有机器人号的记录**，所以机器人号每次都要重新扫。

### 2.1b NapCat 的快速登录机制（源码级证据）

在 `napcat.mjs`（2.9 MB，NapCat v4.18 内嵌主程序）里找到了完整链路：

```js
// ① 向 QQ 要「本地记住的账号列表」
n.getLoginList().then((a) => {
  const c = a.LocalLoginInfoList.filter((u) => u.isQuickLogin);
  pe.setQQQuickLoginList(c.map((u) => u.uin.toString()));
  pe.setQQNewLoginList(c);
});

// ② 拿到 uin 才能发起快速登录
pe.setQuickLoginCall(async (a) => ... {
  a ? (e.log("正在快速登录 ", a), n.quickLoginWithUin(a) ...
```

**关键点**：`getLoginList()` 拿到的就是 `login.enc` 里那份**账号列表**，`isQuickLogin` 是过滤条件。
列表里没有机器人号 → **`quickLoginWithUin(376****47)` 根本没机会被调用** → NapCat 只能退回去请求二维码。

这解释了为什么「重启就扫码」：不是凭据过期，是**列表里压根没有这个号**。

另外，`login.enc` 的写入方是 **QQ 客户端自己**（NapCat 里搜不到 `login.enc` 这个字符串，它是通过 QQ 内部接口 `getLoginList` 读的）。所以「谁最后运行、最后登录，谁占位」——你日常号每天开着，占位的就是它。

### 2.2 两个 QQ 确实在共用同一份 profile

- `D:\QQ\QQ.exe`（实际跑 9.9.26-44725）→ 8 个子进程，`--user-data-dir` 全是 `C:\Users\OTTO\AppData\Roaming\QQ`
- `NapCatShell-Recovery\QQ.exe`（9.9.33-52230）→ 3 个子进程，**同一路径**

`login.enc` 就在这个目录下。两个不同版本的 QQ 抢写同一个 `login.enc`，谁最后写谁占位 —— 今天 08:33:33 那次写的是你的号。

### 2.3 机器人号自己的数据是活的，只是没凭据

| 账号目录 | 文件数 | 今日日志 |
| --- | --- | --- |
| `Documents\Tencent Files\376****47`（机器人） | 729 | 1 个（08:53，正在写） |
| `Documents\Tencent Files\304****45`（你的） | 93,350 | 2 个（08:53） |

机器人号的数据目录在正常读写 ⇒ **QQ 本身在跑、在收发消息**，问题纯粹在「启动时没有可用的免扫凭据」。

### 2.4 顺便排除「掉线」这个说法

| 日期 | 「适配器已连接」次数 | 判读 |
| --- | --- | --- |
| 10-20 | **8** | 当天 12:15–12:20 连 4 次（间隔 64/145/69 秒）、16:10–17:27 又 4 次 —— 那才是真重连 |
| 10-21～23 | **0** | 根本没连上（同期在排查启动截断 / `QQNT.dll` 崩溃） |
| 10-24～26 | 各 1–2 | 都是 AstrBot 重启后的首次连接 |

**最近三天没有运行中掉线。** 你感受到的「掉线」实际是「重启后要重扫」。

---

## 三、还有个次要因素：心跳/重连参数过于激进

NapCat 的 `onebot11_376****47.json`：

```json
"websocketClients": [{
  "url": "ws://127.0.0.1:6199/ws",
  "heartInterval": 1000,      // 1 秒心跳
  "reconnectInterval": 1000   // 1 秒重连
}]
```

方向是 **NapCat 主动连 AstrBot**。1 秒心跳在本地没问题，但 AstrBot 一旦事件循环卡顿（日志里确实配了 `Event loop watchdog: timeout=30s`），1 秒就超时 → 反复重连 → 日志刷「适配器已连接」。**这不是扫码问题的原因，但会让日志看起来很吓人。**

---

## 四、这对「部署到服务器」意味着什么

**这是最关键的一节。** 你的目标是上服务器，那么：

| 问题 | 现在是 | 上服务器后 |
| --- | --- | --- |
| 免扫码登录 | 凭据被日常号占用 | **同样会遇到**，而且更严重 |
| 两个 QQ 同机 | 共用一份 profile | 服务器上通常只跑机器人号，反而**不会有这个冲突** |
| 扫码本身 | 桌面可见，能扫 | **无头环境要 noVNC/远程桌面**，很麻烦 |

SnowLuma 官方文档对无头环境的答案是 Docker + noVNC（Linux），Windows 手动部署仍需**在桌面 QQ 窗口里扫码**。所以 **SnowLuma 并不能消除「首次扫码」**——它消除的是「每次都扫」的前提是**登录态能持久化**，而这取决于 profile 是否稳定，与换不换框架无关。

---

## 五、三条路，按性价比排序

### 路线 A（推荐，成本最低）：让机器人号自己占住 `login.enc`

**先纠正我自己的一个错误假设**：我曾想「给 NapCat 传 `--user-data-dir` 隔离 profile」，但**这条路走不通**——我扫了 `NapCatWinBootMain.exe`（32 KB）和 `NapCatWinBootHook.dll`（19 KB）的字符串表：

```
--user-data-dir    ascii=0  utf16le=0
userDataDir        ascii=0  utf16le=0
以 `--` 开头的参数串：共 0 个
```

启动器**根本不解析任何命令行参数**，它把 `QQ.exe` 和 `-q <uin>` 直接拼起来调用（`QQ.exe` 与 `-q` 在 DLL 里各出现 1 次 UTF-16）。传 `--user-data-dir` 只会被丢弃。

**所以正确的路线 A 是这样**：

1. 让机器人号在**你的日常号没登录之前**先登录一次（扫码），让它成为 `login.enc` 里的记录；
2. 关键：**两个号不能共用一个 Electron profile 同时跑**。要么
   - **A-1**：机器人 QQ 跑的时候，你的日常 QQ **不登录**（但这和你的使用习惯冲突，不现实）；
   - **A-2**：给机器人 QQ 换一个**独立安装位置 + 独立 profile**——`QQ.exe` 支持 `--user-data-dir`（Electron 标准参数，实测两个实例的子进程都带这个参数），但需要**绕过 NapCat 启动器**直接调 QQ。
3. **最稳的是 A-3**：机器人 QQ 挪到**另一个 Windows 用户**下运行。Windows 用户不同 → `AppData\Roaming\QQ` 天然隔离 → 两份 `login.enc` 互不干扰。这正是你「部署到服务器」的终局形态。

**代价**：A-3 需要重新扫码一次（最后一次），之后机器人号自己的 `login.enc` 由它自己写，你日常号动不到。

### 路线 B（治本，但重）：机器人 QQ 换到独立环境

异机 / 虚拟机 / 服务器上单独跑一套 QQ+NapCat，与本机日常 QQ 完全隔离。这正是你「部署到服务器」的终局形态，只是把它提前。

### 路线 C（换 SnowLuma）：不解决当前问题

SnowLuma 同样依赖 NTQQ 的登录态持久化。**两个 QQ 共用一份 profile 的问题原样存在**，换完照样每次扫码。它的收益只在「有 WebUI / SDK / MCP」这些配套上。

---

## 六、还需要确认的三件事（我无法从文件判断）

1. ~~**`NapCatWinBootMain.exe` 是否接受 `--user-data-dir`**~~ → **已查清：不接受**（字符串表里 0 个参数，启动器把 `QQ.exe -q <uin>` 直接拼出来）。所以必须绕过启动器，或在 Windows 用户层面隔离。
2. **机器人号上一次「免扫成功」是什么时候**——如果从来没有成功过，说明凭据一直没写进去；如果曾经能免扫、后来不行，说明是被你的号挤掉了。**从 `login.enc` 只有一条记录、且是你日常号看，更像后者。**
3. **你的日常 QQ 是否曾在机器人启动之后才登录**——如果是，会覆盖 `login.enc`。**你说「每天都开着」，那基本可以认定：只要你的 QQ 先登录，机器人号就挤不进去。**

---

## 七、本次没做的事

- 没改 `onebot11_*.json`、`napcat*.json` 或任何实例配置
- 没重启 AstrBot / NapCat / QQ
- 没碰 `NapCatShell-Recovery`（`.manual-login-reserved` 仍在）
- 没下载/安装 SnowLuma
- 没发 QQ
- **没验证** §五 路线 A 的可行性（需要查 NapCat 启动器参数，属运行时改动，需你授权）
