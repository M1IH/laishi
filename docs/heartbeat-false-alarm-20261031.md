# 心跳告警误报修复：日志法被僵尸进程污染（2026-10-31）

## 现象

心跳全天报 `QQ_OFFLINE`，微信推送反复触发，但机器人实际完全正常：

- `2026-10-31 23:49:33 status=QQ_OFFLINE ... qq_login=awaiting`（每 5 分钟一条，当天共 460 条 `QQ_OFFLINE`）
- 同期 QQ 侧实测在线：`get_status` 返回 `{"online":true,"good":true,"time":38820}`、`get_login_info` 返回 `{"user_id":10000004,"nickname":"miruku"}`
- SnowLuma 日志 17:39:36 仍在正常发图（`私聊 10000001 | 发送：[图片]`，`Highway.Image uploading 73932 bytes`）

## 根因

`heartbeat.sh` v3 用日志法判定 QQ 登录态：

```bash
last_login=$(ls -1 "$SNOW_LOGDIR"/snowluma-*.log 2>/dev/null | sort | tail -7 \
  | xargs -r grep -hE 'login detected|awaiting login' 2>/dev/null | tail -1)
```

`tail -1` 取「最后一条事件即当前状态」——这个假设被下面这组日志击穿：

```
13:03:01 OK   [Hook] login detected: PID=25627   UIN=10000004   <- 主进程真的登录了
13:03:01 INFO [Hook] awaiting login: PID=13666                   <- 2 天前的 --relaunch 残留进程
```

两个进程在同一秒各打一条，`tail -1` 稳定取到后者，于是 `login_state=awaiting` 永久固化。污染源 `PID=13666` 的命令行是 `/opt/QQ/qq --relaunch ...`，`ELAPSED 2-06:58:05`，从 10-29 一直挂在容器里；它的 `pipe connected` 是断的（`Client private-message reporting is unavailable: status=-1`），但 `awaiting login` 那行照样打。

辅助证据：`login detected` 在整个日志历史里只出现 3 次（10-29 13:40、10-29 16:51、10-31 13:03），「登录那一刻打一次」的语义本身也让日志法天生脆弱——v3 加「近 7 个文件」只解决了跨天，没解决同秒多进程。

## 修复

改成**优先问 SnowLuma 自己的 OneBot HTTP 接口**，日志法降级为兜底（v4）：

```bash
SNOW_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' snowluma 2>/dev/null)
api_st=$(curl -s -m 6 -X POST "http://$SNOW_IP:3000/get_status" \
  -H "Authorization: Bearer $api_token" -H "Content-Type: application/json" -d '{}')
case "$api_st" in
  *'"online":true'*)  api_online=true ;;
  *'"online":false'*) api_online=false ;;
esac
```

- `online:true` 且 `get_login_info` 有 `user_id` → `qq_online=true; login_state=online-api`
- `online:false` → `awaiting`
- 接口不可达（容器没起、token 读不到、curl 超时）→ 落回原日志法，保持 v3 的「近 7 个文件 + 15 分钟活动升级」

token 取 `/var/lib/docker/volumes/qq-gateway-data/_data/config/onebot.json` 的 `networks.httpServers[0].accessToken`（全局配置，43 字符，与 HTTP API 一致；账号级 `onebot_<uin>.json` 的 token 只给 WS 反连用，用了会 401——这个坑在 D4-⑦ 里踩过）。

## 验证

- `bash -n` 通过；备份 `/opt/miruku/backups/heartbeat.sh.bak.20261031-235145`
- 干跑（`LOG` 重定向到 `/tmp/hb-dry.log`）→ `status=OK ... qq_login=online-api` + `wechat: back online, sent-flag cleared`
- 正式安装后立刻跑一轮 → `2026-10-31 23:51:47 status=OK up=true/true dash=401 ws6199=1 qq_login=online-api`
- 清掉误报期间留下的 `needs-rescan` 标记（时间戳 23:49:33，属误报产物）
- 线上与仓库 `md5 72883e0d0c48ee0ded203963ac025fc4` 一致

## 教训

1. **登录态不能用「最后一条日志」推断**——同一秒多进程、僵尸 relaunch 进程都会破坏这个假设。有权威接口就直接问接口。
2. `--relaunch` 残留进程会一直挂在容器里（本例 2 天 7 小时），且它打的日志和主进程一模一样，肉眼难以区分。排查掉线类问题时应先 `ps` 看有几个 QQ 进程。
3. 告警误报的代价是「真掉线时不再被相信」。这次一天 460 条误报，正好发生在微信告警试运行期间。

## 遗留

- 僵尸进程 `PID=13666`（`/opt/QQ/qq --relaunch`）仍在容器里，不影响功能但会持续打误导性日志。清理需要 `supervisorctl` 层面确认它是否被托管，暂不动。
- SnowLuma 的 `awaiting login` 是否应该排除 `--relaunch` 子进程，属于上游行为，未提 issue。
