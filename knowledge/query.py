#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query the Miruku knowledge database with Chinese-friendly n-gram scoring.

Usage:
  python knowledge/query.py 何意味
  python knowledge/query.py 源石 搓玉 --topic arknights --limit 5
  python knowledge/query.py 三国杀 --json
  python knowledge/query.py 夏玛 --full

Why not rely on FTS only: FTS5 trigram needs >=3 chars, so 2-character
Chinese words (夏玛, 牛奶, 搓玉) would miss. This script scores 2-4 char
n-grams over title/aliases/summary/tags/detail, so short queries work.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "miruku_knowledge.sqlite3")

FIELD_WEIGHTS = {"title": 6.0, "aliases": 5.0, "summary": 4.0, "tags": 3.0, "detail": 1.0}

# 「你会不会打舞萌」这类问自己的问题，容易被曲目条目压过自身条目，
# 所以带第一人称/自身词时给 self 主题一点加权（不是无条件抬高）。
SELF_HINTS = ("你", "我", "自己", "miruku", "咪璐库", "咪露库", "ミルク")
TOPIC_BOOST = {"self": 2.2}

# 查询里直接点名某个主题时，给该主题一点加权，避免被别的主题的高分条目抢走。
# 只是小幅加成（1.6 倍），主题内真正相关的条目依然靠内容分排前面。
TOPIC_HINTS = {
    "touhou": ("东方", "東方", "幻想乡", "幻想郷", "东方project", "thwiki"),
    "vocaloid": ("术力口", "术曲", "ボカロ", "vocaloid", "v家", "初音", "ミク", "镜音", "巡音"),
    "anime": ("番剧", "动画", "动漫", "新番", "孤独摇滚", "芙莉莲", "mygo", "gbc"),
    "vtuber": ("管人", "虚拟主播", "v圈", "vtb", "vtuber", "hololive", "彩虹社", "にじさんじ"),
    "arknights": ("方舟", "粥", "鹰角", "明日方舟"),
    "sanguosha": ("三国杀", "杀"),
    # 注意：主题识别词里**不能写某个条目自己的标题**。
    # 「小男娘」曾经在这里，结果「小男娘」条目靠 1.6 倍自我加权永远压过同主题的
    # 「男娘音」——问「小男娘音怎么练」时，该答的那条排第二。主题词只放
    # 真正代表整个主题的叫法（vrc/vrchat/改模/虚拟形象），不放单个条目名。
    "vrchat": ("vrc", "vrchat", "改模", "虚拟形象", "avatar", "面捕"),
    "maimai": ("舞萌", "maimai", "洗衣机", "机厅", "出勤"),
    "games": ("街霸", "杰米", "斗魂", "海斗", "海克斯", "三角洲", "跑刀",
              "撤离", "塔科夫", "搜打撤", "英雄联盟", "lol", "红温"),
}
TOPIC_HINT_BOOST = 1.6

# 曲目/条目别名里混着一批日常高频词（lxns 的俗称数据本身没做区分）：
# 「忙シー日」的别名有「忙一天」，「Panopticon」的有「学校」，「监狱」同理。
# 这些词在普通闲聊里出现得太频繁，光靠别名覆盖率挡不住
# （「看你忙一天」=13.17 会注入一首歌）。
# 处理办法不是删别名，而是要求查询里同时出现别的语境词才认这条别名。
#
# 入这个集合的门槛是**真实语料词频**（data/chat_content.sqlite3，
# 26,661 条纯文本实测），且逐条看过上下文确认以日常义为主：
#   老师 54、一天 47、衣服 39、学校 33、监狱 16、起床 13、操作 12、
#   朋友 8、软件 6、距离 2、典狱长 3、对面 4、老板 3、高数 8、米饭 4、早八 20
# 全量 8,663 条私聊跑完审计后又补了两个：
#   「关系」——「没关系的」命中《和 OTTO 的关系》14.0
#   「说话」——「怎么不说话」「不说话是吧」命中《说话方式》20.0，
#             而对方只是在抱怨 Miruku 不回话，不是在问她的说话方式
# 「忙日」「龙之日」不在集合里：它们不是自然汉语短语，只可能是曲名俗称，
# 所以单独查询「忙日」仍然照常命中。
GENERIC_ALIASES = {
    # 生活场景
    "学校", "监狱", "监牢", "典狱长", "一天", "忙一天", "又忙一天",
    "忙了一天", "忙碌的一天", "对面", "朋友", "老板", "老师", "衣服",
    "起床", "早八", "高数", "米饭", "距离", "软件", "关系", "说话",
    # 全量审计第二轮补的（都是汉语常用词，只是恰好也是某个条目的别名）：
    #   「我们最后」→《最后的希望》12.0、「有点逆天」→《宙天》11.8、
    #   「热的要死」→《あつすぎの歌》10.0、「室友给我出了个复苏呼吸机」→《呼吸法》10.56、
    #   「刚刚垫排球给我手干红了」→《排球少年》10.56、「双子星×」→《镜音铃连》13.13、
    #   「躲猫猫这种跟技术没关系」→《药屋少女》10.28（别名「猫猫」）、
    #   「井盖都掏了」→《300井》11.47、「aw让大哥」→《KAITO》10.91（别名「大哥」）、
    #   「我白南93」→《GUMI》10.63（别名「93」）、
    #   「狐狸加我QQ好友了」→《QuiQ》10.47（别名「qq」，而这句话在说 QQ 这个软件）。
    "最后", "逆天", "热死了", "呼吸", "排球", "双子", "猫猫", "井盖",
    "大哥", "93", "qq",
    # 游戏/系统里的通用词（几乎任何游戏都有，指向性太弱）
    "操作", "角色", "主线", "活动", "体力", "排位", "单挑", "警察",
    "同步", "消失", "手游", "喝酒", "新手", "上头", "急了", "最强",
    "打架", "无限", "推特", "空格", "武器", "防具", "坐骑",
    # 全量审计第三轮补的（8,663 条私聊里逐条看出来的误命中）：
    #   「这是你的能力」→《全职猎人》10.0（n-gram 撞上「念能力」）
    #   「标准的那种女拳长相」→《形象》10.0（别名「长相」）
    #   「我就喜欢这样」→《喜欢什么》11.0（标题「喜欢什么」含「喜欢」）
    #   「热的要死」→《あつすぎの歌》10.0（别名「热死了」被切成「热死」）
    #   「相信彩虹」→《虹》12.3（别名「彩虹」）
    #   「只能玩玩下落式的」→《Falling》10.13（别名「下落」）
    #   「学校里有家南昌拌粉，四块钱一大碗」→《SILENT BLUE》10.3（别名「四块钱」）
    #   「是不是你电脑断网了」「PCL不用正版也能联机」→《投币与联机》
    #   「要的东西太阴间了」→《阴间武将》
    #   「差点又被无名截了」→《「　」（无名曲）》
    #   「做检测啤酒」→《ZUN 帽与啤酒》（对方在说真的啤酒）
    #   「我吹完头发上你号给你刷钓鱼等级了」→《Player Level》（别名「等级」）
    #   「你昨天晚上是不是去那个郊狼赌场了？」→《New York Back Raise》（别名「赌场」）
    #   「上洛克王国挂机」「手机放着挂机」→《挂机、Bar 和听歌》（对方在说游戏挂机，
    #     不是 VRChat 的 Bar；有「vrc」陪着时仍照常命中）
    #   「看来bug很多啊」→《バグ》
    "能力", "长相", "喜欢", "热死", "彩虹", "下落", "四块钱", "断网",
    "联机", "阴间", "无名", "啤酒", "等级", "赌场", "挂机", "bug",
}

