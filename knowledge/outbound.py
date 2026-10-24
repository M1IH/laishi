#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出站闸门：对**模型已经生成的回复**做确定性校验与清洗。

为什么它是出站而不是入站
------------------------
入站注入只能"给模型材料"，管不了它会不会自己编；提示词约束的经验上限约为 2/3
（C-14 约局三次漏一次、b50 未接入时全靠编）。**编造和泄漏无法用提示词根治，
只能被出站规则消除**——因为出站这一层看的是**形状**，不是**语义**。

三个已知问题共用同一层（这是本模块存在的理由）：
  C-12  `<thought>` / `[Profile: ...]` / DSML 标记泄漏到正文
  C-14  "来啊 / 几点 / 你先开 / 房间号" —— 约局承诺（做不到的事）
  编造   回复里的 R 值、定数、达成率、段位数字，真值表里找不到

用法：
    from outbound import check, guard
    report = check(reply_text)
    if report.changed:   reply = report.text
    if not report.ok:    reply, used_fallback = guard(reply_text)   # 分层改写
    if not reply:        # 不要发送
        ...

判据（写进验收）：**回复里出现的任何成绩数字，必须能在 b50 真值表里逐字找到；
约局承诺必须为零；结构标记必须为零。**

**关于「重生成」（2026-10-22 判定，见 `docs/outbound-guard-verdict.md`）**：
本模块**不建议**重生成，`guard()` 做的是确定性的分句删除。理由不是成本，是原理——
L3 的违规源是**知识缺失**（她手上没有表外那首歌的数字，再采样只会换个数字编）；
L2/L2.5 的违规是**局部短语**（删掉那个分句就够，整条重来反而丢掉有用信息）。
只有一种情形值得重生成：剥离+删除后**为空**——此时调用方应重发一次；仍为空就**不发送**。

2026-10-23 修复记录（DS-04 审计，见 `docs/outbound-adversarial-audit.md`）
--------------------------------------------------------------------
本轮修掉 B-1 ~ B-14 共 14 个阻断项，其中 11 项的根因是**同一个**：所有正则都
写死了半角字符。模型抄内部标记时经常带全角（中文输入法下 `＜thought＞`、
`Ｒ２８５` 很常见），而 `re` 不做 unicode 归一、`re.I` 也不折叠全角字母——
于是整层规则形同虚设。所以这版引入三件事：

1. `_lit()`：把字面量编译成**全角/半角都认**的正则（`<thought>` → `[<＜][tｔTＴ]...`）。
   用于 L1 剥离，作用在**原文**上（不能对原文跑 NFKC，否则中文标点全变半角）。
2. `_norm_detect()`：NFKC + 去零宽 + 去千分位，**只用于检测副本**。
   用于 L2/L2.5/L3 的判定，不改变最终发出的字符。
3. 舞萌豁免从「同句出现就免罪」改成「先剔除豁免词再判」——修掉
   「我打街霸6和舞萌」被后半截洗白的漏洞。
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRUTH_PATH = ROOT / "data" / "maimai" / "b50_miruku.json"
# 官方曲库（1,344 首，含每首各难度的 level_value）。用途只有一个：
# **带曲名的定数可以核对**。「躯樹の墓守 MASTER 14.9」是真的，「某首 13.9 的歌说 14.9」是假的。
# 不带曲名的定数核对不了（那首歌可能是她没打过的），只能做范围检查——这条边界写在审计文档里。
SONGLIST_PATH = ROOT / "data" / "maimai" / "song_list.json"

_SONG_LEVELS: dict | None = None


def song_levels() -> dict:
    """曲名 → 这首歌**真实存在**的定数集合（来自官方曲库的 level_value）。

    为什么需要：只做范围检查（1.0–15.0）挡不住「把某首 13.9 的歌说成 14.9」。
    带上曲名时就用这张表核对——「躯樹の墓守 MASTER 14.9」是 14.9，说 14.7 就是编的。
    不带曲名时仍然只能做范围检查（那首歌可能是她没打过的，无法证伪）。
    """
    global _SONG_LEVELS
    if _SONG_LEVELS is not None:
        return _SONG_LEVELS
    out: dict = {}
    try:
        data = json.loads(SONGLIST_PATH.read_text(encoding="utf-8"))
        songs = data.get("songs") or []
    except (OSError, ValueError):
        songs = []
    for s in songs:
        title = _norm_title(str(s.get("title") or ""))
        if not title:
            continue
        lv = set()
        for arr in (s.get("difficulties") or {}).values():
            for d in arr or []:
                try:
                    lv.add(round(float(d["level_value"]), 1))
                except (KeyError, TypeError, ValueError):
                    continue
        if lv:
            out.setdefault(title, set()).update(lv)
    _SONG_LEVELS = out
    return out

# ---------------------------------------------------------------- 0. 入口归一化
# 零宽字符（U+200B 等）插在词中间会让所有边界条件失配：「来\u200b啊」不算邀约。
_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")
# 千分位逗号：「R1,5200」会被 `\d{3,5}` 截成 `1`，整条正则不匹配 → 绕过白名单。
# 2026-10-23：原来只认 `(?<=\d),(?=\d{3}(?!\d))` 这种**规范**千分位，
# 于是「R1,4065」（逗号后 4 位，不规范）照样绕过（审计 L3-16）。
# 现在只要逗号夹在两个数字之间就删掉——这是检测副本，删了不影响正文。
_THOUSANDS = re.compile(r"(?<=\d)[,，](?=\d)")


def _clean_invisible(s: str) -> str:
    return _INVISIBLE.sub("", s)


def _norm_detect(s: str) -> str:
    """**只用于检测的副本**：全角折半角 + 去零宽 + 去千分位。

    绝不能拿它的输出当正文发出去——NFKC 会把「，」折成「,」，中文标点全毁。
    """
    s = _INVISIBLE.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    s = _THOUSANDS.sub("", s)
    return s


# 全角变体表：ASCII 可见字符的 +0xFEE0 是它的全角形态，个别符号另有异体。
_EXTRA_CLS = {
    "[": "［【", "]": "］】", "<": "＜", ">": "＞",
    ":": "：", "/": "／", "|": "｜", "\\": "＼", ".": "．", "-": "－", "_": "＿",
}


