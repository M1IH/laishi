# 阿里云服务器部署方案（Miruku）2026-10-26

> 制定：DeepSeek　依据 OTTO 六项拍板：①密钥走部署公钥 ②本机停机+备份 ③主动消息只对测试号
> ④桌面与 noVNC 都装 ⑤知情接受来世数据与 DeepSeek key 上云 ⑥EmotionAI 等 C-21 修好再搬
> ⑧C-10 与心跳由我实现 ⑨`max_unanswered_times` 保持 0（不限制）

## 一、目标与边界

- 服务器：`203.0.113.10`，Ubuntu 22.04（SSH banner 实测 `OpenSSH_8.9p1 Ubuntu-3ubuntu0.18`），22 端口开放。
- **只跑被动回复 + 对测试号的主动消息**；来世（352***294）暂不投放，等 D4 自愈七项在本机/云端各自过完再切。
- 全部服务端口只绑 `127.0.0.1`，访问一律走 SSH 隧道（`ssh -L`），**不向公网开放任何面板端口**。
- 3389/RDP 不存在也不装（Linux 机器，远程桌面不是这个栈的形态）；扫码通道是 **NapCat WebUI 的二维码页**，noVNC 只作运维兜底（Linux 无头栈里 QQ 没有窗口）。

## 二、拓扑（复刻本机形态，而非照抄官方模板）

```
┌ Ubuntu 22.04 (203.0.113.10)
│  docker bridge 网络 miruku
│   ├ astrbot   :6199(AstrBot 平台服务)  :6185(dashboard)
│   └ napcat    :6099(WebUI)             ← reverse_ws 主动外连 ws://astrbot:6199/ws
│  xvfb + x11vnc + novnc（桌面兜底）
│  systemd: docker 自启 + 容器 Restart=always + 心跳/自愈探针
```

本机是 NapCat 作 WS 客户端连 AstrBot（`onebot11_*.json` 实测 `websocketClient → ws://127.0.0.1:6199/ws`），
服务端用 `MODE=reverse_ws` + `ONEBOT_URL=ws://astrbot:6199/ws` 保持一致，6199 不出容器。

## 三、镜像

| 用途 | 镜像 | 说明 |
| --- | --- | --- |
| 协议端 | `mlikiowa/napcat-docker:latest` | 官方 NapCat-Docker README 实测可用字段：`MODE`/`WEBUI_TOKEN`/`ONEBOT_URL`；数据目录三个：`/app/.config/QQ`、`/app/napcat/config`、`/app/napcat/plugins` |
| 框架端 | 优先 `soulter/astrbot`（官方 compose 用这个），拉不到则退回上游 `astrbotastral/astrbot` | 版本号以服务端 `docker inspect` 为准，**与本机对齐后再搬 data** |

**版本必须核对**：本机 AstrBot 是 v4.29.1。搬 `data/` 跨版本有格式风险，落 data 前先看服务端镜像的 AstrBot 版本，不一致就选同版本 tag，或按迁移校验清单逐项核（personas/provider 配置/插件加载）。

## 四、搬什么（白名单式，宁少不多）

从本机实例 `.../core/data/` 搬：

- `cmd_config.json`（DeepSeek provider、模型、人格选择、分段回复开关）
- `data_v4.db`（含来世私聊历史——AstrBot 会话库，主动消息上下文要用）
- `config/astrbot_plugin_proactive_chat_config.json`（11:39 验过的「在干嘛呢」开场文案 + 排期/静默时段）
- `config/` 里 miruku_knowledge / miruku_context_guard / miruku_observer 三个自研插件的配置
- 三个自研插件本体 + `astrbot_plugin_proactive_chat`：`data/plugins/<上述四项>`
- 项目侧知识源：仓库里的 `knowledge/src`、`prompts/system.txt`、`persona/`（服务端重建知识库，Windows 绝对路径不进容器）

**不搬**：`emotionai`（⑦，C-21 污染源）、`livingmemory`（本机本就因缺 Embedding 初始化失败，白占内存）、`soulmap`/`qzone`/`anysearch`/`self_iterative_core`/`meme_manager`/`group_chat_plus`/`reply_directly`/`humanlike`（首版保持最小集，验证稳定后按需再加）、`dist`/`temp`/`_base_only_tmp*`（构建产物与临时库）。