# 通用词别名单独作用时的分数上限，**必须明显低于 min_score=10.0**。
# 留出余量是因为它最后还要过 TOPIC_HINT_BOOST（1.6 倍）这类乘数：
# 7.0 × 1.6 = 11.2 会重新越过阈值，所以封顶写在所有乘数之后。
GENERIC_CAP = 7.0

# 「弱词」：既是圈内叫法、又是汉语常用词，所以**不能**用 GENERIC_ALIASES
# 那套「要求伴随语境词」的门禁——它们本身就是话题，旁边不会有别的语境词。
#   「旋转怎么打」「立绘是什么」「痛包怎么弄」「雷霆的话是什么」「怎么入坑」
# 这些都是真提问，一加语境门禁就全被砍掉（实测 6 个词会杀掉 9 个真提问，
# 只修好 5 个误命中，是净亏）。
# 改用另一条判据：**只有在 clean_query 之后独立成段时才算数**。
# 依据（全量 8,663 条私聊 + 逐条读上下文）：
#   「好像能旋转」      → qn 只有一段「好像能旋转」，旋转粘在句子里 → 不算
#   「并非痛包」        → 同上 → 不算
#   「看到立绘脸红吗」  → 同上 → 不算
#   「我干脆直接入坑邦邦得了」→ 同上 → 不算
#   「什么雷霆封面」    → 「雷霆封面」一段，「雷霆」是定语 → 不算
# 而真提问恰好都被停用词切成独立段：
#   「旋转怎么打」→ [旋转, 打]｜「立绘是什么」→ [立绘]
#   「痛包怎么弄」→ [痛包, 弄]｜「雷霆的话是什么」→ [雷霆, 话]｜「怎么入坑」→ [入坑]
# 注意「入坑看什么」会被切成 [入坑看] 而失效——这是这条规则的已知代价，
# 但「入坑」在真实语料里只出现 1 次且是误命中，宁可漏也不误注入。
#
# 「辉夜」「辉夜姬」也放进这个集合，理由**不同**但机制一样：
# 它们不是日常汉语词，而是常作为更长专有名词的一部分出现——
# 《超时空辉夜姬》是动画，不是东方角色。
#   「你看没看过超时空辉夜姬」→ segs [看, 看, 超时空辉夜姬] → 辉夜姬不独立成段 → 不算
#   「超时空辉夜姬好看吗」    → segs [超时空辉夜姬好看] → 不算
# 而真的在问角色时它一定独立成段：
#   「辉夜姬」→ 26.0｜「辉夜」→ 30.0｜「辉夜姬是谁」→ [辉夜姬, 谁] → 20.0
#   「蓬莱山辉夜」走标题整段 → 31.67
# 代价：「辉夜姬的符卡」这类粘连写法会失效。真实语料里没有这种写法。
#
# 「天爆」进这个集合的理由是**第三种**：它不是日常词，字也常见，但它是
# 「今天」+「爆率」两个词拼接后偶然出现的两字（今[天爆]率）。
#   「今天爆率高会摸回来的」→ qn「今天爆率高/摸回来」，天爆横跨两个词 → 不算
#   「他在打天爆」「我想听天爆」「今天打天爆」→ 天爆紧跟动作词 → 算
# 这一条靠下面 WEAK_VERB_PREFIX 的「紧跟动作词」例外保住，
# 否则「他在打天爆」会被一起打死（实测：只加独立成段时该条会掉到阈值下）。
# 「水平」属于上一条的第四种情况：它是「你什么水平」被 clean_query 砍掉
# 「你／什么」之后**唯一剩下的词**（→ 段落只剩「水平」）。别名无论写成
# 「你什么水平」还是「水平怎么样」，规范化后都比查询长，substring 匹配不上，
# 实测只有 7.0 分（n-gram 封顶）→ 低于阈值 10.0，从不注入。
# 所以补一个两字别名「水平」，同时受这条独立成段门禁约束：
#   「你什么水平」「水平怎么样」「你舞萌水平」→ 段落含独立「水平」→ 认
#   「这节课水平不行」「我水平有限」          → 不独立成段 → 不认
WEAK_ALIASES = {"性格", "旋转", "入坑", "立绘", "痛包", "雷霆",
                "辉夜", "辉夜姬", "天爆", "水平"}

# 弱词的第二个放行条件：**紧跟在一个动作词之后**。
# 「他在打天爆」clean_query 之后是「打天爆」一整段，天爆不独立成段，
# 但它跟在「打」后面，指向是明确的（打/听/放/点/练/看/上/唱/玩/刷/推 + 词）。
# 这一条不放松别的方向：「好像能旋转」的「能」、「并非痛包」的「非」、
# 「看到立绘脸红」的「到」、「干脆直接入坑邦邦得」的「接」都不在集合里。
WEAK_VERB_PREFIX = "打听放点练看上唱玩刷推"


# 「版本牌子」的歧义处理（DS-09，2026-10-26）。
# 极 / 将 / 神 / 舞舞 / 霸者 是舞萌的版本牌子名，但「极」「将」同时是超高频汉字，
# 不能当普通别名（`score()` 里 `len(an) < 2` 也会直接跳过单字别名）。
# 观察到的真实问法：「极和将是什么牌子」→ clean_query 得到「极\x01将\x01牌子」，
# 「极」「将」各自独立成段，任何双语别名（「极牌」）都对不上，于是只命中通用
# 条目 `pai-zi`（「牌子」独立成段），答不出「版本牌子」这条。
#
# 判据：**牌子词独立成段 + 至少一个牌名独立成段**，两个条件缺一不可。
#   「极和将是什么牌子」→ 牌子✓ 极✓ 将✓ → 认
#   「极牌和将牌呢」    → 牌子✗（没有裸「牌子」段）→ 走原别名路径（极牌已有别名，本来就命中）
#   「终于下班了」      → 牌子✗ → 不认
#   「将军」            → 牌子✗ → 不认
#   「将来想做什么」    → 牌子✗ → 不认
# 这样不需要把「极」「将」放进 WEAK_ALIASES（那会让「极其无聊」「极度疲惫」这类
# 独立成段的「极」也参与匹配，反而更危险）。
PLATE_NAMES = ("极", "極", "将", "將", "神", "舞舞", "霸者", "覇者")
PLATE_CONTEXT_WORDS = ("牌子", "牌", "プレート", "plate")
# 触发这条判据时给的分：高于注入阈值 10.0，但要低于「整句正好是标题/别名」的 20.0，
# 因为它依赖两个词共现，比直接叫出名字弱一档。
PLATE_CONTEXT_SCORE = 16.0