def _lit(s: str) -> str:
    """把字面量编译成「全角/半角/大小写都认」的正则片段。

    为什么不用 `re.I`：Python 的 `re.I` 对全角字母 `ｔ` 和半角 `t` 不做互相折叠，
    `＜ｔｈｏｕｇｈｔ＞` 这种写法会整条漏掉（B-14）。
    """
    out = []
    for ch in s:
        alts = [ch]
        o = ord(ch)
        if 0x21 <= o <= 0x7E:
            alts.append(chr(o + 0xFEE0))
        alts.extend(_EXTRA_CLS.get(ch, ""))
        if ch.isalpha():
            alts.extend(a.upper() for a in list(alts))
            alts.extend(a.lower() for a in list(alts))
        seen = list(dict.fromkeys(alts))
        out.append("[" + "".join(re.escape(a) for a in seen) + "]")
    return "".join(out)


# ---------------------------------------------------------------- 1. 泄漏剥离
# 这些都是"模型把内部状态写到正文里"的产物，形态固定，正则即可 100% 清掉。
#
# 顺序有讲究：成对的先于单个标签，system_reminder 成对先于未闭合。
_CLOSE_THOUGHT = re.compile(_lit("</thought>"))
_OPEN_THOUGHT = re.compile(_lit("<thought>"))

# **最内层优先**的成对匹配：内容里不许再出现开标签。
# 普通非贪婪在嵌套时会留下残渣：
#   `<thought>a<thought>b</thought>c</thought>好的`
#   → 删掉 `<thought>a<thought>b</thought>` → 剩 `c</thought>好的` → 残渣「c」成正文。
# 用「内层先删、循环到不动」就能正确收敛到「好的」，同时不影响
#   `<thought>甲</thought>打啊<thought>乙</thought>好的` → `打啊好的`
_THOUGHT_PAIR = re.compile(
    _lit("<thought>") + r"(?:(?!" + _lit("<thought>") + r")[\s\S])*?" + _lit("</thought>")
)

LEAK_PATTERNS = [
    # 成对 thought（最内层优先，见上）。
    (_THOUGHT_PAIR, "thought"),
    (re.compile(_lit("<think>") + r".*?" + _lit("</think>"), re.S), "think"),
    (re.compile(_lit("<thinking>") + r".*?" + _lit("</thinking>"), re.S), "think"),
    # [Profile: 爱好=舞萌]。闭合括号可能是 `]`/`］`/`】`（B-3）。
    (re.compile(_lit("[Profile:") + r"[^\]］】\n]*" + _lit("]")), "profile"),
    # 无括号的裸形态：`Profile: 爱好=舞萌`。只吃 key=value，不吃后面的正文。
    # 注意不能匹配「我的 profile 没啥好写的」——那句没有冒号。
    (re.compile(r"Profile\s*[:：](?:\s*[^\s=，。！？!?,]+=[^\s，。！？!?,]*)*\s*", re.I),
     "profile-bare"),
    # DSML 标记的竖线有两套字符：半角 `|`（U+007C）和**全角 `｜`（U+FF5C）**。
    # 2026-10-20 15:57 那条真实泄漏用的是全角，旧写法只认半角 → 假阴性。
    (re.compile(r"</?[|｜]{1,3}DSML[|｜]{1,3}[^>＞]*[>＞]?"), "dsml"),
    # 系统注入的提醒块被模型抄进正文（2026-10-20 12:43 与 15:57 各一条）。
    (re.compile(_lit("<system_reminder>") + r".*?" + _lit("</system_reminder>"), re.S),
     "sys-reminder"),
    # 未闭合的那种：只吃标签 + 已知的 datetime 载荷，**不再一路切到结尾**。
    # 旧写法 `.*\Z` 会把标签后面她本来想说的话一起吃掉
    # （「好的<system_reminder>Current datetime: … 我也想知道」→ 只剩「好的」）。
    (re.compile(_lit("<system_reminder") + r"[^>＞\n]*[>＞]\s*"
               r"(?:(?:Current|current)\s+(?:datetime|time|date)\s*[:：]?\s*)?"
               r"\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?"
               r"(?:\s*\([A-Za-z]+\))?"
               r"(?:\s*,\s*(?:Weekday|weekday)\s*[:：]\s*[A-Za-z]+)?"),
     "sys-reminder-unclosed"),
    (re.compile(_lit("<system_reminder") + r"[^>＞\n]*[>＞]"), "sys-reminder-tag"),
    # 被括号包住的内部状态行：「（更新：joy:2）」（B-3）
    (re.compile(r"[\(（]\s*(?:感知|评估|决策|更新|代谢|思考|内心|分析|自检|判定)"
                r"\s*[:：][^\)）\n]*[\)）]"), "state-paren"),
    # 裸独白行：完全没有标签的 `[感知] …` / `[决策] …` / `[更新] joy:2`（B-2）。
    # 吃到行尾或下一个方括号为止，不会跨行吞正文。
    (re.compile(r"[\[［【]\s*(?:感知|评估|决策|更新|代谢|思考|内心|分析|自检|判定)"
                r"\s*[\]］】][^\n\[\]［］【】]*"), "monologue-line"),
    (re.compile(_lit("tool_calls") + r"\s*[:：]?\s*"), "tool-calls"),
    # 兜底：所有残留的裸标签
    (re.compile(_lit("</thought>") + "|" + _lit("<thought>")), "thought-tag"),
    (re.compile(_lit("</think>") + "|" + _lit("<think>") + "|"
                + _lit("</thinking>") + "|" + _lit("<thinking>")), "think-tag"),
    (re.compile(_lit("</tool_calls>") + "|" + _lit("<tool_calls>")), "tool-tag"),
    (re.compile(_lit("</system_reminder>")), "sys-reminder-tag"),
]

