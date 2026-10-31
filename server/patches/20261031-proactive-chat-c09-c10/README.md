# proactive_chat C-09/C-10/C-23/C-24/C-25 补丁（2026-10-30 ~ 10-31）

> 这些文件是**线上实际运行版本**，从容器 `/AstrBot/data/plugins/astrbot_plugin_proactive_chat/`
> 用 `docker exec tar` 导出后原样入仓，用于追溯与重建。
> **不是可直接覆盖的仓库源码**——插件本体在上游，本目录只保存我们改过的 5 个文件。

## 背景

Codex 终验（`docs/codex-acceptance-20261030.md`）判 C-09/C-10/C-16 暂不销账，派回三个缺陷：
C-23（出站清洗空结果保留内部标记）、C-24（C-10 重排未持久化）、C-25（TTS 已发但装饰停止被记 0 段）。
修复涉 2 个插件共 7 个文件，proactive_chat 侧 5 个：

| 文件 | 关联缺陷 |
|---|---|
| `core/services/sender_service.py` | C-09（DeliveryOutcome/四级判定）、C-25（voice_sent partial） |
| `core/features/deliver/split_delivery.py` | C-09（partial 走 CONTINUE 而非 abort） |
| `core/features/record/history_writer.py` | C-09（把 delivery 传给 finalize_and_reschedule） |
| `core/pipeline/flow_orchestrator.py` | C-09（session_payload 落 delivery 字段） |
| `core/services/scheduler_service.py` | C-10（停摆标记/重新上膛）、C-24（重排后持久化） |

另两个文件在 `astrbot_plugin_miruku_outbound/`（C-23 三态 guard3 + 双钩子阻断），该插件本就是自有仓库代码，无需另存补丁。

## 关键改动锚点（线上行号）

### sender_service.py
- `class DeliveryOutcome`（dataclass）：`status` ∈ {`skipped`,`attempted`,`partial`,`all_segments_accepted`}、`segment_count_planned`、`segment_count_sent`、`segment_index_failed`、`voice_sent`
- `send_proactive_message()` 返回 `DeliveryOutcome`（原来是 bool）：配置缺失/装饰拦截 → `skipped`；逐段计数；**段 0 成功即 `_record_story_state(text)`**；`segment_count_planned = len(send_chain) + tts_attempted`
- `:562 if not should_send:` ← **C-25 修复点**：`is_tts_sent` 为真时返回
  `DeliveryOutcome(status="partial", segment_count_planned=2, segment_count_sent=1, segment_index_failed=[1], voice_sent=True)`，
  否则 `skipped`
- 新增 `_record_story_state()`：写 `<data_dir>/proactive/story_state.json`（tmp + `os.replace` 原子写），字段 `last_story_sent_at_utc` / `story_id=f"story-{YYYYMMDD}-{sha8}"` / `continue_used=False` / `last_story_sha256`

### split_delivery.py（`DeliverStage.handle`）
- `outcome.status in (partial, all_segments_accepted)` → `extra["delivery_outcome"] = outcome` + **CONTINUE**（partial 打 warning 带段数）
- 否则 `ctx.abort("send_failed")` + RESCHEDULE
- **这是唯一调用 `send_proactive_message` 的地方**（grep 确认），不同步改会把所有主动消息判成失败

### history_writer.py（`RecordStage`）
- `finalize_and_reschedule(..., delivery=extra.get("delivery_outcome"))`

### flow_orchestrator.py（`finalize_and_reschedule`）
- 签名加 `delivery=None`；私聊分支 `session_payload` 顶层写 `status` / `segment_count_sent` / `segment_count_planned` / `segment_index_failed`（list 复制）/ `voice_sent`（dict 与 attr 两态，None 跳过）

### scheduler_service.py
- 新增 `_mark_stall_state()`：写 `<data_dir>/stall_state.json`
  `{"sessions": {sid: {session_key, reason:"persisted_task_expired", stalled_at, expired_next_trigger, unanswered_count, auto_trigger_enabled, recover_when:"next_peer_message"}}}`，
  幂等合并、tmp+replace、函数内 import json/Path/timezone、失败只 warning
- `init_jobs_from_data()` 过期分支改造：`auto_enabled` 为真 → `compute_next_trigger()` + `add_chat_job()` + **`data_lock` 内回写 `next_trigger_time`/`last_scheduled_at`/`last_schedule_{min,max,random_interval}_seconds` + `save_data()`**（C-24，:604-624）；为假 → `_mark_stall_state()` + warning「主动消息链路已停摆」

## 验证

- `data/probe_c09_c10.py`（容器内 `/tmp/mmprobe2` 隔离副本）**26/26 全绿**；`C10-06B`（二次重启持久化）与 `C09-07B`（TTS+装饰停止）为 C-24/C-25 专项补测
- `data/probe_outbound_tristate.py` **39/39**
- 线上部署后重启日志：`已成功从文件恢复任务喵: 私聊 10000001, 执行时间: 2026-10-31 08:30:14`
- 详细修复记录见 `docs/defect-register.md` C-23/C-24/C-25 三节

## 部署方式

```bash
# 备份
docker exec -i astrbot tar -cf /tmp/pc-bk.tar -C /AstrBot/data/plugins astrbot_plugin_proactive_chat
docker cp astrbot:/tmp/pc-bk.tar /opt/miruku/backups/pc-$(date +%Y%m%d-%H%M%S).tar
# 覆盖（路径按上面的相对结构拼到 /AstrBot/data/plugins/astrbot_plugin_proactive_chat/）
docker cp <file> astrbot:/AstrBot/data/plugins/astrbot_plugin_proactive_chat/<rel>
# 语法校验 + 重启
docker exec -i astrbot sh -c 'cd /AstrBot/data/plugins/astrbot_plugin_proactive_chat && python3 -m py_compile core/services/sender_service.py core/services/scheduler_service.py core/features/deliver/split_delivery.py core/features/record/history_writer.py core/pipeline/flow_orchestrator.py'
docker restart astrbot
```

## 坑

- `docker exec` 必须带 `-i`，否则 heredoc 被静默丢弃
- PowerShell 上传的 .sh 带 BOM，ssh 端报 `#!/bin/bash: No such file or directory`（不影响执行）
- `probe_c09_c10.py` 本地跑不了（PEP 604 `dict | None`，本地 Python 3.9），只能容器内跑