def _weak_alias_ok(qn: str, an: str) -> bool:
    """弱词：独立成段，或紧跟动作词。"""
    if an in qn.split(SEP):
        return True
    i = qn.find(an)
    while i >= 0:
        if i > 0 and qn[i - 1] in WEAK_VERB_PREFIX:
            return True
        i = qn.find(an, i + 1)
    return False


def _plate_context_hit(qn: str) -> bool:
    """这句是不是在问「版本牌子」。

    两条判据，**任一成立**：

    ① **牌子词 + 任一个牌名**，都独立成段。
       `clean_query` 已把停用词换成 SEP，所以「极和将是什么牌子」
       → segs = ['极','将','牌子']，「极」「将」各自是完整段；
       而「将军」只有一段，不认；「终于下班了」「将来想做什么」没有牌子词，不认。

    ② **两个及以上牌名同时独立成段**（问区别/比较的常见形态）：
       「极和将有什么区别」→ segs = ['极','将','区别']，没有「牌子」二字，
       但「极」「将」同时出现，指向已经明确。
       要求 **≥2 个** 是硬条件：「终于想通了有什么区别」只有一个「终」（不是牌名），
       「极其无聊有什么区别」只有「极」，都不认。
    """
    segs = set(qn.split(SEP))
    names = [n for n in PLATE_NAMES if n in segs]
    if not names:
        return False
    if any(w in segs for w in PLATE_CONTEXT_WORDS):
        return True
    return len(names) >= 2


# 「水平」这条弱别名有一个上面门禁拦不住的漏口：**对方在自评**。
#   「我水平有限」→ clean_query 砍掉「我／有」→「水平\x01限」→「水平」独立成段 → 认
#   「我水平不行」同理
# 实测 39.6 分，会让 Miruku 把 R 值 14065 掏出来抢话——对方在自嘲自己打得差，
# 这时候她该接对方的话，而不是报自己的成绩。判据用**原始问句**（qn 里「我」已被砍掉，
# 只能回到 q_raw 判断）：主语是第一人称且紧跟「水平」时，这条别名不算。
SELF_ASSESS_PREFIX = ("我水平", "俺水平", "自己水平", "本人水平", "我舞萌水平")


def _self_assess(q_raw: str) -> bool:
    """这句话是在说「我水平怎么样」，不是问 Miruku。"""
    return any(prefix in q_raw for prefix in SELF_ASSESS_PREFIX)

# 只有 n-gram（字面相似）命中、没有任何标题/别名命中时的分数上限。
# 同样必须低于 min_score=10.0，理由与 GENERIC_CAP 一样：
# 字面像不等于在聊这个，它只该帮已在话题内的条目排序。
NGRAM_ONLY_CAP = 7.0

# 出现这些词说明这句话还有别的指向，不是碰巧用到了某个通用词。
# 分三组维护，是为了以后能看清「哪一类语境救回了哪条别名」。
MUSIC_WORDS = ("歌", "曲", "谱", "难度", "好听", "出勤", "机厅", "bpm",
               "音游", "maimai", "舞萌", "解谜", "解密", "打歌", "rating")
# 语境词一律要求 **2 字以上**。单字语境词会把门禁开得到处都是：
# 「关」曾让「没关系的」通过（→《和 OTTO 的关系》14.0），
# 「本」「卡」「队」「抽」「练」「打」「玩」「局」同理
# （本来/卡住/排队/抽烟/练习/打扫/玩手机）。
# 实测：把门禁整个关掉，全量 8,663 条私聊里只有 1 条命中消失——
# 说明门禁本来就几乎不影响召回，那它就该严，而不是松。
GAME_WORDS = ("上分", "版本", "更新", "活动", "英雄", "武将", "干员",
              "卡池", "排位", "对局", "副本", "关卡", "配队", "抽卡",
              "练级", "打歌", "开黑", "组队")
VRC_WORDS = ("模型", "改模", "vrc", "vrchat", "avatar", "皮肤", "材质",
             "面捕", "追踪", "unity", "booth", "avatar")
CONTEXT_WORDS = MUSIC_WORDS + GAME_WORDS + VRC_WORDS


def _generic_alias_ok(q_raw: str) -> bool:
    """通用词别名：只有查询里同时出现别的语境词才认。"""
    return any(w in q_raw for w in CONTEXT_WORDS)

PUNCT = re.compile(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()\[\]【】<>《》~～…\-—_/\\|]+")

# 剩下的装饰符号（曲名里的 ◆ ★ × ✕ 等）也要清掉，否则「Xaleid◆scopiX」
# 永远匹配不上用户打的「Xaleid scopiX」。只保留中日文、ASCII 字母数字和少数连接符。
NON_WORD = re.compile(r"[^0-9a-z\u4e00-\u9fff\u3040-\u30ffー・]+")

# 聊天里图片/表情/语音在文本里是「[图片:0392...jpg]」这种占位符。
# 不清掉的话，占位符里的十六进制串会被当成检索词（「39」命中初音未来的别名），
# 于是每张图都会注入一条不相干的知识——正是「看见表情包就想描述」的成因之一。
#
# 全量审计又抓到一个漏网的：`[闪照]请使用新版手机QQ查看闪照。`
# 原来不在名单里，于是这 8 条一模一样的系统提示全部命中《QuiQ》
# （靠别名「qq」）。名单要覆盖 QQ/NapCat 会替我们塞进正文的所有占位标签。
PLACEHOLDER = re.compile(
    r"\[(?:图片|表情|语音|视频|文件|动画表情|回复|引用|@|CQ|闪照|位置|链接|"
    r"名片|视频通话|戳一戳|窗口抖动|音乐分享|小程序|合并转发|群公告|"
    r"红包|转账|礼物|打卡|签到)[^\]]*\]", re.I)

# 兜底：方括号里**没有任何汉字**的，一律当资源令牌摘掉
# （[CQ:image,file=xxx]、[abc.jpg]、[123456]、[1.2MB]）。
# 宁可多摘一点，也不要把哈希串、尺寸、文件大小当检索词。
PLACEHOLDER_ASCII = re.compile(r"\[[^\]\u4e00-\u9fff]*\]")

# 疑问句/语气词会稀释检索，先去掉再取 n-gram
STOP_PHRASES = [
    "为什么", "是不是", "会不会", "有没有", "能不能", "可不可以", "什么", "怎么",
    "一下", "告诉", "请问", "知道", "觉得", "可以", "我们", "你们", "他们",
    "吗", "呢", "啊", "吧", "呀", "哦", "嗯", "嘛", "啦", "哈",
    "你", "我", "他", "她", "它", "的", "了", "是", "在", "有", "会", "要",
    "就", "都", "也", "和", "与", "或", "不", "没", "这", "那", "个", "些", "着", "过",
    # 「还」是纯功能词，但漏删它会**掐死单字条目**：真实语料里
    # 「还在粥吗」「还在adx吗」「还在zmd吗」「你还在改模吗」共 60+ 处，
    # 删掉「在/吗」后剩「还\x01粥」，两字不触发单字回落，单字标题「粥」只能
    # 走「查询是标题的一截」那支拿 8.0，卡在 10.0 线下——而「在粥吗」是 26.4。
    # 差一个「还」字就翻面。删掉后「还在粥吗」21.0、「你还在改模吗」49.6。
    # 不会误伤：「还好」「还有呢」「还是算了」clean 后为空或整句保留，仍不注入。
    "还",
]