# ---------------------------------------------------------------- 2. 约局承诺
# 只抓**未来/邀请**形态。过去的"一起打过"是合法叙述（跟夏玛拼过机），必须放过。
#
# 2026-10-22 22:5x 第一版重写：旧表只有 5 条强规则，且「来」要求前后是标点/边界，
# 实测 10 条最像真约局的口语说法**10 条全漏**。
# 2026-10-23 第二轮（B-4/B-5/B-13）：
#   · 补 开黑/来不来/一起玩/见面/好友/上线/带我 七类高频形态
#   · 「几点」原来只写 `几点开|你几点`，把「机台那边几点开」「你几点去打舞萌」
#     这两句**合法问句**也拦了（B-5）。改成只认她自己的时间承诺。
#   · 「时间地点」原来认「时间+机台/出勤」，于是「周末去机台吗」「我今天出勤」
#     这些她的日常叙述被判成违约（B-13）。改成只认**见面语义**（见/来打/拼机/等你）。
INVITE_STRONG = [
    ("来", r"(?:^|[\s，,。！!～~])(?:来|来来|这就来)(?:啊|呀|嘛|吧|了)?(?:$|[\s，,。！!～~])"),
    ("几点", r"(?:我|咱们?|我们)几点|几点(?:开打|上线|碰)|约(?:个)?几点"),
    # 2026-10-23：「来啊，几点开」删掉「来啊」后剩「几点开」——约局的尾巴还在。
    # 但「机台那边几点开」「机台几点开」是**合法问句**（问场馆/机台开门时间），
    # 必须放过，所以用 lookbehind 挡掉地点前缀。
    ("几点开", r"(?<!那边)(?<!机台)(?<!店里)(?<!商场)几点开(?!打)"),
    ("你先开", r"你先开|你先建|你先拉|开个房|建房|拉我|邀我"),
    ("房间号", r"房间号|房号|房ID|组我|带我上分"),
    ("我开", r"我开(?:个)?房|我来开|我建房|我拉你"),
    # 「来」+ 动作：口语最高频形态。三条 lookbehind 挡掉非承诺：
    #   你自己来打就知道了（让对方来，不是她来）
    #   来世来打舞萌吗（对方名字带「来」）
    #   来打个SSS（「拿到」的意思，不是到场）
    ("来打", r"(?<!你自己)(?<!来世)来(?:打(?!个|出)|一局|一把|一盘|两把|玩玩|搓)"),
    ("开黑", r"开黑|开一局|开一把|上号(?:等|拉)?"),
    # 2026-10-23：`(?:来|去|打|玩|上)不(?:来|去|打|玩)` 会把「杰米那套我打不来」
    # 判成邀约——「打不来」是"不会"，不是"来不来"。改成要求**同一个字**重复。
    ("来不来", r"(来|去|打|玩|上)不\1"),
    # 她单方面承诺**亲自到场**——比邀请对方更严重，因为兑现不了
    ("到场", r"我(?:马上|这就|现在就|一会儿|等会|晚点)?(?:过去|到)|"
             r"我(?:这就|马上|立刻)来|我在机台等|等我过去|我等你(?:来|到|啊|呀|哦|嘛|$)"),
    ("陪打", r"我(?:就|也|可以|能|会|肯定|一定|想|要|来)*"
             r"(?:陪你|带你|跟你|和你|跟你俩)(?:打|玩|上分|出勤|一起)|"
             r"(?:一起|和我|跟我|陪我)出勤"),
    # 见面语义：`见/碰/约` 才算约定；单纯「去机台」「出勤」是她自己的日常。
    ("见面", r"(?:明天|周末|今晚|改天|下周|周[一二三四五六日天]|过两天|月底)"
             r"[^。！？!?\n]{0,8}(?:见|碰|约)"),
    # 2026-10-23 第三轮：「你什么时候来」「你几点来」是**把对方往某个地点约**，
    # 而她到不了场。原来这条只认「几点开打/几点上线」，整句漏掉（真实样本探针
    # 「约局·什么时候来」）。
    # 收紧到「疑问词 + 来」且后面不接动作/地点：`你什么时候来打` 归「来打」管，
    # `你自己来打就知道了`、`来世来打舞萌吗` 不受影响。
    ("你来", r"你(?:什么时候|啥时候|几点|几时)来(?!打|玩|试|看|听|学|帮|接)"),
    # 2026-10-23 第三轮：**将来时的出勤**是到场承诺，和「我今天出勤」不同。
    # 「我今天出勤」「昨天出勤了」是她的日常叙述（她真去机台），必须放过；
    # 「我这周末出勤」「明天出勤」是把未来的自己许出去，兑现不了。
    # 判据：将来时间词 + 出勤，且中间不夹否定、句尾不带疑问（「明天出勤吗」是问对方）。
    ("将来出勤", r"(?:这?周末|明天|后天|下周|下周末|改天|晚点|等会|过两天|月底)"
                r"[^。！？!?\n]{0,6}(?<!不)出勤(?!吗|么)"),
    ("好友", r"加(?:个)?(?:好友|QQ|qq|微信)|好友码|二维码|扫我"),
    ("上线", r"我(?:先)?上线(?:了)?等|我(?:先)?上号(?:了)?等|我(?:这|马上)上号"),
    ("带我", r"你(?:带|教)我(?:打|玩|上分|一把|两把)"),
]
INVITE_WEAK = [
    ("一起打", r"一起打(?:一?把|一?局|两把)?"),
    ("一起玩", r"(?:一起|一块|一块儿)(?:玩|打|上分|开黑)"),
    ("来啊", r"来啊|来嘛|来呀"),
]
# 「一起打过」这类过去式，命中 weak 也放过
PAST_MARKERS = ("过", "了过", "昨天", "前天", "以前", "上次", "那次", "拼过", "出勤")
# 强规则里需要过去式保护的（时间地点那条最容易误伤「今天出勤了」）
# 2026-10-23：`上线` 从这张表里删掉。「我上线了等你」的「了」是**即将上线**的体貌，
# 不是过去式；原来被 PAST_TENSE 的 `了` 规则当成回忆放过（审计 L2-12）。
PAST_GUARDED = {"时间地点", "见面", "来打", "到场", "陪打"}
# 用正则而不是子串：裸「过」会把「等我过去」「过去那边」误判成过去式。
# `那天` 是 B-13 补的：「那天我们一起出勤」是回忆，不是约定。
PAST_TENSE = re.compile(
    r"(?:过(?!去|来|几|一|两|这|那|会)|了(?!解|不起)|昨天|前天|上次|那次|以前|"
    r"刚才|已经|那天|那次|那时候|之前)"
)


