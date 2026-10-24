# -*- coding: utf-8 -*-
"""知识源文件体检：隐私与「会让 Miruku 说错话」的写法。

build_knowledge_db.py 只管结构（slug/summary 长度）。这里管内容。

分级依据：`knowledge/inject.py` 运行时只把 **title + summary** 拼进 prompt，
`detail` / `source` 不进（除非有人用 `--full` 手工喂）。所以：
  ⚠ 严重：title/summary 里出现内部路径、账号、系统实现词——会被模型直接看到
  · 提示：detail/source 里有——只在人工查阅时可见，留意即可

用法：
    python knowledge/lint.py
    python knowledge/lint.py --strict   # 有严重警告就返回 1

只读，不改文件。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

INJECTED = ("title", "summary")
REFERENCE = ("detail", "source")

# 出现即警告：这些词进 prompt 后模型可能复述
FORBIDDEN = [
    (re.compile(r"prompts/[\w.]+"), "项目内部提示词路径"),
    (re.compile(r"persona/[\w.]+"), "项目内部人设路径"),
    (re.compile(r"个性化语言/"), "项目内部素材路径"),
    (re.compile(r"data/[\w.]+\.(?:db|sqlite3|json)"), "项目内部数据路径"),
    (re.compile(r"\b\d{6,12}\b"), "疑似 QQ 号/账号数字"),
    (re.compile(r"Shiina\s*Taki", re.I), "真实账号昵称"),
    (re.compile(r"jwt|api[_ ]?key|secret|token", re.I), "密钥类词"),
    (re.compile(r"AstrBot|NapCat|OneBot|插件|部署|提示词|模型权重", re.I), "系统实现词"),
]

URL_RE = re.compile(r"https?://\S+")

# 这些条目里出现「提示词」「部署」是在教 Miruku 别聊这些，属于正当用法
WHITELIST = {
    ("self", "otto-guan-xi"),
    ("self", "bei-wen-zai-na"),
    ("self", "shuo-hua"),
    ("self", "ai-shen-fen"),
}


def scan_text(text: str, skip_numbers: bool = False):
    """返回 (原因, 命中片段) 列表。"""
    text = text or ""
    hits = []
    for pat, why in FORBIDDEN:
        target = URL_RE.sub(" ", text) if skip_numbers and why.startswith("疑似 QQ") else text
        for m in pat.finditer(target):
            hits.append((why, m.group(0)))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="有严重警告就返回 1")
    ap.add_argument("--verbose", action="store_true", help="连提示项一起列")
    args = ap.parse_args()

    severe = 0
    minor = 0
    total = 0
    for path in sorted(SRC.glob("*.json")):
        data = json.load(io.open(path, encoding="utf-8"))
        topic = data.get("topic", path.stem)
        for e in data.get("entries", []):
            total += 1
            slug = e.get("slug", "?")
            for field in INJECTED:
                for why, hit in scan_text(e.get(field, "")):
                    severe += 1
                    print("⚠ [%s/%s] %s 里出现%s：%s（会被注入 prompt）"
                          % (topic, slug, field, why, hit))
            for field in REFERENCE:
                for why, hit in scan_text(e.get(field, ""), skip_numbers=True):
                    minor += 1
                    if (topic, slug) in WHITELIST:
                        continue
                    if args.verbose:
                        print("· [%s/%s] %s 里出现%s：%s（不进 prompt）"
                              % (topic, slug, field, why, hit))
            if len(e.get("summary", "")) > 60:
                severe += 1
                print("⚠ [%s/%s] summary 超 60 字（%d）"
                      % (topic, slug, len(e["summary"])))

    print("\n扫描 %d 条：严重 %d 处，提示 %d 处" % (total, severe, minor))
    if severe == 0:
        print("OK：注入路径（title/summary）干净。")
    return 1 if (args.strict and severe) else 0


if __name__ == "__main__":
    raise SystemExit(main())