# 停用词被删掉后，两侧的词不能直接粘在一起。
# 「7ref 和 KALEIDXSCOPE 有关系吗」删掉「和」「有关系吗」之后变成
# 「7refkaleidxscope」，于是「7ref」的右侧紧贴字母 k、「kaleidxscope」的左侧
# 紧贴 f，两边都过不了 ASCII 词边界检查，整条查询返回空——
# 而这两个词恰恰是 KALEIDXSCOPE 解谜里最常一起被问到的两个名字。
# 用一个 normalize() 永远不会产出的分隔符顶替被删掉的位置：
# 它既不是 ASCII 字母数字（词边界因此成立），也不属于任何标题/别名（不会误命中）。
SEP = "\u0001"


def clean_query(q: str) -> str:
    text = normalize(q)
    for phrase in STOP_PHRASES:
        text = text.replace(phrase, SEP)
    # 折叠分隔符：连续多个停用词只留一个
    while SEP + SEP in text:
        text = text.replace(SEP + SEP, SEP)
    # 两端的停用词（「你喜欢什么」→「喜欢」）不能留下分隔符，
    # 否则「整句就等于这个别名」的判断会全部失效。
    # 分隔符只保留在**两个内容词之间**，它的作用仅限于让 ASCII 词边界成立。
    text = text.strip(SEP)
    if not text:
        # 整句都是疑问词/语气词（「为什么？」「嗯嗯」「哈？」），
        # 说明这句话里**没有任何内容词**，不该去检索。
        # 原来这里回落到 normalize(q)，于是「为什么」三个字被当成检索词，
        # 命中《春日影 / 为什么要演奏春日影》拿 12.0——对方只是在问为什么。
        # 空串让 score() 直接返回 0.0。
        return ""
    # 只剩一个字（「粥」「鸟」「虹」）时回落到原始串：单字查询由 score() 的
    # short 分支按「精确等于标题/别名」处理，是圈内真叫法。
    return text if len(text) >= 2 else normalize(q)


# 「问成绩」的整句疑问部分，先摘掉再匹配。
# 起因（DS-06 的 F1）：「QUEEN 多少分」clean 后是「queen多少分」（「多少分」不在
# STOP_PHRASES 里），别名「queen」只能靠包含命中，覆盖率 5/8 打折到 8.75，
# 卡在 10.0 阈值下面——而同一句只问「QUEEN」就是 20.0。差一个「多少分」就翻面。
# 实测三首她**真有成绩**的曲子在自然问法下全部静默不注入：
#   QUEEN 多少分 9.97 / Cthugha 多少分 9.92 / 不思議の国のクリスマス 多少分 7.00
# 只放进宽松形式（loose_query），**不动 clean_query**：后者被 120 条回归用例
# 依赖，改它等于重标定整条链路。
SCORE_INTENT_PATTERNS = [
    re.compile(r"多少分(?!钟|秒|时)"),
    re.compile(r"什么评级"),
    re.compile(r"多少r"),
]


def loose_query(q: str) -> str:
    """比 clean_query 更宽松的形式：只摘多字疑问词，**保留单字停用词**。

    起因（DS-06 的 F1 第二条根因）：单字停用词里有「不」「没」「着」「过」这种
    会出现在**曲名/条目名中间**的字。clean_query 一律删掉，于是
        「不思議の国のクリスマス 多少分」→「思議の国のクリスマス多少分」
    别名「不思議の国のクリスマス」再也匹配不上，只剩 n-gram 7.0。
    而这首她在 b50 里真有成绩（MASTER 13.3，SSS，R288）。

    这里只做「删多字疑问词 + 删成绩问法」，单字一个不删，曲名因此保持完整。
    它只在 clean_query 匹配不上时作为**兜底**（见 score() 的别名分支），
    不替代 clean_query，所以不会重新打开「学校」「监狱」这类日常词误命中。
    """
    text = normalize(q)
    for phrase in STOP_PHRASES:
        if len(phrase) > 1:
            text = text.replace(phrase, SEP)
    for pat in SCORE_INTENT_PATTERNS:
        text = pat.sub(SEP, text)
    while SEP + SEP in text:
        text = text.replace(SEP + SEP, SEP)
    return text.strip(SEP)


def normalize(text: str) -> str:
    return _normalize_cached(str(text or ""))


@lru_cache(maxsize=8192)
def _normalize_cached(text: str) -> str:
    text = PLACEHOLDER.sub(" ", text)
    text = PLACEHOLDER_ASCII.sub(" ", text)
    text = PUNCT.sub("", text).lower()
    # 再清掉剩下的符号：曲名里常有 ◆ ★ × 这类装饰字符
    # （「Xaleid◆scopiX」不清的话，查询「Xaleid scopiX」永远匹配不上标题）。
    # 必须先 lower 再清，否则大写字母会被这条正则整个删掉。
    return NON_WORD.sub("", text)


def _word_boundary_at(needle: str, haystack: str, i: int) -> bool:
    """haystack[i:i+len(needle)] == needle，且两侧不是 ASCII 字母数字。"""
    before = haystack[i - 1] if i > 0 else ""
    after = haystack[i + len(needle)] if i + len(needle) < len(haystack) else ""
    return not (before.isascii() and before.isalnum()) and \
           not (after.isascii() and after.isalnum())


def _ascii_word_in(needle: str, haystack: str) -> bool:
    """needle 是否作为独立词出现在 haystack 里（两侧不能是 ASCII 字母数字）。

    两侧都要查：只查字母的话，查询「13」会在「135秒」里命中（数字也是词的一部分），
    查询「lol」会在「hololive」里命中。中文词不需要这道检查，因为中文没有词边界。
    """
    start = 0
    while True:
        i = haystack.find(needle, start)
        if i < 0:
            return False
        if _word_boundary_at(needle, haystack, i):
            return True
        start = i + 1


def _needs_boundary(needle: str) -> bool:
    """纯 ASCII 的短串才需要词边界；中文串没有词边界可查。"""
    return needle.isascii()


def _contains(needle: str, haystack: str) -> bool:
    """needle 是否出现在 haystack 里；ASCII 串要求词边界。

    「13」不该在「135秒」里命中，「lol」不该在「hololive」里命中。
    """
    if not needle or not haystack:
        return False
    if needle not in haystack:
        return False
    if not _needs_boundary(needle):
        return True
    return _ascii_word_in(needle, haystack)


def _pick_non_overlapping(bonuses: list[tuple[float, int, int]]) -> float:
    """同一段查询文字只计一次分。

    起因：「小男娘音怎么练」里，「小男娘」这条的 title、别名「小男娘」、
    别名「男娘」三段全部落在查询的同一段文字上，叠了三次分（60.48），
    把真正该回答的「男娘音」（38.08）压到第二。
    一条消息里提到一个词，不该因为条目自己写了三种叫法就被算成三次。
    做法：按分值从高到低贪心取，区间不重叠的才累加——
    真正分开提到的两个词（「方舟」和「源石」）仍然各自计分。
    """
    total = 0.0
    taken: list[tuple[int, int]] = []
    for value, start, end in sorted(bonuses, key=lambda b: -b[0]):
        if any(start < t_end and t_start < end for t_start, t_end in taken):
            continue
        taken.append((start, end))
        total += value
    return total