# ---------------------------------------------------------------- 3. 自称上手
# OTTO 2026-10-22 21:44 重定：街霸6、三角洲**她懂但不打**，舞萌才是唯一真打的项目。
# 模型为了共鸣极易说"我也玩"，而这句话一出现，前面所有"我不打"的设定全废。
# 判据：同一分句里既出现**她不上手的游戏**，又出现**第一人称上手动词** → 拦。
NOT_PLAYER_GAMES = (
    "街霸", "格斗", "三角洲", "搜打撤", "撤离模式", "撤离点",
    # 街霸6 角色名：她说"我最近在练嘉米"＝她在打街霸，光靠游戏名抓不到
    "杰米", "嘉米", "春丽", "古烈", "桑吉尔夫", "豪鬼", "卢克", "玛丽莎",
    "朱莉", "曼侬", "金伯莉", "莉莉", "达尔西姆", "布兰卡", "拉希德",
    "Jamie", "Cammy", "Ryu", "Ken", "Juri", "Guile", "Zangief", "Marisa",
)
# 这些是她的**真实日常**，不是洗白工具。B-12 的教训：原来是「同句出现就整句放过」，
# 于是「我打街霸6和舞萌」被后半截免罪。现在改成**先剔除豁免词，再判剩下的部分**。
PLAYER_EXEMPT_GAMES = ("舞萌", "maimai", "机台", "出勤", "洗衣机")
SELF_PLAY_RE = re.compile(
    r"(?:我|俺)"
    r"(?:也|就|还|又|常|经常|常常|天天|平时|最近|现在|以前|偶尔|一般|主要|主|"
    r"会|能|开始|已经|都)*"
    r"(?:在|正在)?"
    # `打(?!开|听|算|赌|…)`：B-8 的根因——「我打开街霸6看看」里的「打开」不是「打」。
    r"(?:玩|打(?!开|听|算|赌|扮|扫|印|包|字|车|电话|呵|哈)|练|搓|上分|开镜|刷|肝)"
)
# 「我用杰米上分」「我主玩杰米」：角色名夹在动词中间，SELF_PLAY_RE 抓不到。
SELF_PLAY_RE2 = re.compile(
    r"(?:我|俺)(?:也|就|还|平时|最近|现在|一般|主要|主)?"
    r"(?:用|拿|使|选)(?:杰米|嘉米|春丽|古烈|桑吉尔夫|豪鬼|卢克|玛丽莎|朱莉|曼侬|"
    r"金伯莉|莉莉|达尔西姆|布兰卡|拉希德|Jamie|Cammy|Ryu|Ken|Juri|Guile|Zangief|Marisa)",
    re.I,
)
# 「我街霸6和三角洲都玩」：动词前的不是副词而是**游戏名并列**，
# 主语「我」和动词之间隔了 10 个字，SELF_PLAY_RE 的紧邻匹配抓不到（B-12 之二）。
SELF_PLAY_RE3 = re.compile(
    r"(?:我|俺)[^，。！？!?\n]{0,10}?(?:都|也|常|经常|天天|一般|主要|主|还)"
    r"(?:在)?(?:玩|打(?!开|听|算|赌|扮|扫|印|包|字|车|电话|呵|哈)|练|搓|上分)"
)
# 这些不是"我打过"，是"我打不过/我没打过"，必须放过
SELF_PLAY_EXEMPT = (
    "打不过", "打不赢", "打不动", "打不来", "打不了", "打不好", "打不动",
    "没打过", "没玩过", "不打", "不玩", "打赌", "打听", "打电话", "打车",
    "打哈", "打不开", "打错", "打的是", "打开", "没在打",
)
# 跨分句继承主语：`我不打街霸6，但是我会玩` —— 后半句的主语是前半句的游戏。
# 只在**明确的连接词**开头时继承，避免「我不打街霸6。对了我会玩舞萌」误伤。
_CONT_CLAUSE = re.compile(r"^(?:但是|但|不过|而且|然后|还有|还|也|就|其实|可是)")

# ---------------------------------------------------------------- 4. 成绩数字
# 2026-10-23：删掉 `SCORE_CONTEXT` 早退（B-9）。旧写法 `if not any(k in text ...): return []`
# 让「我B35是12000」「我打了100.8%」「那首 14.9 级吧」**根本没进检测**。
# 性能代价可以忽略（4 条正则 × 分句数），换来的是不再有"某个词不在词表里就整条放过"。
SCORE_PATTERNS = [
    # 5 位必须有：真实 R 值 14065 是 5 位数。写成 {2,4} 会把「R 14065」
    # 截成 1406，再拿去和真值比 → 报自己真数的句子反被判违规。
    # `(?<![A-Za-z])` 挡掉 `SSR285` 这类粘连；`{3,5}` 挡掉「R15 那台机器」（B-5 同族误伤）。
    ("r_value", re.compile(r"(?<![A-Za-z])[Rr]\s?(\d{3,5})(?!\d)")),
    # 定数有两种语序：「14.9 级」和「定数 14.9」（口语几乎全是后者）
    ("level", re.compile(r"(\d{1,2}\.\d)\s*(?:定数|级|的谱)")),
    ("level", re.compile(r"(?:定数|难度)\s*[:：]?\s*(\d{1,2}\.\d)")),
    ("achievement", re.compile(r"(\d{2,3}(?:\.\d{1,4})?)\s*[%％]")),
    # 口语常省略 %：「这首达成率 98.7」
    ("achievement", re.compile(r"(?:达成率|准确率|acc)\s*[:：]?\s*(\d{2,3}(?:\.\d{1,4})?)", re.I)),
    # 总分是 5 位、以 1 开头；B35/B15 也是同一个量级
    ("rating_total", re.compile(r"(?<!\d)(1[0-9]{4})(?!\d)")),
    # 「我打了285分」：单曲 R 的口语说法
    ("r_value", re.compile(r"(?:打|拿|上|刷)了?\s*(\d{2,4})\s*分")),
]