DeepSeek API key 只经 SSH 管道进入服务端配置文件：不回显、不落中间明文文件、不写日志。

## 五、按 OTTO 决定要落地的两件事（原属 Codex 前置，Codex 无额度，本单承接）

### C-10：重启后主动消息自动重排
现象（本机 17:53 实测日志）：`私聊 10000002 的持久化任务已过期或无效，清理后跳过恢复` → `共恢复 0 个` → 只剩 `auto_trigger` 计时器兜着；一旦这 120 分钟窗口内没触发，她就不再主动说话。
做法（**不改 AstrBot core**，只在插件配置层）：开机恢复阶段显式走 `enable_auto_trigger=true`（当前本机是 `false`，见 MEMORY 的 WB-08 记录）+ `auto_trigger_after_minutes=120`，并用 systemd 在容器重启后跑一次 `/api/jobs/{umo}/trigger` 之外**不**发（避免开机就轰炸），只验证排期存在；缺任务则由插件自身的持久化恢复+自动触发器重建。验收＝「杀进程→自愈→`GET /api/jobs` 里该会话仍有 next_run」，即 D4 前置 2 的行为口径。

### 心跳（D4 第 4 条：≤10 分钟一行「进程在＋适配器在线」）
新增 `server/heartbeat.sh`（容器内 host 侧 systemd timer，每 5 分钟）：
①`docker inspect` 两容器 running；②AstrBot dashboard 可访问；③6199 有 ESTABLISHED（NapCat 已连）；④`GET /api/jobs` 返回的 next_run 未过期。
四行结果写 `/var/log/miruku-heartbeat.log`，任一项失败追加 `ALERT` 行并 `docker compose restart` 对应容器（自愈动作）。
这条同时把 `data/probe_uptime.py` 的 `HEARTBEAT_MARKS=()` 补成真实标记，让探针有机会判 `PROVEN`。

## 六、执行顺序（跑到第 7 步停下等你扫码）

1. 装 Docker（Ubuntu 22.04 官方 apt 源 or 阿里云镜像源，国内直连 Docker Hub 可能超时 → 配 registry mirror）。
2. 建 `/opt/miruku` + compose，两容器起（NapCat 先不连、AstrBot 先空配置）。
3. 搬 data/plugins（`tar` 经 SSH 管道，白名单见 §四）；`chown` 对齐 `NAPCAT_UID/GID`。
4. 服务端跑 `build_knowledge_db.py` 重建知识库；核对知识插件 `db_path` 与 `target_qq`（**测试号**）。
5. 核对 AstrBot 版本与人格加载；主动消息收件人设为 **测试号 10000001**，`max_unanswered_times=0`（⑨保持不限制，但只对测试号生效）。
6. 装 Xvfb+x11vnc+novnc；写心跳与 C-10 的 systemd 单元；全部端口绑 127.0.0.1。
7. **停**：给 NapCat WebUI 隧道地址 → 你在浏览器里看到二维码 → 手机 QQ 扫码 → 告诉我。
8. 我收尾：适配器已连接 / 6199 ESTABLISHED / 对测试号手动触发一条主动消息冒烟 / 心跳日志正常。
9. **本机停机**（②）：备份带时间戳 → 停 NapCat → 停 AstrBot → 确认 6199 无 LISTEN。
   注意顺序：**第 7 步扫码会把本机会话踢掉**，所以备份要先于扫码做。

## 七、已知风险（都记着，出事先对照）

- 机房 IP 的 NTQQ 风控严度高于住宅 IP；掉线需人工重扫（这是④装桌面/noVNC 的理由）。
- 机器人号天生不进 `login.enc` 快速登录名单（[qr-login-rootcause](qr-login-rootcause-20261026.md)）：服务器独占 profile 后是否写入，**第 7 步扫码后第一件事就是验这个**，结论决定「偶发重扫」还是「彻底免扫」。
- 2G 内存跑 Linux QQ NT + AstrBot 属临界；不够我会加 swap 并停下报告，不硬跑。
- `data/*` 在 `.gitignore` 内，本次搬运走 SSH，不 push、不触发清号闸。
- 本方案不改仓库代码，不动 `WORK_LOG` 历史条目；完工按精简准则追加一条。