def grams(q: str) -> list[str]:
    q = normalize(q)
    if not q:
        return []
    if len(q) == 1:
        return [q]
    out = set()
    for size in (2, 3, 4):
        if size > len(q):
            break
        for i in range(len(q) - size + 1):
            out.add(q[i:i + size])
    return sorted(out, key=lambda s: (-len(s), s))


def load_entries(db_path: str, topic: str | None) -> list[dict]:
    if not os.path.exists(db_path):
        # DS-06 的 F4：这里原来 raise SystemExit，而 SystemExit 是 BaseException，
        # 运行期插件的 `except Exception` 接不住——库文件在 TOCTOU 窗口里消失时，
        # 整个事件循环会被带走（探针第一版真的被它终结了整个进程）。
        # 换成普通异常，由调用方按「检索失败不拖垮回复」处理。
        raise RuntimeError(
            f"数据库不存在：{db_path}（先跑 knowledge/build_knowledge_db.py）"
        )
    # DS-06 的 F7：损坏库时 con.execute 抛错，con.close() 走不到，
    # 每个请求漏一个连接/文件句柄（Windows 上表现为临时目录删不掉，
    # PermissionError: [WinError 32]）。用 try/finally 兜住。
    con = sqlite3.connect(db_path)
    try:
        con.row_factory = sqlite3.Row
        sql = "SELECT * FROM entries"
        params: tuple = ()
        if topic:
            sql += " WHERE topic = ?"
            params = (topic,)
        rows = [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()
    for r in rows:
        for key in ("aliases", "tags"):
            try:
                r[key] = json.loads(r.get(key) or "[]")
            except json.JSONDecodeError:
                r[key] = []
    return rows


def score(entry: dict, q: str) -> float:
    qn = clean_query(q)
    # 宽松形式：保留单字停用词，只摘多字疑问词与成绩问法（理由见 loose_query）。
    # 只作别名匹配的兜底，权重计算仍以 qn 为主。
    ql = loose_query(q)
    q_raw = normalize(q)
    total = 0.0
    gs = grams(qn)
    if not gs:
        return 0.0
    # 日常词别名要在**两条路径**上一起挡：别名加成路径（下面的 GENERIC_ALIASES 分支）
    # 和 n-gram 路径。上一轮只挡了前者，结果「今天忙一天了，晚上想打舞萌」里
    # 「忙一天」被拆成 天忙一天/忙一天/一天/天忙一/忙一/天忙 六个 gram，
    # 各在别名里撞一次（6×5.0），除以 27 得 1.15，加别名封顶 7.0 得 8.15，
    # 再乘 maimai 主题加权 1.6 = **13.04**，照样注入《忙シー日》。
    # 做法：没有音乐语境词时，把日常词别名从 n-gram 的比对文本里摘掉。
    # 不删条目里的别名本身——「忙日」单独查仍然可用。
    alias_list = entry["aliases"]
    if not _generic_alias_ok(q_raw):
        alias_list = [a for a in alias_list if normalize(a) not in GENERIC_ALIASES]
    alias_text = " ".join(alias_list)
    fields = {
        "title": entry["title"],
        "aliases": alias_text,
        "summary": entry["summary"],
        "tags": " ".join(entry["tags"]),
        "detail": entry.get("detail", ""),
    }
    # 单字查询（「行」「好」「粥」）只认**精确等于**标题或别名的情况。
    # 中文单字在任何条目里都能撞到：「行」会同时命中「三角洲行动」「砂之行星」
    # 「西行寺幽幽子」。但「粥」「鸟」「虹」「乐」「⑨」这类单字是圈内真叫法，
    # 全判 0 会漏掉真话题，所以保留精确匹配，只砍掉子串和 n-gram 路径。
    short = len(qn.replace(SEP, "")) < 2
    # 覆盖率、占比这类「长度比」必须用**去掉分隔符后的实际字数**。
    # 分隔符只是为了让 ASCII 词边界成立，它不是内容，不能算进分母：
    # 否则「墓守\x01歌\x01样」会被算成 6 个字，别名「墓守」的覆盖率从 2/4 掉到 2/6，
    # 真在聊这首歌时反而不注入了。
    qlen = len(qn.replace(SEP, ""))
    # 纯数字（「13」「88」「666」）不评分：数字在真实聊天里几乎都是语气、层数、
    # 次数、时间，不是曲名。「13」曾经命中「等级与等级值」的别名「13+」拿 15 分，
    # 「88」命中暗号条目。带文字的数字（「300井」「135秒」「88boy」）不受影响。
    if qn.isdigit() and len(qn) <= 3:
        return 0.0
    # clean_query 之后整句只剩一个日常词（「我也喜欢你」→「喜欢」、
    # 「没关系的」→「关系」、「你不说话」→「说话」）时，这条消息里**没有别的
    # 内容词**，任何条目都不该被它触发。
    # 前面几轮只挡了「别名/标题**是**日常词」的方向，没挡「查询本身**就是**
    # 日常词」的方向——结果「我也喜欢你」靠标题《喜欢什么》拿到 8.0，
    # 再乘 self 主题加权 2.2 = 17.6，直接注入。
    # 例外：原始查询**整句就等于**这条的标题或别名时照常算——
    # 「你喜欢什么」clean 之后也是「喜欢」，但它本来就是《喜欢什么》的别名，
    # 不能因为 clean_query 把修饰词删了就当成日常词闲聊。
    if qn in GENERIC_ALIASES and not _generic_alias_ok(q_raw):
        raw_names = {normalize(entry["title"])}
        raw_names.update(normalize(a) for a in entry["aliases"])
        if q_raw not in raw_names:
            return 0.0
    # 日常词也要在 n-gram 路径上挡一次。上一轮只挡了别名路径，结果
    # 「怎么操作都不知道」靠 tags 里的「操作」拿 16.0，
    # 「没关系的」靠标题里的「关系」拿 14.0——同一个日常词换了条路照样进来。
    # 判断对象是 gram 本身：gram 是日常词且没有语境词陪着，就不让它计分。
    generic_gram_ok = _generic_alias_ok(q_raw)
    if not short:
        for gram in gs:
            # 日常词 gram 在没语境词时整条不计分。注意判断的是 **gram 本身**
            # 是否就是那个日常词，而不是它包含日常词——
            # 「出勤迟到」里含「出勤」，但它不是日常词，不该被误伤。
            if not generic_gram_ok and gram in GENERIC_ALIASES:
                continue
            boundary = _needs_boundary(gram)
            # 两字符的纯 ASCII gram（「ap」「fc」「vr」「qq」）只有在整句就是它时
            # 才参与 n-gram 计分。这类缩写太短，混进别的话题里必然误伤：
            # 「ap狗头」是英雄联盟的 AP 出装，却命中《AP / FC》10.83。
            # 整句就是「ap」「fc」（「我ap了」clean 之后就是「ap」）时照常命中。
            if boundary and len(gram) < 3 and qn != gram and not generic_gram_ok:
                continue
            for field, text in fields.items():
                hay = normalize(text)
                # n-gram 也要守词边界：查询「lol」拆出的 2 字 gram「lo」「ol」
                # 会整个钻进「hololive」，把 hololive 顶到 16 分。
                # 中文 gram 不受影响（没有词边界可查）。
                if boundary and not _ascii_word_in(gram, hay):
                    continue
                if gram in hay:
                    total += FIELD_WEIGHTS[field]
        total /= max(1, len(gs))
    # 正向：查询就是标题/别名，或标题/别名是查询的一部分（如「你会不会打舞萌」包含「会不会打舞萌」）
    title_n = normalize(entry["title"])
    bonuses: list[tuple[float, int, int]] = []
    # 通用词别名本次是否参与过计分（用来决定要不要在最后封顶）
    used_generic = False
    # 是否有非通用词（真叫法）命中过。有真命中就不封顶——
    # 「出勤」是真叫法，「忙一天」不是，两者同时出现时该按真叫法算。
    strong_hit = False

    def add(value: float, needle: str, hay: str | None = None) -> None:
        """把 needle 在 hay（默认 qn）里的首次合法出现记成一段（start, end）。"""
        haystack = qn if hay is None else hay
        if not needle:
            return
        boundary = _needs_boundary(needle)
        start = 0
        while True:
            i = haystack.find(needle, start)
            if i < 0:
                return
            if not boundary or _word_boundary_at(needle, haystack, i):
                bonuses.append((value, i, i + len(needle)))
                return
            start = i + 1

    if qn and title_n:
        if qn == title_n:
            bonuses.append((20.0, 0, len(qn)))
        elif len(title_n) >= 2 and _contains(title_n, qn):
            # 弱词标题（「性格」）**不走这条分支**。
            # 「光是看外貌和性格也能看出来」把「性格」切成独立一段，
            # 光靠「独立成段」挡不住——它是在陈述别人的性格，不是在问 Miruku 的性格。
            # 而真提问 clean_query 之后正好只剩标题本身：
            # 「你什么性格」「我什么性格」→ qn = 「性格」→ 走上面的 qn == title_n（20.0 × 2.2）。
            # 这里跳过标题分后，n-gram 单靠自己也过不了 NGRAM_ONLY_CAP。
            if title_n in WEAK_ALIASES:
                pass
            else:
                # 标题出现在查询里，给 15.0：**必须高于别名的上限 14.0**。
                # 起因：「小男娘音怎么练」里「男娘音」是标题（该答这条），
                # 但「小男娘」既是另一条的标题、又是 vrchat 的主题识别词，
                # 走别名分支拿满 14.0，把真正的标题（10.0）压到第二。
                # 一个词被写成条目标题，比被写成别名更能说明"问的就是它"。
                add(15.0, title_n)
                # 中文是中心词在后：同样长度的两个标题命中同一段文字时，
                # 结束位置更靠后的那个才是被问的东西。
                # 「小男娘音怎么练」里「小男娘」(0-3) 与「男娘音」(1-4) 等长，
                # 但「男娘音」结束得更靠后，是中心词，应该排第一。
                # 只加最多 0.5 分，纯粹用来打破平局，不改变任何阈值附近的判定。
                i = qn.find(title_n)
                while i >= 0 and not (
                        not _needs_boundary(title_n) or _word_boundary_at(title_n, qn, i)):
                    i = qn.find(title_n, i + 1)
                if i >= 0 and qlen > 1:
                    total += 0.5 * (i + len(title_n)) / qlen
        elif qlen >= 2 and _contains(qn, title_n):
            # 查询只是标题的一截。这里必须按**占比**给分，不能给固定分。
            # 起因（全量 8,663 条私聊跑出来的误命中）：
            #   「为什么？」  → 《春日影 / 为什么要演奏春日影》
            #   「没关系的」 → 《和 OTTO 的关系》
            #   「没体力了」 → 《谱面属性（物量·技巧·体力）》
            #   「会了就容易了」→《夜に駆ける（容易混淆）》
            # 这四个词都是 2–3 字的日常词，恰好是某条标题里的一截。
            # 原来固定给 8.0，加上 n-gram 的 6.0 就是 14.0，全部越过阈值。
            # 现在按 len(qn)/len(title_n) 打折，并要求覆盖一半以上才算命中：
            # 「为什么」3/11=27% → 0 分；而「300井」这种真的在说那首歌的
            # 短查询仍能从别名和 n-gram 路径拿到分。
            # 两个门禁都是必须的：len(qn) >= 2 挡单字（「行」命中「三角洲行动」），
            # _contains 挡 ASCII 子串（「13」命中「封焔の135秒」、「lol」命中「hololive」）。
            cover = qlen / max(1, len(title_n))
            if cover >= 0.5:
                bonuses.append((8.0, 0, len(qn)))
        else:
            # 标题写成「A / B」的，A 和 B 是并列叫法，任一出现在查询里就算命中标题。
            # 否则「方舟的300井」只会命中「明日方舟」，「300 井 / 吃井」那条反而排不上。
            for part in re.split(r"[/／|｜]", entry["title"]):
                pn = normalize(part)
                if len(pn) < 2:
                    continue
                # 这条分支原来直接 `pn in qn`，两个门禁都没有：
                #   「ap狗头」→《AP / FC》10.0（「AP」是英雄联盟的 AP 出装）
                #   「还有ap小炮」→ 同上
                # 所以补上 _contains（ASCII 词边界）和「短 ASCII 只认整句」。
                if pn.isascii() and len(pn) < 3 and qn != pn:
                    continue
                if pn in GENERIC_ALIASES and not _generic_alias_ok(q_raw):
                    continue
                # 弱词也要在这一支上守「独立成段」：
                # 「并非痛包」→ qn =「非痛包」，痛包粘在句子里 → 不算。
                if pn in WEAK_ALIASES and not _weak_alias_ok(qn, pn):
                    continue
                if _contains(pn, qn):
                    add(10.0, pn)
                    break

    # DS-09：版本牌子的语境内判据（见 PLATE_NAMES / _plate_context_hit 定义处）。
    # 「极和将是什么牌子」这类问法里，「极」「将」被 clean_query 拆成独立段，
    # 任何双语别名（"极牌"）都对不上，只能靠这条补充。
    # **只对 ban-ben-pai-zi 这条生效**，不改变其它条目的评分路径。
    if entry.get("slug") == "ban-ben-pai-zi" and _plate_context_hit(qn):
        total += PLATE_CONTEXT_SCORE
        return total

    for alias in entry["aliases"]:
        an = normalize(alias)
        if not an or len(an) < 2:
            continue
        # 别名本身带第一人称/语气词（「你打舞萌吗」「你几岁」「你唱歌吗」）时，
        # 用 normalize 后的形式和 clean_query 后的查询比**永远对不上**——
        # clean_query 把查询里的「你」「吗」删掉了，别名里的却还留着。
        # 后果（真实语料 + 手工验证）：来世问「你打舞萌吗」，self 条目只能靠
        # n-gram 拿 7.0，被《"打舞萌会电我"》38.4 压死——她拿到的是「打舞萌伤身」
        # 这个梗，而不是自己的水平。同理「你几岁」「你唱歌吗」「你住哪」全部只有 7.0。
        # 这里补一条：**别名的 clean 形式与 clean 后的查询完全相同**，也算整句命中。
        # 值取 20.0（与「查询正好等于标题」同档）：两者都是「整句就是在问这一条」，
        # 而别名比标题更具体（「你打舞萌吗」比「会不会打舞萌 / 什么水平」更像人话）。
        #
        # **只对 self 主题生效**，这一点是必须的。self 的别名写成人话问句
        # （「你打舞萌吗」「你几岁」），clean 之后仍然是个明确的指向；
        # 其他主题的别名是名词叫法，clean 之后往往退化成一个常用词：
        #   「有格调」→「格调」→「你是格调」「格调是什么」全被带进来（Λzure Vixen 25.0）
        #   「真的假的」→「真/假」→ 闲聊里的「真的假的」注入《会赢的》20.0
        #   「什么意思」→「意思」→ 闲聊里的「什么意思」注入《何意味》29.0
        # 这三个都是全量审计里新冒出来的误命中，加这条限制后消失。
        # 门禁照旧：clean 之后退化成日常词/弱词的别名不算。
        ac = clean_query(alias)
        # ac 用的是 clean_query（保留 SEP \x01），而 qn 是 normalize 之后（SEP 被删）。
        # 于是**别名中间夹着停用词的，这条永远对不上**：
        #   「你街霸6什么段位」→ clean「街霸6\x01段位」/ normalize「街霸6段位」
        #   而 ac 永远是「街霸6\x01段位」≠ qn → 拿不到 20.0，只剩 n-gram 的 7.0，
        #   低于 10.0 注入阈值 → 「答自己段位」这条知识根本进不了上下文。
        # 修法：比较前先把 ac 也 normalize 一遍。`ac != an` 的守卫保留原样（防重复计分）。
        # 两侧都再比一次 normalize 形式：qn 是 clean_query（保留 SEP），
        # 若别名与查询的**停用词位置**不同（「你街霸6什么段」vs「你街霸6什么段位」），
        # clean 形式就对不上，normalize 形式还能对上。两种都比，缺一不可。
        # b50 主题也放行，理由与 self 相同但更窄：那里的别名全是「你打过14吗」
        # 「打过哪些歌」这种问句，clean 之后只剩「打/14」「打/哪/歌」，
        # 不含任何一个能独立指代别的东西的常用词，退化风险不成立。
        # 名字类条目（曲名）不在此列——它们的别名本来就是名词，仍只走原路径。
        alias_clean_hit = (
            entry.get("topic") in ("self", "b50") and bool(ac) and ac != an
            and (qn == ac or normalize(qn) == normalize(ac))
        )
        if alias_clean_hit and ac in GENERIC_ALIASES and not _generic_alias_ok(q_raw):
            alias_clean_hit = False
        if alias_clean_hit and ac in WEAK_ALIASES and not _weak_alias_ok(qn, ac):
            alias_clean_hit = False
        # 两字符的纯 ASCII 别名（「VR」「xx」「QZ」）只认**整句就是它**。
        # 这类别名太短，随便混进一句话里都能撞上：
        # 「上VR？」→《VirtuaReal》10.13（对方说的是要上 VRChat），
        # 「白xx要上了」→《Xaleid◆scopiX》10.63（「xx」是那条目的别名）。
        # 整句就是「VR」「xx」时仍照常命中——那时候指向是明确的。
        if an.isascii() and len(an) < 3 and qn != an:
            continue
        # 弱词别名必须**独立成段**（或紧跟动作词）才算数（理由见 WEAK_ALIASES 定义处）。
        if an in WEAK_ALIASES and not _weak_alias_ok(qn, an):
            continue
        # 「我水平有限」这类自评句：独立成段这条门禁拦不住（见 _self_assess 注释）。
        if an == "水平" and _self_assess(q_raw):
            continue
        # 日常词别名（学校/监狱/忙了一天/老师…）必须在查询里伴随音乐语境词。
        # 这道门禁要拦在「完全相等」分支**之前**：上一轮只拦了 an in qn，
        # 结果单说一句「忙了一天」qn == an 走捷径拿满 14 分，直接注入《忙シー日》，
        # 「学校」「监狱」「典狱长」同理（各 20.0）。
        if an in GENERIC_ALIASES and not _generic_alias_ok(q_raw):
            continue
        if an in GENERIC_ALIASES:
            used_generic = True
        if alias_clean_hit:
            bonuses.append((20.0, 0, len(qn)))
            strong_hit = True
        elif qn == an:
            # 通用词别名整句就是它（「忙了一天」「88」「13」）也封顶 7.0：
            # 「88」是「拜拜」，「13」是随便一个数字，都不该单独触发注入。
            # 通用词只能帮已经在话题内的条目排序，不能自己把话题带进来。
            bonuses.append((7.0 if an in GENERIC_ALIASES else 14.0, 0, len(qn)))
            if an not in GENERIC_ALIASES:
                strong_hit = True
        elif (an in qn) or (
            an in ql and len(an) >= 3 and len(ac.replace(SEP, "")) >= 3
        ):
            # 别名只覆盖查询一部分时按覆盖度打折。
            # 舞萌曲目有一堆生活化俗称（Panopticon 的别名里有「学校」），
            # 不打折的话「学校对面的」这种普通闲聊会注入一首歌的知识。
            # 例外：别名本身就是该主题的识别词（「方舟」「出勤」），
            # 那说明用户真在聊这个主题，按满分算。
            #
            # `base` 是这条别名实际匹配上的文本：优先 clean 形式，匹配不上才用
            # 宽松形式（保留单字停用词）。兜底那条只接受 **3 字以上、且 clean 之后
            # 仍有 3 个字以上**的别名：单字停用词会出现在曲名中间
            # （「不思議の国のクリスマス」的「不」），删掉就永远匹配不上；
            # 但「真的假的」clean 之后只剩「真/假」，回到宽松形式里会重新注入
            # 《会赢的》——它就是靠这条被挡掉的。
            if an in ql and (an not in qn or an in ql.split(SEP)):
                # 宽松形式里别名**独立成段**（或 clean 形式里根本没有它）时用它算覆盖：
                # 「QUEEN 多少分」的 clean 形式是「queen多少分」，别名只能拿 5/8 打折；
                # 宽松形式把「多少分」摘掉后是「queen」，整段命中，该给满分。
                base = ql
            else:
                base = qn
            qlen_b = len(base.replace(SEP, ""))
            if an in TOPIC_HINTS.get(entry.get("topic") or "", ()):
                value = 14.0
            else:
                # 覆盖率折扣：别名只覆盖查询的一部分时按比例打折。
                # 舞萌曲目有一堆生活化俗称（Panopticon 的别名里有「学校」），
                # 不打折的话「学校对面的」这种普通闲聊会注入一首歌的知识。
                #
                # 下限 0.7：clean_query 会删掉语气词和疑问词，
                # 「墓守这歌怎么样」被压成「墓守歌样」，2/4 的折扣会把真正的主题
                # 压到阈值以下（9.0 < 10.0）。
                # 注意不能改成「覆盖不足 1/3 就不给下限」——那样
                # 「闲鱼买模型靠谱吗」（「闲鱼」覆盖 2/7）和
                # 「今天忙一天了，晚上想打舞萌」（「舞萌」覆盖 2/11）都会被压到阈值下，
                # 真正在聊的话题反而不注入。
                # 覆盖率低的日常词别名由 GENERIC_ALIASES 单独挡（见上），
                # 不靠这里的折扣。
                # 别名**整段**落在查询里（「7ref 和 KALEIDXSCOPE 有关系吗」里的
                # 「7ref」「kaleidxscope」各自是一整段）按满分算。
                # 这是「分开提到的两个词各自计分」的另一种形态：clean_query
                # 删掉停用词后用 SEP 隔开，所以「整段等于别名」比「出现在查询里」
                # 更精确——它排除了「别名只是长句里的一截」这种情况。
                # 没有这条，「7ref 和 KALEIDXSCOPE 有关系吗」两个词各只得 9.8 分，
                # 双双卡在 10.0 阈值下面，同时问两个词反而一个都不注入。
                if an in base.split(SEP):
                    value = 14.0
                else:
                    value = 14 * max(0.7, len(an) / qlen_b)
            if an in GENERIC_ALIASES:
                # 通用词别名即使有语境词陪着，也**封顶 7.0**（低于 10.0 阈值）。
                # 「今天忙一天了，晚上想打舞萌」里有「舞萌」这个语境词，
                # 门禁放行后「忙一天」按 14 分算，直接注入《忙シー日》——
                # 对方在说自己忙，却收到一首歌的知识。
                # 一个日常词永远不该**单靠自己**触发注入；它只能帮已在话题内的条目排序。
                value = min(value, 7.0)
            else:
                strong_hit = True
            add(value, an, base)
    # tags 是人工维护的主题描述词。「整句查询**正好等于**一个 3 字以上的 tag」
    # 是一条独立证据：闲聊里不会有人恰好只打出「英雄联盟」这四个字而不在说它。
    # 加这条是因为 DS-02 的回归用例「英雄联盟」原本期望注入，而库里没有
    # 「英雄联盟」条目（只有斗魂竞技场、海克斯大乱斗两条，tag 都是「英雄联盟」），
    # 它只能靠 n-gram 命中 tags，被 NGRAM_ONLY_CAP 封到 7.0 后变空。
    # 门槛取 3 字：2 字 tag（「街霸」「关系」「评价」）在真实语料里是日常词，
    # 全量 8,663 条私聊里，整句等于 3 字以上 tag 的只有「三角洲」两条，
    # 都是真命中（三角洲行动）。
    tag_names = {normalize(t) for t in entry["tags"]}
    if len(q_raw) >= 3 and q_raw in tag_names:
        bonuses.append((8.0, 0, len(qn)))
        strong_hit = True
    bonus_total = _pick_non_overlapping(bonuses)
    total += bonus_total
    # n-gram 只是「字面上像」，不能单独把一条知识带进注入。
    # 起因（全量 8,663 条私聊审计剩下的 3 条 n-gram-only 误命中）：
    #   「那我平时也不玩了」→《平时做什么》11.0（gram「平时」撞标题+别名+summary）
    #   「会了就容易了」    →《夜に駆ける（容易混淆）》10.0（gram「容易」）
    #   「我也是这么说」    →《说话方式》11.0（gram「么说」撞别名「你怎么说话」）
    # 这三条没有任何标题/别名层面的证据，全靠 n-gram 均分刚好过线。
    # 这里只记标记，封顶留到**所有乘数之后**做——理由见文件末尾 GENERIC_CAP 那段：
    # 先封顶再乘 2.2（self 主题）等于没封（5.0 × 2.2 = 11.0 照样过线）。
    ngram_only = bonus_total <= 0.0 and not strong_hit
    # 自身向问题：查询里出现第一人称/自身称呼时，给 self 主题加权
    if entry.get("topic") in TOPIC_BOOST:
        if any(h in q_raw for h in SELF_HINTS):
            total *= TOPIC_BOOST[entry["topic"]]
    # 查询里点名了某主题（如「东方有什么好玩的」），小幅抬高该主题
    hints = TOPIC_HINTS.get(entry.get("topic") or "", ())
    if hints and any(h in q_raw for h in hints):
        total *= TOPIC_HINT_BOOST
    # 通用词封顶必须在**所有乘数之后**。
    # 上一轮把封顶写在别名分支里（min(value, 7.0)），随后 7.0 × 1.6 = 11.2，
    # 照样越过 10.0 阈值——《忙シー日》仍然注入。乘数只能放大真命中，
    # 不能把「对方在说自己忙」放大成一首歌。
    if used_generic and not strong_hit:
        total = min(total, GENERIC_CAP)
    # 纯 n-gram 命中的封顶也必须在乘数之后（同 GENERIC_CAP 的理由）。
    if ngram_only:
        total = min(total, NGRAM_ONLY_CAP)
    return total


def search(db_path: str, query: str, topic: str | None, limit: int,
           include_sensitive: bool = False) -> list[dict]:
    entries = load_entries(db_path, topic)
    if not include_sensitive:
        entries = [e for e in entries if not e.get("sensitive")]
    scored = []
    for e in entries:
        s = score(e, query)
        if s >= 1.0:
            scored.append((s, e))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["title"]))
    out = []
    for s, e in scored[:limit]:
        out.append({
            "score": round(s, 2),
            "topic": e["topic"],
            "slug": e["slug"],
            "title": e["title"],
            "aliases": e["aliases"],
            "summary": e["summary"],
            "detail": e.get("detail", ""),
            "tags": e["tags"],
            "source": e.get("source", ""),
            "confidence": e.get("confidence", ""),
            "sensitive": bool(e.get("sensitive")),
        })
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="查询 Miruku 知识库")
    ap.add_argument("query", nargs="+", help="要查的词或句子")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--topic", default=None)
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--full", action="store_true", help="同时打印 detail")
    ap.add_argument("--include-sensitive", action="store_true",
                    help="连 sensitive 条目标记一起返回（默认过滤）")
    args = ap.parse_args()

    q = " ".join(args.query)
    results = search(args.db, q, args.topic, args.limit, args.include_sensitive)
    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    if not results:
        print(f"没查到：{q}")
        return 0
    for i, r in enumerate(results, 1):
        flag = " [敏感]" if r["sensitive"] else ""
        print(f"{i}. [{r['topic']}] {r['title']}{flag}  ({r['score']})")
        print(f"   {r['summary']}")
        if r["aliases"]:
            print(f"   别名：{'、'.join(r['aliases'])}")
        if args.full and r["detail"]:
            print(f"   详情：{r['detail']}")
        if r["source"]:
            print(f"   来源：{r['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