# 段位牌（R 值底色）。她说「我白金框」而真值是金框——这是**比真值更高**的编造，必须拦。
# 只拦"往上编"，往下说（我银框）是自谦，不拦。
#
# 顺序必须按官方 R 值阶梯，不能凭印象排（2026-10-24 修过一版）：
#   白 <999｜青 1000-1999｜绿 2000-3999｜黄 4000-6999｜红 7000-9999｜紫 10000-11999
#   铜 12000-12999｜银 13000-13999｜金 14000-14499｜白金 14500-14999｜虹 15000+
# 两处旧错：① 紫被排在白金之后（当成最高档），于是「我紫框」被误判成"往上编"而误拦；
#          ② 「彩/虹/彩虹」不在集合里，`said not in PLATE_ORDER` 直接放行 →「我彩框」漏检。
# 中文圈把 15000+ 的彩虹底色口语叫「彩框」，与「虹框」同指，务必都收。
PLATE_CANON = {
    "緑": "绿",
    "紅": "红",
    "赤": "红",
    "銅": "铜",
    "銀": "银",
    "黃": "黄",
    "橙": "黄",
    "彩": "虹",
    "彩虹": "虹",
    "鉑": "白金",
}
PLATE_ORDER = ["白", "青", "绿", "黄", "红", "紫", "铜", "银", "金", "白金", "虹"]
# 真值里的 `rating_rank` 是 `"金（14000-14499）"` 这种带区间的写法，要取出牌名本身。
_RANK_HEAD = re.compile(
    r"^\s*(白金|鉑|彩虹|彩|虹|金|銀|银|銅|铜|紫|赤|紅|红|黃|橙|緑|绿|青|白)"
)
_PLATE_WORDS = (
    r"(?:白金|鉑|彩虹|彩|虹|金|銀|银|銅|铜|紫|赤|紅|红|黃|橙|緑|绿|青|白)"
)
PLATE_RE = re.compile(
    r"我(?:是|现在|已经|才|还|也就|目前)?\s*(" + _PLATE_WORDS + r")\s*(?:框|牌)"
)
# 版本牌子（極/将/神/舞舞/覇者）是**另一套体系**：按"该版本全曲 FC/SSS/AP"授予，
# 与 R 值底色无关，不能塞进 PLATE_ORDER 比较大小。她说「我极牌」等于自称拿到某个
# 版本的全曲 AP——b50 里没有任何证据，属具体成就编造，一律拦。
VERSION_PLATE_RE = re.compile(
    r"我(?:是|现在|已经|才|还|也就|目前)?\s*"
    r"(?:(?:这|那|上)?(?:个)?版本(?:的)?|这一期(?:的)?|上期(?:的)?)?\s*"
    r"(極|极|将|將|神|舞舞|覇者|霸者)\s*牌"
    r"(?!\s*(?:还没|没|不|差))"
)


@dataclass
class Report:
    text: str
    leaks: list[str] = field(default_factory=list)
    invites: list[str] = field(default_factory=list)
    scores: list[str] = field(default_factory=list)
    selfplay: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.leaks)

    @property
    def empty(self) -> bool:
        """剥离后没有可发正文。调用方必须判这个——空消息发出去是事故。"""
        return not self.text.strip()

    @property
    def violations(self) -> list[str]:
        out = []
        if self.invites:
            out.append("约局承诺：" + "、".join(self.invites))
        if self.scores:
            out.append("表外成绩数字：" + "、".join(self.scores))
        if self.selfplay:
            out.append("自称会打（她只懂不打）：" + "、".join(self.selfplay))
        return out

    @property
    def ok(self) -> bool:
        return not self.violations


