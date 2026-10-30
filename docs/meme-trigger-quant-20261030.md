# 表情包触发率量化实测（2026-10-30）

## 结论先行

线上 `probability=75` 配置下，真实带图率 **62.4%（72h 全量）**，10-30 当天 **69.5%**。
漏斗瓶颈 **100% 在概率骰**：情感模型一旦被调用，选图率 **97.6%**。

**用户结论（2026-10-30 21:38）：表情包现状「挺好的，不用再修复了」——本条止于记录，不再调参。**

## 漏斗拆解（72h，`docker logs astrbot --since 72h`）

| 环节 | 次数 | 占比 |
|---|---|---|
| 判定总数（有回复即判一次） | 133 | 100% |
| 骰子未命中，**压根没调情感模型** | 48 | **36.1%** |
| 骰子命中 → 模型选了标签 | 83 | 62.4% |
| 骰子命中 → 模型没选 | 2 | 1.5% |

- 骰子命中率实测 63.9%（配置 75%，因为 10-27～10-29 期间配置是 45，拉低了均值）
- **模型在命中时的选图率 97.6%**（85 次里 83 次选中）
- 最终带图率 62.4%

按天看（配置在这几天改过，能对上）：

| 日期 | 判定 | 骰子命中率 | 带图率 |
|---|---|---|---|
| 10-27 | 5 | 40.0% | 40.0% |
| 10-28 | 45 | 53.3% | 53.3% |
| 10-29 | 24 | 66.7% | 66.7% |
| 10-30 | 59 | 72.9% | **69.5%** |

10-30 已配 75，实测命中 72.9%，与配置吻合，**逻辑正常**。

## 根因（代码实证）

`/AstrBot/data/plugins/meme_manager/mixins/event_handlers.py:1353-1355`：

```python
legacy_probability_hit = probability_hit(self.emotions_probability)
event.set_extra("meme_manager_legacy_probability_hit", legacy_probability_hit)
if self.emotion_llm_enabled and legacy_probability_hit:   # ← 骰子不中就不调模型
```

骰子不中时直接走到 `:1403` 打 `去重后的最终表情列表: []`，**连日志都不会有「情感模型选择标签」那行**。

因此日志模式可直接判读：
- 有「情感模型选择标签」行 → 骰子命中
- 只有「最终表情列表」行 → 骰子未命中

`utils.py:55 probability_hit(value)`：`<=0` False、`>=100` True、否则 `randint(1,100) <= value`。

## 没有 p²（已核实）

`event_handlers.py` 有三处读 `emotions_probability`，但：

- `:1353` `_resp_impl` —— 首次掷骰，结果存进 `event.set_extra("meme_manager_legacy_probability_hit")`
- `:1570-1575` `on_decorating_result` 发送阶段 —— **先读 extra，只有 None 才回退掷骰**
- `:1757-1762` `_after_message_sent_impl` 补发阶段 —— 同样先读 extra

只有 `_build_emotion_images_for_event:630`（`compat_prepare_message` 兼容接口）会独立掷骰，**不在 legacy 路径上**。所以没有 p²，一次判定只有一次骰。

## 反推（未采用，仅存档）

| probability | 预估带图率 |
|---|---|
| 100 | ~98% |
| 90 | ~88% |
| 85 | ~83% |
| 75（当前） | ~73% |

## 已排除的干扰项

- 10-29 的 10 次「平台发送失败」全是 NapCat 时期 `ActionFailed retcode=1200`（`rich media transfer failed` / `网络连接异常!`），QQ 侧图片上传/网络问题，**与表情包逻辑无关**。10-30 全天 19 次成功 0 次失败。
- 包分类齐全：atri-meme-pack 552 张 15 类、juxueli-meme-pack 39 张 9 类。**builtin-default 0 张（空包）仍在启用列表**（无副作用，`_get_category_meme_files` 静默跳过）。

## 体感解释

用户「聊了好多一条也没发」= 骰子逐条独立，25% 缺席会**成簇出现**（如 20:23/20:28/20:30 连续三条 `最终表情列表: []`）。近 45 次判定序列（S=选图 / E=模型空选 / M=骰子未中）：

```
MMSMSMSMEMSMSMSMSMSMSMSMMSMMEMMSMSMSMMSMSMMSM
```

M 的密度与 25% 缺席率一致。

## 遗留可查项（未做，记录备查）

- `semantic.enabled=true` 但 `embedding_provider_id=""` → 语义检索实际未生效；`main.py:515` 每次启动打「juxueli-meme-pack 的图片描述尚未全部完成，暂不自动建立向量」。
- 20:28:41 出现过 `Session ID miruku:FriendMessage:0 is not in the session allowlist`（uin=0 异常会话）。
