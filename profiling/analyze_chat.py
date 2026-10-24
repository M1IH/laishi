"""Summarize a QQChatExporter private chat without copying raw history."""

import collections
import json
import pathlib
import statistics


path = next((pathlib.Path(__file__).parents[1] / "聊天记录").glob("*.json"))
data = json.loads(path.read_text(encoding="utf-8"))
messages = data["messages"]
speakers = {"self": data["chatInfo"]["selfUin"], "peer": data["chatInfo"]["peerUin"]}


def plain(message):
    text = message.get("content", {}).get("text", "").strip()
    if message.get("type") not in ("text", "reply") or not text:
        return ""
    if text.startswith(("[图片:", "[语音", "[视频", "[文件", "[QQ小程序", "[回复消息]")):
        return ""
    if "http" in text or len(text) > 180:
        return ""
    return text


for role, uin in speakers.items():
    own = [m for m in messages if m.get("sender", {}).get("uin") == uin]
    texts = [plain(m) for m in own]
    texts = [t for t in texts if t]
    lengths = [len(t) for t in texts]
    single = [t for t in texts if len(t) <= 35 and "\n" not in t]
    starts = collections.Counter(t for t in single if len(t) <= 12)
    print(role, "messages", len(own), "plain", len(texts), "median_len", statistics.median(lengths))
    print("short<=15", round(sum(len(t) <= 15 for t in texts) / len(texts), 3))
    print("question", round(sum("？" in t or "?" in t for t in texts) / len(texts), 3))
    print("period", round(sum("。" in t for t in texts) / len(texts), 3))
    print("newline", round(sum("\n" in t for t in texts) / len(texts), 3))
    print("top_short", starts.most_common(35))
    print("openers", [(phrase, sum(t.startswith(phrase) for t in texts)) for phrase in ("在干什么", "在干嘛", "在干啥", "人呢", "怎么了", "吃饭", "晚安")])
    print("markers", [(phrase, sum(phrase in t for t in texts)) for phrase in ("啧", "行吧", "神了", "666", "nb", "牛逼", "草", "何意味", "～", "~", "……")])
    print("care_counts", [(phrase, sum(phrase in t for t in texts)) for phrase in ("怎么了", "休息", "吃饭", "难受")])

# Consecutive messages from one speaker are a conversational burst.
bursts = []
for message in messages:
    uin = message.get("sender", {}).get("uin")
    if uin not in speakers.values() or not plain(message):
        continue
    if bursts and bursts[-1][0] == uin:
        bursts[-1][1].append(message)
    else:
        bursts.append((uin, [message]))
for role, uin in speakers.items():
    sizes = [len(items) for sender, items in bursts if sender == uin]
    print(role, "burst_median", statistics.median(sizes), "burst_ge4", round(sum(n >= 4 for n in sizes) / len(sizes), 3))