def _load_truth(path: Path = TRUTH_PATH) -> dict:
    """真值表：全局数字集 + **按曲名分组的数字集** + 总分集 + 段位。

    为什么必须分组：全局白名单抓不到"数字合法但配错了曲"的情况——
    「病み垢我打了 R285」里的 285 在别的曲目上确实存在（ツギハギスタッカート R285），
    只比全局集合会直接放过。**成绩造假的常见形态恰恰是"拿一个真数字安到错的曲子上"。**
    所以判定顺序是：句子里出现了哪首曲名 → 那个数字必须属于**这首歌**。
    """
    empty = {"numbers": set(), "levels": set(), "songs": {}, "totals": set(), "rank": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    numbers, levels, songs, totals = set(), set(), {}, set()
    for key in ("b35", "b15"):
        for e in data.get(key, []):
            lv = round(float(e["level"]), 1)
            rv = int(e.get("rating_value") or 0)
            acc = round(float(e["achievement"]), 4)
            levels.add(lv)
            numbers.update({lv, rv, acc})
            allowed = {lv, rv, acc}
            title = str(e.get("title") or "").strip()
            if title:
                songs[_norm_title(title)] = allowed
    # 2026-10-23：删掉 `numbers.update({14000, 14500})`。
    # 那两行是为口语「一万四」加的，但「一万四」没有阿拉伯数字，根本走不到这里；
    # 留下的唯一效果是让「我14500」「我R14000」这类**编造**通过白名单（审计 B-9 之一）。
    for v in (data.get("rating_total"), data.get("rating_b35"), data.get("rating_b15")):
        if v:
            totals.add(int(v))
    numbers.update(totals)
    rank = str(data.get("rating_rank") or "").strip() or None
    return {"numbers": numbers, "levels": levels, "songs": songs,
            "totals": totals, "rank": rank}


def _norm_title(s: str) -> str:
    return re.sub(r"[\s　·,，.。!！?？~～\-—_()（）\[\]【】:：/／]", "", s).lower()


_CLAUSE = re.compile(r"[。！？!?\n；;，,、]+")

_TRUTH = None


def truth() -> dict:
    global _TRUTH
    if _TRUTH is None:
        _TRUTH = _load_truth()
    return _TRUTH


def strip_leaks(text: str) -> tuple[str, list[str]]:
    hits: list[str] = []
    text = _clean_invisible(text)
    # 循环 4 轮：嵌套标记一轮清不干净。
    #   `<thought>a<thought>b</thought>c</thought>好的`
    #   第一轮非贪婪只删掉 `<thought>a<thought>b</thought>`，剩 `c</thought>好的`；
    #   第二轮走「只有闭合标签」分支，切到最后一个 `</thought>` 之后 → `好的`。
    for _ in range(4):
        before = text
        # 先把**成对**的 thought 反复删到不动，再让兜底的裸标签规则上场。
        # 为什么必须分阶段：`<thought>a<thought>b</thought>c</thought>好的`
        # 一轮里删掉内层后剩 `<thought>ac</thought>好的`，如果**同一轮**就执行
        # 「残留裸标签」兜底，那个兜底会把外层的 `<thought>` 也删掉，
        # 于是外层配对再也拼不起来，最后剩 `ac好的`——中间那段独白成了正文。
        # 分开之后：内层删完 → 外层拼上 → 下一轮整对删掉 → `好的`。
        for _ in range(4):
            if not _THOUGHT_PAIR.search(text):
                break
            if _THOUGHT_PAIR.sub("", text) == text:
                break
            hits.append("thought")
            text = _THOUGHT_PAIR.sub("", text)
        # 只有闭合标签：实测最常见的一种是开头漏了 <thought>，
        # 于是**整段内部独白成了正文**，只剩一个 </thought> 在末尾。
        closes = list(_CLOSE_THOUGHT.finditer(text))
        opens = list(_OPEN_THOUGHT.finditer(text))
        if closes and not opens:
            text = text[closes[-1].end():]
            hits.append("thought-prefix")
        # 未闭合的开标签（B-1）：旧写法只删标签本身，整段独白留在正文里。
        # 有开无合 → 从开标签一路切到结尾。
        elif opens:
            last_close = closes[-1].start() if closes else -1
            unclosed = [m for m in opens if m.start() > last_close]
            if unclosed:
                text = text[:unclosed[0].start()]
                hits.append("thought-unclosed")
        for pattern, name in LEAK_PATTERNS:
            if pattern.search(text):
                hits.append(name)
                text = pattern.sub("", text)
        if text == before:
            break
    # 清完之后可能剩下空行首尾
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, list(dict.fromkeys(hits))


def find_invites(text: str) -> list[str]:
    t = _norm_detect(text)
    found = []
    for name, pattern in INVITE_STRONG:
        m = re.search(pattern, t)
        if not m:
            continue
        if name in PAST_GUARDED:
            # 过去式放过：「今天出勤了」「上次来打了两把」「那天我们一起出勤」
            window = t[max(0, m.start() - 10): m.end() + 10]
            if PAST_TENSE.search(window):
                continue
        found.append(name)
    for name, pattern in INVITE_WEAK:
        m = re.search(pattern, t)
        if not m:
            continue
        # 过去式放过：「一起打过」「上次不是拼过机」
        window = t[max(0, m.start() - 12): m.end() + 8]
        if any(mark in window for mark in PAST_MARKERS):
            continue
        found.append(name)
    return found


def find_self_play_claims(text: str) -> list[str]:
    """她说"我也玩街霸"这类断言——违反"懂但不打"。返回命中的分句。"""
    bad, _ = _scan_self_play(text)
    return bad


def _scan_self_play(text: str, carry: str | None = None) -> tuple[list[str], str | None]:
    """同 `find_self_play_claims`，但把「上一句在说哪个游戏」带出去。

    为什么要带：`我不打街霸6，但是我会玩` 的违规在后半句，而后半句**没有游戏名**。
    单句判定看不见主语继承，`degrade()` 就会把整条原样放行——审计 B-7 的连带项。
    """
    bad: list[str] = []
    for clause in _CLAUSE.split(text):
        c = _norm_detect(clause).strip()
        if not c:
            continue
        # B-12：先把豁免词（舞萌/机台/出勤/洗衣机）从判定副本里剔掉再判。
        # 「我打街霸6和舞萌」→ 剔完是「我打街霸6和」→ 后半截再也洗不白前半截。
        stripped = c
        for g in PLAYER_EXEMPT_GAMES:
            stripped = stripped.replace(g, "")
        games = [g for g in NOT_PLAYER_GAMES if g in stripped]
        if games:
            carry = games[0]
        elif carry and _CONT_CLAUSE.match(c) and not any(
            g in c for g in PLAYER_EXEMPT_GAMES
        ):
            # 跨分句继承：`我不打街霸6，但是我会玩`
            games = [carry]
        if not games:
            continue
        m = (SELF_PLAY_RE.search(stripped) or SELF_PLAY_RE2.search(stripped)
             or SELF_PLAY_RE3.search(stripped))
        if not m:
            continue
        # B-8：豁免窗口从 ±2/+4 扩到 -4/+8。
        # 「我打街霸6打不过」原来窗口是「我打街霸6打」，刚好把「不过」切在外面。
        window = stripped[max(0, m.start() - 4): m.end() + 8]
        if any(ex in window for ex in SELF_PLAY_EXEMPT):
            continue
        bad.append(c)
    return bad, carry


def _numbers_in(s: str) -> list[tuple[str, str]]:
    out = []
    for kind, pattern in SCORE_PATTERNS:
        for m in pattern.finditer(s):
            out.append((kind, m.group(1)))
    return out


def _allowed(raw: str, kind: str, allowed: set, has_song: bool,
             song_titles: tuple = ()) -> bool:
    try:
        if kind == "level":
            # 定数是**游戏事实**，不是她的成绩：只要在 1.0–15.0 之间就是合法值。
            # 旧写法 `a < 15` 让 15.0 永远不合法，而 15 级三首（系ぎて /
            # Xaleid◆scopiX / PANDORA PARADOXXX）真实存在（审计 B-9 之一）。
            #
            # 为什么不再拿 b50 比对：b50 只有她打过的 12 个定数，
            # 「躯樹の墓守 MASTER 14.9」是**真的**、但她没打出成绩，表里就没有。
            # 拿 b50 当权威会把她说的真话判成造假。
            v = round(float(raw), 1)
            if not 1.0 <= v <= 15.0:
                return False
            # 带曲名时能进一步核对：这首歌的真实定数里有没有这个值。
            # 「某首 13.9 的歌说 14.9」在这里被挡住（审计 L3-06 的判定变更见文档）。
            if song_titles:
                table = song_levels()
                real = set()
                for name in song_titles:
                    real |= table.get(name, set())
                if real:
                    return v in real
            return True
        if kind == "achievement":
            v = float(raw)
            return any(isinstance(a, float) and a > 50 and abs(v - a) < 1e-4 for a in allowed)
        if kind == "rating_total":
            # 只认真值表里的总分/B35/B15，不再容忍 14000/14500（那是编造）
            return int(float(raw)) in truth()["totals"]
        # r_value（单曲 R）：**没有曲名就等于无法核对**（B-10）。
        # 旧写法在没有曲名时退化到全局数字集，于是「我打了R285」被放过——
        # 因为 285 在别的歌上确实存在。成绩是绑定到曲目的，脱离曲目的 R 值一律不可信。
        if not has_song:
            # 例外：五位数不可能是单曲 R（单曲 R 上限三百多），那是总 R 的写法。
            # 「舞萌我玩，R 14065 金框」里的 14065 是**真的总分**，按单曲 R 判会误伤。
            return int(float(raw)) in truth()["totals"]
        return int(float(raw)) in {a for a in allowed if isinstance(a, int)}
    except (TypeError, ValueError):
        return True


def _plate_claim(text: str) -> str | None:
    """她自称的段位牌，如果**高于**真值就返回它。"""
    t = _norm_detect(text)
    # 版本牌子（極/将/神/舞舞/覇者）不属于 R 值底色阶梯，见上方 VERSION_PLATE_RE 注释。
    m_ver = VERSION_PLATE_RE.search(t)
    if m_ver:
        return m_ver.group(1) + "牌"
    rank = truth().get("rank")
    if not rank:
        return None
    head = _RANK_HEAD.match(rank)
    real = PLATE_CANON.get(head.group(1), head.group(1)) if head else None
    if real not in PLATE_ORDER:
        return None
    for m in PLATE_RE.finditer(t):
        said = PLATE_CANON.get(m.group(1), m.group(1))
        if said in PLATE_ORDER and PLATE_ORDER.index(said) > PLATE_ORDER.index(real):
            return said
    return None


def find_score_claims(text: str) -> list[str]:
    """返回真值表里对不上的成绩数字（带曲名，便于定位）。"""
    t_all = truth()
    bad = []
    # 跨分句继承的曲名（见下方「曲名跨分句继承」注释）
    song_carry: list = []
    # **先归一化再切分句**（2026-10-23 修 L3-16）。
    # 旧写法先 `_CLAUSE.split(text)` 再逐句 `_norm_detect`，而 `_CLAUSE` 里含逗号，
    # 于是「我打了R1,4065」在归一化之前就被切成「我打了R1」+「4065」——
    # 千分位逗号被当成标点，两半都不成数字，整条放行。
    # 归一化（NFKC + 去千分位）会把逗号并掉，所以顺序必须是「先归一化，后切分句」。
    for clause in _CLAUSE.split(_norm_detect(text)):
        c = clause.strip()
        if not c:
            continue
        plate = _plate_claim(c)
        if plate:
            bad.append(f"plate={plate}")
        hit_songs = [
            (name, allowed) for name, allowed in t_all["songs"].items()
            if len(name) >= 2 and name in _norm_title(c)
        ]
        if not hit_songs:
            # 简称：「病み垢我打了 R285」里的「病み垢」只是「病み垢ステロイド」的前三字。
            # 只认**唯一前缀**，避免「春」这种撞一片。
            cn = _norm_title(c)
            for name, allowed in t_all["songs"].items():
                if len(name) < 3:
                    continue
                if name[:3] in cn:
                    hit_songs.append((name, allowed))
        # 2026-10-23 第三轮：**曲名跨分句继承**。
        # 「フィクサー SSS+，R299」按逗号切成两段，后半段「R299」里没有曲名，
        # 于是 r_value 走「无曲名」分支被判违规——而 299 是这首歌的表内真值。
        # 真实对话里「曲名 + 成绩」被逗号分开是常态，所以把上一句认到的曲名带下来。
        # 只在**本句没认到曲名**时继承，避免一句里换了首歌还沿用上一首。
        if hit_songs:
            song_carry = hit_songs
        elif song_carry:
            hit_songs = song_carry
        allowed = set()
        for _, a in hit_songs:
            allowed |= a
        label = hit_songs[0][0] if hit_songs else ""
        titles = tuple(name for name, _ in hit_songs)
        for kind, raw in _numbers_in(c):
            if _allowed(raw, kind, allowed, bool(hit_songs), titles):
                continue
            bad.append(f"{kind}={raw}" + (f"@{label}" if label else ""))
    return bad


def check(text: str, do_strip: bool = True) -> Report:
    clean, leaks = strip_leaks(text) if do_strip else (_clean_invisible(text), [])
    return Report(
        text=clean,
        leaks=leaks,
        invites=find_invites(clean),
        scores=find_score_claims(clean),
        selfplay=find_self_play_claims(clean),
    )


# ---------------------------------------------------------------- 6. 分层改写
# 2026-10-22 22:5x 新增。判定见 `docs/outbound-guard-verdict.md`。
#
# 为什么不「重生成」：
#   L3 的违规源是**知识缺失**——她手上根本没有表外那首歌的数字，再采样只会换个数字编。
#   L2/L2.5 的违规是**局部短语**，删掉那个分句就够了，整条重来反而丢掉有用信息。
# 所以这里一律做「删违规分句 / 改违规动词」，不请求第二次 LLM。
#
# 分层：
#   1. 删掉违规分句，保留其余
#   2. 删完还成立 → 直接发
#   3. 删完为空/只剩半句 → 用该层专属安全句
#   4. 仍然为空 → 调用方不发（QQ 发空消息是事故）

# 每层的兜底安全句。**必须是她会说的话**，不能是「抱歉我无法回答」这种客服腔。
SAFE_FALLBACK = {
    "invites": "去不了，你看",
    "selfplay": "看你打就行",
    "scores": "记不清了，没特意记",
}

# L2.5 的动词改写：把「我也玩/我在练」换成「看你玩/挺强的」
_SELFPLAY_REWRITE = [
    (re.compile(r"我(?:也|现在|最近|平时|偶尔|以前|就|还)*(?:在)?(?:玩|打|练|搓|上分|开镜)(?:着|过)?"), ""),
]


def _clause_spans(text: str) -> list[tuple[int, int]]:
    """按分句切，返回每段的 (start, end)，分隔符归前一段。"""
    spans, start = [], 0
    for m in _CLAUSE.finditer(text):
        spans.append((start, m.end()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _clause_is_bad(clause: str, carry: str | None = None) -> str | None:
    """这一分句该不该删？返回违规层名或 None。

    `carry` 是「上一句在说哪个游戏」，用于跨分句主语继承（B-7 连带项）。
    """
    if find_invites(clause):
        return "invites"
    if _scan_self_play(clause, carry)[0]:
        return "selfplay"
    if find_score_claims(clause):
        return "scores"
    return None


def _looks_dangling(s: str) -> bool:
    """删完剩下的是不是一个**站不住的残句**（B-6）。

    为什么需要它：`上号，我拉你` 删掉后半句只剩「上号」，`明天机台见啊，别迟到`
    只剩「别迟到」——约定没了，暗示还在，比整条兜底更糟。

    但不能一刀切按长度：`你先开一局，我看着` 删完剩「我看着」，这是**完整回应**
    （有主语 + 实义动词），必须放过。所以判据是「短 + 无主谓」。
    """
    core = re.sub(r"[\s，,。！？!?；;、~～…]+", "", s)
    if not core:
        return True
    if len(core) >= 6:
        return False
    if re.match(r"^[我你他她]", core) and re.search(
        r"(?:看|说|听|想|觉得|知道|懂|在|去|来|行|好|是)", core
    ):
        return False
    # 2026-10-23：**评价性短句**是完整回应，不是残句。
    # 「病み垢我打了 R285，还行吧」删掉前半句后剩「还行吧」——三个字，但它
    # 本身就是在回应，语气完整。旧判据只看「有主语 + 实义动词」，把它当残句
    # 丢掉换成兜底句，等于把一句自然的话改成了敷衍。
    #
    # 但「挺爽的」「稳的」这类**以「的」收尾的定语式评价**不算：它们必须挂在
    # 一个被删掉的对象上才成立，留下来就是在夸一个她没说出口的成绩（审计 B-6 的
    # X-07）。所以先按「的」收尾判残句，再看评价词白名单。
    if core.endswith("的"):
        return True
    if re.match(r"^(?:还|挺|蛮|也|就|倒是|一般|不错|还行|凑合|差不多|有点|好|嗯|行|可以|算了)", core):
        return False
    return True


def degrade(text: str) -> tuple[str, list[str]]:
    """删掉违规分句。返回 (改写后文本, 被删的层名)。

    不重生成——只做确定性的分句删除。调用方拿到空串时**不要发送**。
    """
    kept, dropped = [], []
    # 千分位逗号会骗过 `_clause_spans`：「我打了R1,4065」被切成「我打了R1,」+「4065」，
    # 两半单独看都不是数字，`_clause_is_bad` 判不出违规，整条原样放行（审计 L3-16）。
    # 这里先并掉数字之间的逗号再切分句——被并掉的只是千分位，中文正文不受影响；
    # 而且走到这一步的句子本来就要被改写。
    text = _THOUSANDS.sub("", text)
    spans = _clause_spans(text)
    # L2.5 有个陷阱：「街霸6我也玩，主玩杰米」删掉前一句会留下「主玩杰米」，
    # 后半句本身还在断言她打杰米（只是没带「我」）。所以一旦某句因 selfplay
    # 被删，同条消息里**所有提到她不上手游戏的分句一起删**。
    selfplay_seen = False
    # 跨分句主语继承（B-7 连带项）：「我不打街霸6，但是我会玩」——
    # 违规在后半句，后半句没有游戏名。`_scan_self_play` 会把上一句的游戏带下来，
    # 所以这里也维护一份 carry，逐句传进去。
    carry: str | None = None
    for s, e in spans:
        clause = text[s:e]
        if not clause.strip():
            continue
        layer = _clause_is_bad(clause, carry)
        # 无论这一句删不删，都要更新 carry（「我不打街霸6」这句本身合法，
        # 但它决定了下一句在说哪个游戏）。
        _bad, carry2 = _scan_self_play(clause, carry)
        if carry2:
            carry = carry2
        if layer == "selfplay":
            selfplay_seen = True
        if layer is None and selfplay_seen:
            stripped = clause
            for g in PLAYER_EXEMPT_GAMES:
                stripped = stripped.replace(g, "")
            if any(g in stripped for g in NOT_PLAYER_GAMES):
                layer = "selfplay"
        if layer is None:
            kept.append(clause)
        else:
            dropped.append(layer)
    out = "".join(kept)
    # 删完只剩标点/空白 → 视为空，交给调用方决定发不发
    if not re.sub(r"[\s，,。！？!?；;、~～…]+", "", out):
        out = ""
    else:
        # 删中间句会留下悬空逗号：「…能看出来，」→「…能看出来」
        out = re.sub(r"[\s，,、；;]+$", "", out.strip())
    return out, dropped


def guard(text: str, do_strip: bool = True) -> tuple[str, bool]:
    """一站式出站处理：剥离 → 改写 → 兜底。

    返回 (可发送文本, used_fallback)。
    **文本为空表示不要发。** `used_fallback=True` 表示这条已经不是你原本想说的
    内容（改成了兜底句，或者本来就没有可发正文）。
    """
    report = check(text, do_strip=do_strip)
    if report.ok:
        # 2026-10-23：`used_fallback` 在「剥完为空」时也置 True。
        # 旧行为是 `('', False)`——调用方若只看这个标志，会以为"干净，发吧"，
        # 然后把一条空消息发出去。空串和「没有内容」必须用同一个信号。
        return report.text, report.empty
    fixed, dropped = degrade(report.text)
    if fixed and not _looks_dangling(fixed):
        return fixed, False
    # 全条都是违规（或只剩残句）：用最后命中那一层的兜底句，而不是「无法回答」
    layer = dropped[0] if dropped else (
        "invites" if report.invites else "scores" if report.scores else "selfplay"
    )
    return SAFE_FALLBACK.get(layer or "scores", ""), True


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = check(" ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read())
    print("clean :", r.text)
    print("leaks :", r.leaks)
    print("invite:", r.invites)
    print("scores:", r.scores)
    print("selfpl:", r.selfplay)
    print("ok    :", r.ok)
