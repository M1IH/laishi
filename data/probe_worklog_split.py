#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WORK_LOG 拆分与完整性核对（2026-10-24）

背景：`WORK_LOG.md` 已到 349 KB / 1863 行，开工必读成本过高。按 OTTO 交办的
清单拆成三份，**原文逐字不改**，主文件只留索引与指针：

  1. 缺陷原文 C-01…C-17      → `docs/defect-register.md`
  2. 2026-10-22 及以前的进展 → `docs/archive/WORK_LOG-archive-2026-10.md`
  3. 「当前状态」压到 5 行，被替换的历史摘要同样归档

两种模式：
  --split    执行拆分。归档文件已存在时拒绝（除非 --force）。
  --verify   只读核对（默认）：把块从归档/缺陷表取回来，与备份原件对应区段比
             sha256；再把「原文非空行的多重集合」与「拆分后三个文件的非空行
             多重集合」比对，证明一行未丢。

跑法（必须用 Launcher 实例 venv，见项目约定）：
  PY="C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/venv/Scripts/python.exe"
  "$PY" data/probe_worklog_split.py --split
  "$PY" data/probe_worklog_split.py --verify
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
from collections import Counter

SRC = "WORK_LOG.md"
BAK = "data/backups/WORK_LOG-20261024-before-split.md"
ARCHIVE = "docs/archive/WORK_LOG-archive-2026-10.md"
DEFECTS = "docs/defect-register.md"

MARKS = {
    "status": "## 当前状态",
    "proj": "## 项目是什么",
    "dec": "## 已拍板的决策",
    "defect": "## 待 Codex 修复的缺陷清单",
    "prog": "## 最新进展",
    "todo": "## 当前待办",
}

TAG_PROG = "progress-le-20261022"
TAG_STATUS = "status-history"


def rd(path: str) -> str:
    return io.open(path, encoding="utf-8", newline="").read()


