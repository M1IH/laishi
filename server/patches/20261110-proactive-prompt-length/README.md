# 20261110 主动消息提示词长度约束回补

## 为什么

`astrbot_plugin_proactive_chat_config.json` 里 `friend_settings.proactive_prompt`
在 **2026-10-28 15:23** 被换成了一版 276 字的，把所有长度约束删掉了。

实测对照（按实际发出的消息计）：

| 版本 | 样本 | 中位 | ≤10 字占比 | p90 |
|---|---|---|---|---|
| 旧提示词（454 字）+ v1 人格 | 13 | **7** | **92.3%** | 8 |
| 新提示词（276 字）+ v1 人格 | 112 | 11 | 36.6% | 25 |
| 新提示词（276 字）+ v2 人格 | 34 | **17** | **5.9%** | 22 |

也就是说，普通回复在 v2 之后已经缩到中位 9 字，**只有主动消息反而越写越长**。
四份配置副本（当前 + 三个 `.bak`）的 `friend_len` 全是 276，说明这次改动没留备份，
不是回滚造成的。

## 改了什么

不是整段回滚到 454 字旧版，只在现有 276 字基础上补回四段，保持其余措辞不动，
从 276 字变成 **432 字**：

1. **长度**：「只发一条短消息，通常十个字上下，最多二十来字；能一句话说完就不要再补。不要为了显得热情而展开。最多一个问题，多数时候不用问。」
2. **主语与称呼**：「默认省略主语，不要把「Miruku」当默认主语；称呼对方时用「来世」。」
3. **故事护栏**：在原有「只是语感示例」后追加「不要把角色世界的故事说成现实亲历，对方低落、严肃或危机时不用故事转移话题。」
4. **防重复**：「不要照抄，也不要每次都用同一个开头。」

`group_settings.proactive_prompt`（333 字，群聊破冰那套）**未动**。

## 怎么部署

```bash
scp .tmp-tone/patch_prompt_len.py root@<server>:/tmp/
ssh root@<server> "docker cp /tmp/patch_prompt_len.py astrbot:/tmp/ && \
                   docker exec astrbot python3 /tmp/patch_prompt_len.py"          # 先 dry run 看全文
ssh root@<server> "docker exec astrbot python3 /tmp/patch_prompt_len.py --write"
```

脚本行为：

- 读配置用 `encoding="utf-8-sig"`（**该文件有 BOM，直接 utf-8 会报 `Unexpected UTF-8 BOM`**）。
- 只认「当前 276 字版本」或「已打过补丁的 432 字版本」，其余一律 `exit 2` 拒绝改写，防止覆盖别人的改动。
- 写入前备份成 `*.bak.promptlen-<时间戳>`。
- 写回保留 BOM，`json.dumps(ensure_ascii=False, indent=2)`，写后重新加载校验逐字相等。

## 验证

```bash
ssh root@<server> "docker exec astrbot python3 /tmp/dump_prompt.py"
```

`dump_prompt.py` 会打印 `friend_settings` 与 `group_settings` 两段原文 + repr。
预期 `friend_settings` 为 432 字，且包含「只发一条短消息」「最多二十来字」
「不要把「Miruku」当默认主语」「称呼对方时用「来世」」四条。

**配置改动不需要重启**：`proactive_chat` 每次生成提示词时读配置文件。
次日 08:30 主动消息发出后，可用 `probe_3way.py` 的三分类口径复测长度。

## 坑

- `docker exec astrbot python3 -c "..."` 从 PowerShell 调会被引号拆参数 → 一律写 `.py` 文件再 `docker cp` 进去跑。
- 外层单引号 `'...'` 里的 `$P`、`$n` 会被本地 PowerShell 先吞掉 → 路径要写死，或整个改双引号。
- 该配置文件若被 AstrBot 在运行期回写（插件保存 settings），补丁会被覆盖 → 改完第二天复查一次 `len == 432`。