def wr(path: str, text: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def idx_of(lines: list[str], prefix: str) -> int:
    for i, l in enumerate(lines):
        if l.startswith(prefix):
            return i
    raise SystemExit("找不到标题：%r" % prefix)


def beg(tag: str) -> str:
    return "<!-- BLOCK-BEGIN:%s -->\n" % tag


def end(tag: str) -> str:
    return "<!-- BLOCK-END:%s -->\n" % tag


def cut_block(text: str, tag: str) -> str:
    """从归档文件里把一个块原样取回（不含标记行）。"""
    b, e = beg(tag), end(tag)
    i = text.index(b) + len(b)
    j = text.index(e, i)
    return text[i:j]


def stat(s: str) -> str:
    return "行 %-5d 字节 %-7d sha256 %s" % (
        s.count("\n"),
        len(s.encode("utf-8")),
        sha(s)[:16],
    )


# ---------------------------------------------------------------- 新写的内容

STATUS_NEW = """\
- **投放状态：No-Go。** 放行闸＝`docs/otto-decisions-20261024.md` **D4 自愈七项**（杀进程→自动回来→被动可回→心跳 ≤10min 恢复→连续 3 次 3/3→主动侧按 C-10 状态显式记→空窗消息可补性），**不是**「连续 24 小时」；24h 已降级为观察期口径（`docs/soak-watch-card.md`）。
- **两个硬前置仍未满足**：① 真实心跳未落地——`data/probe_uptime.py` 的 `HEARTBEAT_MARKS = ()`，探针**结构上到不了 `PROVEN`**；② C-10 未修——重启后主动消息不会自动排期，**D4 前置 2 要求先修它**，否则自愈验收会把「进程回来了但她不主动说话」判成通过。
- **在办三件**：**C-15 知识注入**（Codex 承接，插件已热重载，只差一条真实命中消息打出 `[Miruku knowledge] armed`）／**C-09 四级判定**（**D2 已拍「必须实现」**，`data/probe_c09_c10.py` 的 `KNOWN_BUGS` 10 条未清零，`docs/pilot-go-no-go.md` 的 `- [ ] G2` 仍空）／**C-12·C-16 出站闸门接入**（原型 53+9 例已过，未接链路；`guard()` 三态语义未定死前**禁止接 C-16**）。
- **已关闭**：**C-17 危机告警按 D1 不实现**——书面接受「无人接管时段无法保障」，代价见决议单 D1，**每次投放重新确认**，不是一次性豁免。
- **本文件结构（2026-10-24 瘦身）**：缺陷原文 → `docs/defect-register.md`；2026-10-22 及以前的进展 → `docs/archive/WORK_LOG-archive-2026-10.md`。**查历史去归档，别只看这里。** 三方 git 约定（可 `status`/`diff`/`log`/`add`/`commit`，禁 `restore`/`checkout -- .`/`clean -fd`/`reset --hard`/`stash`）见 `docs/git-usage.md`。
"""

DEFECT_INDEX = """
> **原文已整段迁至 `docs/defect-register.md`（逐字未改，2026-10-24）。本节只留索引与指针。**
> 下表「状态」列取自**原文自述**与 `docs/otto-decisions-20261024.md`，**未重新复核运行状态**；有疑义以原文为准。
> 状态在本文件「最新进展」里变化时，请同步更新此表——**否则这张表会变成第三份过期事实**。

| ID | 优先级 | 状态（一句话） | 详情 |
|---|---|---|---|
| C-01 | P0 | **半修**：主动消息侧 `enable=true` 已落地；全局分段路径待 Codex 判；提示词已改 | 搜 `### C-01` |
| C-02 | P0 | 无修复记录；现靠「故事断点固定用 `……`」规避 | 搜 `### C-02` |
| C-03 | P1 | **登记，无需行动**：`words_count_threshold` 语义是反的，别凭名字调参 | 搜 `### C-03` |
| C-04 | P1 | 原文记录需重新实测：二次核查实测 `interval_method=random`、`log_base=2.6`，与原文的 `log`/`1.8` 不符 | 搜 `### C-04` |
| C-05 | P0 | 无修复记录；待选 A（放宽到 2，全局生效）／B（给故事续段加 gating 例外） | 搜 `### C-05` |
| C-06 | P0 | **仍未修**：重跑 `configure_proactive.py` 会静默覆盖运行配置 | 搜 `### C-06` |
| C-07 | P1 | **已确认会触发**；结论：出站记录行数 ≠ QQ 气泡数，验收只认气泡 | 搜 `### C-07` |
| C-08 | P1 | 无修复记录；故事七日窗口无持久化载体 | 搜 `### C-08` |
| C-09 | P0 | 无修复记录；**D2 已拍「必须实现四级判定」**，`KNOWN_BUGS` 10 条未清零，`- [ ] G2` 仍空 | 搜 `### C-09` |
| C-10 | P0 | 无修复记录；**D4 前置 2 要求先修**，否则自愈验收会误判通过 | 搜 `### C-10` |
| C-11 | P1 | **规范已补、v5 已通过 Codex 文档验收**；对应的告警实现按 D1 未做 | 搜 `### C-11` |
| C-12 | P0 | 无修复记录；**根因已更正**为 `<system_reminder>`（169 条里 5 条），thought 泄漏实测 0 条 | 搜 `### C-12` |
| C-13 | P1 | 无修复记录；实测连问六条里五条以反问收尾 | 搜 `### C-13` |
| C-14 | P0 | **部分改**：`prompts/system.txt` 已加边界，仍约 1/3 漏；要到 100% 只能靠出站闸门 | 搜 `### C-14` |
| C-15 | P0 | **已落地、待终验**：插件已热重载，只差一条真实命中消息打出 `[Miruku knowledge] armed` | 搜 `### C-15` |
| C-16 | P1 | **未接入**；`guard()` 三态语义未定死前**禁止接**（否则整条独白会静默发空串） | 搜 `### C-16` |
| C-17 | P0 | **已关闭（D1：不实现）**：书面接受「无人接管时段无法保障」，每次投放重新确认 | 搜 `### C-17` |

"""

PROG_POINTER = """
> **2026-10-22 及以前的进展已归档** → `docs/archive/WORK_LOG-archive-2026-10.md` §一（原文逐字未改，2026-10-24 迁出）。
> 本区只保留 2026-10-23 起的记录。要查更早的「谁在什么时候做了什么」，去归档；**别因为这里看不到就当成没发生**。
"""

RULE_NEW = (
    "> - **归档不算删改**（2026-10-24 OTTO 同意）：历史条目可**原文整段**搬入 "
    "`docs/archive/`，主文件须留一行指针——**这不算删改**。禁止改写原文；"
    "禁止删除而不留指针。\n"
)


# ---------------------------------------------------------------- 拆分

def do_split(force: bool = False) -> int:
    if os.path.exists(ARCHIVE) and not force:
        raise SystemExit("归档已存在，拒绝重复拆分：%s（确需重跑加 --force）" % ARCHIVE)

    raw = rd(SRC)
    # 防呆：源必须还是「未拆分」的原件。否则 --force 会把拆过的文件再拆一次，
    # 切出来的块是索引表而不是缺陷原文——破坏不可逆，所以宁可直接停。
    if "### C-01 P0" not in raw:
        raise SystemExit(
            "源文件看起来已经拆分过（找不到 `### C-01 P0` 原文），拒绝执行。\n"
            "要重做：先 `git restore WORK_LOG.md`（或从 %s 拷回），再跑 --split。" % BAK
        )
    lines = raw.splitlines(keepends=True)
    if "".join(lines) != raw:
        raise SystemExit("切片往返不一致，停止（行尾风格异常）")

    i = {k: idx_of(lines, v) for k, v in MARKS.items()}

    # 进展区：首条 <= 2026-10-22 的条目
    first_old = None
    for n in range(i["prog"], i["todo"]):
        s = lines[n]
        if len(s) >= 10 and s[:4].isdigit() and s[4] == "-" and s[:10] <= "2026-10-22":
            first_old = n
            break
    if first_old is None:
        raise SystemExit("进展区里找不到 2026-10-22 及以前的条目，停止")

    blk_defect = "".join(lines[i["defect"]:i["prog"]])
    blk_prog = "".join(lines[first_old:i["todo"]])
    blk_status = "".join(lines[i["status"] + 1:i["proj"]])

    h = {"defects": sha(blk_defect), "progress": sha(blk_prog), "status": sha(blk_status)}

    # 备份原件（幂等）
    if not os.path.exists(BAK):
        wr(BAK, raw)

    # ---- docs/defect-register.md
    defects_md = """# 缺陷登记表（C-01 … C-17）

> **来源**：`WORK_LOG.md`「待 Codex 修复的缺陷清单」（2026-10-22 WorkBuddy 登记），2026-10-24 **整段迁入，逐字未改**。
> `WORK_LOG.md` 保留索引表与指针；本文件是**唯一原文**，改状态请改 `WORK_LOG.md` 的索引表并在此追加说明，不要改原文。
> **核对**：本块 sha256 = `%s`（%d 行 / %d 字节）；原件 `WORK_LOG.md` 全文 sha256 前 16 位 = `%s`。复核命令见文件末尾。

## 迁移说明

- 迁入块 %d 行 / %d 字节。
- 块内标题层级原样保留（`##` 母标题 + `###` 各缺陷），因此下方原文里仍会出现一次「待 Codex 修复的缺陷清单」——**这是原文的一部分，不是重复章节**。

---

<!-- 以下为 WORK_LOG.md 原文，逐字未改（2026-10-24 迁出） -->

%s%s%s
## 完整性核对

```
%s
```

复核：`PY=data/probe_worklog_split.py` 跑 `--verify`。
""" % (
        h["defects"],
        blk_defect.count("\n"),
        len(blk_defect.encode("utf-8")),
        sha(raw)[:16],
        beg("defects"),
        blk_defect,
        end("defects"),
        stat(blk_defect),
    )

    # ---- docs/archive/WORK_LOG-archive-2026-10.md
    archive_md = """# WORK_LOG 归档（2026-10 及更早）

> **本文件是历史原文，不是现行口径。** 2026-10-24 从 `WORK_LOG.md` 整段迁入，**逐字未改**。
> 现行状态看 `WORK_LOG.md` 顶部「当前状态」；已拍板决策看 `docs/otto-decisions-20261024.md`。
> **不要引用本文件当"现在的状态"**——它只回答「当时谁做了什么」。

## 一、进展记录（2026-10-22 及以前）

迁出原因：`WORK_LOG.md` 开工必读，原文 %d 行 / %d 字节，其中这一段占 %d 字节。
迁出后主文件只留 2026-10-23 起的记录 + 一行指针。

%s%s%s
## 二、「当前状态」被替换的历史摘要

原来的「当前状态」是**滚动摘要**，同一件事在正文和这里各写一遍，越堆越长（%d 行 / %d 字节）。
2026-10-24 压到 5 行，被替换的原文如下，**逐字未改**。

%s%s%s
## 三、完整性核对（2026-10-24）

| 块 | 规模 | sha256（前 16 位） |
|---|---|---|
| 进展 ≤2026-10-22 | %d 行 / %d 字节 | `%s` |
| 「当前状态」历史摘要 | %d 行 / %d 字节 | `%s` |
| （对照）原件 `WORK_LOG.md` 全文 | %d 行 / %d 字节 | `%s` |

复核命令（只读，不写任何文件）：

```bash
PY="C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/venv/Scripts/python.exe"
"$PY" data/probe_worklog_split.py --verify
```

判定标准两条，缺一不算通过：

1. 三块的 sha256 与上表一致（**逐字节**相同，不是"看起来一样"）；
2. 原文的**非空行多重集**在「主文件 + 缺陷表 + 本归档」三处合并后**没有减少**（`--verify` 会打印 LOST 计数，必须为 0）。

> 原件已留档：`data/backups/WORK_LOG-20261024-before-split.md`（该目录被 `.gitignore` 排除，属运行时备份）。
""" % (
        raw.count("\n"),
        len(raw.encode("utf-8")),
        len(blk_prog.encode("utf-8")),
        beg(TAG_PROG),
        blk_prog,
        end(TAG_PROG),
        blk_status.count("\n"),
        len(blk_status.encode("utf-8")),
        beg(TAG_STATUS),
        blk_status,
        end(TAG_STATUS),
        blk_prog.count("\n"),
        len(blk_prog.encode("utf-8")),
        h["progress"][:16],
        blk_status.count("\n"),
        len(blk_status.encode("utf-8")),
        h["status"][:16],
        raw.count("\n"),
        len(raw.encode("utf-8")),
        sha(raw)[:16],
    )

    # ---- WORK_LOG.md 重组
    head = lines[:i["status"]]
    for n, l in enumerate(head):
        if l.startswith("> - 只追加、不删改历史记录"):
            head.insert(n + 1, RULE_NEW)
            break
    else:
        raise SystemExit("头部没找到「只追加」规则行，停止")

    out = []
    out.append("".join(head))
    out.append("## 当前状态（一句话）\n")
    out.append("\n")
    out.append(STATUS_NEW)
    out.append("\n")
    out.append("".join(lines[i["proj"]:i["defect"]]))   # 项目是什么 + 已拍板决策
    out.append("## 待 Codex 修复的缺陷清单（2026-10-22 登记｜原文已迁出，见索引）\n")
    out.append(DEFECT_INDEX)
    out.append("".join(lines[i["prog"]:first_old]))     # 最新进展 + 10-23 起
    out.append(PROG_POINTER)
    out.append("\n")
    out.append("".join(lines[i["todo"]:]))              # 当前待办 + 关键文件速查

    wr(DEFECTS, defects_md)
    wr(ARCHIVE, archive_md)
    wr(SRC, "".join(out))

    # ---- 回读核对
    ok = verify(h, raw)
    print("\n拆分完成：")
    print("  主文件  %s  %s" % (SRC, stat(rd(SRC))))
    print("  缺陷表  %s  %s" % (DEFECTS, stat(rd(DEFECTS))))
    print("  归档    %s  %s" % (ARCHIVE, stat(rd(ARCHIVE))))
    return 0 if ok else 1


# ---------------------------------------------------------------- 核对

def verify(h: dict | None = None, raw: str | None = None) -> bool:
    if raw is None:
        if not os.path.exists(BAK):
            raise SystemExit("缺少备份原件：%s（--verify 需要它当基准）" % BAK)
        raw = rd(BAK)
    lines = raw.splitlines(keepends=True)
    i = {k: idx_of(lines, v) for k, v in MARKS.items()}

    first_old = None
    for n in range(i["prog"], i["todo"]):
        s = lines[n]
        if len(s) >= 10 and s[:4].isdigit() and s[4] == "-" and s[:10] <= "2026-10-22":
            first_old = n
            break
    if first_old is None:
        raise SystemExit("备份里找不到 2026-10-22 及以前的条目")

    src_defect = "".join(lines[i["defect"]:i["prog"]])
    src_prog = "".join(lines[first_old:i["todo"]])
    src_status = "".join(lines[i["status"] + 1:i["proj"]])

    arch = rd(ARCHIVE)
    dreg = rd(DEFECTS)
    back = {
        "defects": cut_block(dreg, "defects"),
        "progress": cut_block(arch, TAG_PROG),
        "status": cut_block(arch, TAG_STATUS),
    }
    src = {"defects": src_defect, "progress": src_prog, "status": src_status}

    print("=== 一、分块 sha256（原件 vs 归档回读）===")
    allok = True
    for k in ("defects", "progress", "status"):
        same = sha(src[k]) == sha(back[k])
        allok &= same
        print("  %-9s %s  %s" % (k, "OK  " if same else "FAIL", sha(src[k])[:16]))
        if not same:
            print("     原件 %s" % stat(src[k]))
            print("     回读 %s" % stat(back[k]))
        if h and h.get(k) != sha(back[k]):
            print("     ! 与拆分时记录的哈希不符")
            allok = False

    print("\n=== 二、非空行多重集（证明一行未丢）===")
    norm = lambda t: Counter(l.strip() for l in t.splitlines() if l.strip())
    o = norm(raw)
    n = norm(rd(SRC) + "\n" + dreg + "\n" + arch)
    lost = o - n
    extra = n - o
    print("  原文非空行 %d 条（去重 %d 种）" % (sum(o.values()), len(o)))
    print("  拆后非空行 %d 条（去重 %d 种）" % (sum(n.values()), len(n)))
    print("  LOST  = %d 条  ← 必须为 0" % sum(lost.values()))
    print("  EXTRA = %d 条  ← 本次新增（状态 5 行、索引表、指针、规则、核对表）" % sum(extra.values()))
    if lost:
        print("\n  !! 丢了这些行：")
        for line, c in list(lost.items())[:20]:
            print("     x%d  %s" % (c, line[:110]))
        allok = False
    if extra:
        print("\n  新增行抽样（前 6 条，人工确认都是本次写的）：")
        for line, c in list(extra.items())[:6]:
            print("     +%d  %s" % (c, line[:110]))

    print("\n=== 三、原文字节守恒 ===")
    moved = sum(len(back[k].encode("utf-8")) for k in back)
    print("  原件全文      %d 字节" % len(raw.encode("utf-8")))
    print("  迁出的三块合计 %d 字节" % moved)
    print("  主文件现在    %d 字节（原 %d，减 %d）" % (
        len(rd(SRC).encode("utf-8")),
        len(raw.encode("utf-8")),
        len(raw.encode("utf-8")) - len(rd(SRC).encode("utf-8")),
    ))

    print("\n结论：%s" % ("通过（分块逐字节一致，且原文一行未丢）" if allok else "不通过，见上"))
    return allok


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--verify"
    if mode == "--split":
        return do_split(force="--force" in sys.argv)
    if mode == "--verify":
        return 0 if verify() else 1
    raise SystemExit("用法：--split [--force] / --verify")


if __name__ == "__main__":
    sys.exit(main())
