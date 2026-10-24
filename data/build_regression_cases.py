# -*- coding: utf-8 -*-
"""生成 data/regression_cases.json（结构化回归用例，DS-02）。

为什么要用脚本生成而不是手写 JSON：上一轮 anime.json 手拼字符串时
`《Don't say "lazy"》` 内层引号没转义，整份 JSON 解析失败。
这里一律 json.dump。

用例字段：
    q            输入文本
    expect       "hit" / "miss"
    rank         期望排第几（1 起），省略表示"只要在前 3 就行"
    topic        期望主题（可选，配合 rank 用）
    slug         期望条目（可选，最强断言）
    max_rank     允许的最好名次上限（默认 1 表示必须第一）
    not_slug     明确不能出现在注入里的条目
    why          这条用例为什么存在（给验收的人看）
"""
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "regression_cases.json")


def hit(q, slug=None, topic=None, rank=1, why="", max_rank=None, not_slug=None):
    item = {"q": q, "expect": "hit"}
    if slug:
        item["slug"] = slug
    if topic:
        item["topic"] = topic
    if rank is not None:
        item["rank"] = rank
    if max_rank is not None:
        item["max_rank"] = max_rank
    if not_slug:
        item["not_slug"] = not_slug
    if why:
        item["why"] = why
    return item


def miss(q, why="", not_slug=None):
    item = {"q": q, "expect": "miss"}
    if not_slug:
        item["not_slug"] = not_slug
    if why:
        item["why"] = why
    return item


CASES = {
    "正例": [
        hit("你是谁", "wo-shi-shui", "self", why="自身向问题不能被曲目条目抢走"),
        hit("ACID是谁啊", "acid-jie-mi-juese", "maimai", why="KALEIDXSCOPE 解谜角色，装饰符号与大小写混写"),
        hit("7ref是啥", "7sref", "maimai", why="用户打的是 7ref，条目名是 7sRef，靠别名救回"),
        hit("7sRef到底是个什么世界", "7sref", "maimai"),
        hit("KALEIDXSCOPE怎么开", "kaleidxscope", "maimai"),
        hit("我昨天打到第七道门了", "kaleidxscope-7th-gate", "maimai"),
        hit("Xaleid scopiX好难", "xaleid-scopix", "maimai", why="曲名带 ◆ 装饰符号，normalize 必须清掉"),
        hit("夏玛是谁", "xia-ma", "self", why="しゃま 在 self 和 maimai 都有条目，self 带第一人称加权"),
        hit("何意味", "he-yi-wei", "memes"),
        hit("鸟加那个谱面好难", "niao-jia", "maimai"),
        hit("墓守这歌怎么样", "qu-shu-mu-shou", "maimai",
            why="clean_query 删语气词后别名只覆盖 2/4，覆盖率折扣下限 0.7 的由来"),
        hit("万花筒解谜到哪了", "kaleidxscope", "maimai"),
        hit("洗衣机出勤", "xi-yi-ji", "maimai", why="两个词都指向洗衣机梗，别名「洗衣机」应胜出"),
        hit("300井是什么", "san-bai-jing", "arknights"),
        hit("初音未来的歌你听过吗", "chu-yin-wei-lai", "vocaloid"),
        hit("少女乐队最近在听什么", "shao-nv-yue-dui", "anime",
            why="此前「少女乐队」被 memes/乐 单字条目抢第一"),
        hit("方舟源石怎么攒", "yuan-shi", "arknights", why="同句两个词，分开计分，取高的排第一"),
        hit("三国杀OL还有人玩吗", "san-guo-sha", "sanguosha",
            why="ASCII 短别名 OL 必须守词边界，不能钻进 hololive"),
        hit("街霸6杰米怎么玩", "jie-ba-6", "games"),
        hit("三角洲跑刀怎么打", "san-jiao-zhou-xing-dong", "games"),
        hit("英雄联盟海斗", "hai-ke-si-da-luan-dou", "games"),
        hit("VRChat改模要多久", "gai-mo", "vrchat"),
        hit("小男娘是啥意思", "xiao-nanniang", "vrchat"),
        hit("闲鱼买模型靠谱吗", "xianyu-moxing-keng", "vrchat"),
        hit("hololive最近有什么事", "hololive", "vtuber"),
        hit("东方幻想乡有什么好玩的", "huan-xiang-xiang", "touhou"),
        hit("术力口最近有什么新曲", "shu-li-kou-jiao-fa", "vocaloid"),
    ],
    "正例（排名边界）": [
        hit("小男娘音怎么练", "nanniang-yin", "vrchat",
            why="精确术语与泛主题排名：上一版「小男娘」靠主题加权+别名叠加压到第一，"
                "该答的是「男娘音」。这条是本轮排名修复的核心用例"),
        hit("男娘音", "nanniang-yin", "vrchat", why="只打术语本身，必须是它"),
        hit("英雄联盟", None, "games", rank=None, max_rank=3,
            why="库里没有「英雄联盟」条目，只有两个模式条目；允许前 3，但不能为空"),
        hit("街霸和三角洲哪个难", None, "games", rank=None, max_rank=3,
            why="同句两个游戏，主题必须判对，具体排第几不追究"),
        hit("粥", "zhou", "arknights",
            why="单字圈内叫法：单字查询只认精确等于标题/别名，不能靠子串"),
        hit("鸟", "niao", "maimai", why="同上，单字真叫法要保住"),
        hit("今天忙一天了，晚上想打舞萌", None, "maimai", rank=None, max_rank=3,
            why="日常别名与曲名同句：「忙一天」是《忙シー日》的别名，"
                "但这句话里对方在说自己忙。通用词别名必须封顶 7.0，不能靠语境词放行就注入",
            not_slug="busy-day"),
        # ---- DS-02 新增：组合短句 / 精确术语 / 占位符混入 ----
        hit("7ref 和 KALEIDXSCOPE 有关系吗", None, "maimai", rank=None, max_rank=3,
            why="同句两个 ASCII 术语。clean_query 删掉「和」「有关系吗」后两词会粘成"
                "「7refkaleidxscope」，双双过不了词边界；用 SEP 隔开后各自按整段别名满分"),
        hit("[图片:abc.jpg] 墓守这歌好听吗", "qu-shu-mu-shou", "maimai",
            why="占位符混入文本：占位符必须摘掉，剩下的真话题照常命中"),
        hit("我今天出勤了，打了一下午墓守", "chu-qin-pc", "maimai",
            why="一句话里同时有主题词和曲名，取分高的排第一，曲名不能把它挤掉"),
        hit("衣服买好了，明天出勤穿", "chu-qin-pc", "maimai",
            why="「衣服」是改模条目别名，「出勤」是舞萌主题词。语境词该让出勤胜出，"
                "不能让日常词把话题带偏", not_slug="yifu-caizhi"),
        hit("起床了，等会打舞萌", None, "maimai", rank=None, max_rank=3,
            why="「起床」是曲目别名，「舞萌」是主题词；主题必须判对，"
                "不能因为「起床」两个字注入一首曲子"),
        hit("这个操作在街霸里叫啥", "jie-ba-6", "games",
            why="「操作」既是日常词也是街霸条目别名。有「街霸」在，应命中街霸本体",
            not_slug="xian-dai-jing-dian-cao-zuo"),
        hit("你是AI吗", "ai-shen-fen", "self",
            why="身份向问题，不能靠「AI」二字命中别的条目"),
        hit("英雄联盟和三国杀哪个好玩", None, "sanguosha", rank=None, max_rank=3,
            why="同句两个游戏主题，不能为空，也不能被判成同一个"),
        hit("夏玛和 shama 是一个人吗", None, "self", rank=None, max_rank=3,
            why="同一对象的中英文名一起出现，self 与 maimai 各有一条，前 3 内出现即可"),
        # ---- DS-03 新增：弱词的真提问形态 ----
        # 这 6 条是「弱词必须独立成段」那条规则的保护用例。
        # 没有它们，把 6 个弱词直接塞进 GENERIC_ALIASES 也能让 93 条全绿，
        # 但会悄悄杀掉这些真提问（实测 6 个词会砍掉 9 条真提问、只修好 5 条误命中）。
        hit("旋转怎么打", "hui-zhuan", "maimai",
            why="「旋转」是弱词，但它独立成段，是真的在问这个手法"),
        hit("立绘是什么", "pi-tao", "vtuber",
            why="「立绘」是弱词，独立成段"),
        hit("痛包怎么弄", "er-ci-yuan", "memes",
            why="「痛包」是弱词，独立成段"),
        hit("雷霆的话是什么", "lei-ting", "memes",
            why="「雷霆」是弱词，独立成段"),
        hit("怎么入坑", "ru-keng", "vtuber",
            why="「入坑」是弱词，独立成段（clean_query 删掉「怎么」后只剩它）"),
        hit("你什么性格", "xing-ge", "self",
            why="「性格」是弱词标题，整句 clean 之后正好等于标题"),
        hit("辉夜姬是谁", "hui-ye", "touhou",
            why="「辉夜姬」进弱词集合，但独立成段时仍要命中东方角色"),
        hit("蓬莱山辉夜", "hui-ye", "touhou",
            why="标题整段命中，弱词门禁不该影响完整名字"),
        # ---- DS-03 补丁：天爆（弱词第三种成因）与「大红/爆率」 ----
        # 「天爆」进弱词是因为它是「今天」+「爆率」拼出来的两字，
        # 所以正例必须覆盖「紧跟动作词」这条放行路径，
        # 否则规则会退化成「把天爆整组禁掉」。
        hit("他在打天爆", "heavenly-blast", "maimai",
            why="天爆是弱词，但紧跟动作词「打」，指向明确"),
        hit("我想听天爆", "heavenly-blast", "maimai",
            why="同上，「听」也是动作词"),
        hit("天爆怎么打", "heavenly-blast", "maimai",
            why="「天爆」独立成段"),
        hit("今天爆率高会摸回来的", "da-hong-bao-lv", "games",
            why="OTTO 2026-10-22 指出这句是三角洲的爆率/大红，不是《Heavenly Blast》。"
                "既不能注入那首歌，也该认出「爆率」「摸回来」是搜打撤黑话"),
        hit("大红是什么", "da-hong-bao-lv", "games",
            why="大红是搜打撤红色品质战利品的叫法，2026-10-22 新增条目"),
        hit("你在干什么", "ping-shi-gan-sha", "self",
            why="别名精确匹配。summary 已于 2026-10-22 改为「也有自己的小日子」，"
                "不再输出「没有真人日程」这种自我介绍"),
        # ---- 别名 clean 命中（只对 self 生效）----
        # self 的别名写成人话问句（「你打舞萌吗」「你几岁」），clean_query 会把
        # 查询里的「你」「吗」删掉、却删不掉别名里的，所以 `an in qn` 永远不成立。
        # 修之前「你打舞萌吗」只拿 n-gram 7.0，被《"打舞萌会电我"》38.4 压死——
        # 来世问水平，Miruku 回的是「打舞萌伤身」这个梗。
        hit("你打舞萌吗", "hui-bu-hui-da-wu-meng", "self",
            why="别名 clean 后等于查询。这是最典型的人话问法，修前 38.4 命中的是 dian-wo"),
        hit("你几岁", "sheng-ri-nian-ling", "self",
            why="同上，修前只有 7.0（阈值下，等于不注入）"),
        hit("你唱歌吗", "hui-chang-ge", "self",
            why="同上，修前只有 7.0"),
        hit("你什么段位", "hui-bu-hui-da-wu-meng", "self",
            why="问的是 Miruku 自己的水平。修前 33.0 命中 duan-wei-ren-ding（玩法条目）"),
    ],
    "负例": [
        miss("今天天气不错"),
        miss("早上好"),
        miss("我去睡了"),
        miss("在干嘛"),
        miss("吃了吗"),
        miss("好的"),
        miss("嗯"),
        miss("哈哈哈哈"),
        miss("那我先忙了"),
        miss("晚点再说"),
        miss("[图片:0392a1b4c7.jpg]", why="占位符里的十六进制串不能变成检索词"),
        miss("[表情:abc123]"),
        miss("你吃饭了吗"),
        miss("外面下雨了"),
        miss("我有点困"),
        miss("这个怎么弄"),
        miss("随便聊聊"),
        miss("我回来了"),
        miss("笑死"),
        miss("学校对面的那家店", not_slug="panopticon",
             why="Panopticon 的别名里有「学校」，普通闲聊不该注入一首歌"),
        miss("看你忙一天了", not_slug="busy-day", why="「忙一天」是《忙シー日》的别名"),
        miss("监狱里的人都这样", why="「监狱」是曲目别名，也是日常词"),
        miss("这件衣服挺好看", why="「衣服」是改模条目别名，也是日常词"),
        miss("我起床了", why="「起床」是曲目别名，也是日常词"),
        miss("这个操作有点难", why="「操作」是街霸条目别名，也是日常词"),
        miss("你玩什么游戏", why="泛问句，不该猜成某个具体游戏"),
        miss("[图片:abc] 这歌好听吗", why="占位符 + 弱语境：占位符清掉后只剩「这歌好听吗」"),
        miss("lol", why="ASCII 子串：lo/ol 会钻进 hololive。库里没有英雄联盟条目，"
                        "宁可空也不要注入 hololive"),
        miss("13", why="纯数字：13 会命中「等级与等级值」的别名 13+"),
        miss("88", why="纯数字：88 是拜拜，暗号条目只在特定消息触发"),
        miss("行", why="中文单字：行 会同时命中三角洲行动/砂之行星/西行寺幽幽子"),
        # ---- DS-02 新增负例：全部取自真实语料里出现过的日常句 ----
        miss("我和朋友去吃饭了", why="「朋友」是曲目别名，也是日常词"),
        miss("今天下雨了，衣服还没收", why="「衣服」是改模条目别名，这句话在说晾衣服"),
        miss("他住在学校旁边", why="「学校」是 Panopticon 的别名"),
        miss("这个软件挺好用", why="「软件」是条目标签，日常语境"),
        miss("明天早八", why="「早八」是曲目别名，也是课程表用语"),
        miss("他好像有点急", why="「急了」是红温条目别名，这里是描述别人着急"),
        miss("我手机快没电了，等会再说", why="含「电」字，不能命中打舞萌会电我"),
        miss("我今天打了一整天", why="「打」类单字语境词必须 ≥2 字，不能靠「打」放行"),
        miss("我在楼下等你", why="纯日常，不该有任何注入"),
        miss("你昨天几点睡的", why="纯日常，不该有任何注入"),
        # ---- DS-03 新增负例：弱词被当成普通汉语词用 ----
        # 全部取自全量 8,663 条私聊里真实出现过的句子，且逐条读过上下文。
        miss("好像能旋转", why="日常动词。旋转是《旋转与\"皿\"》的别名，但它粘在句子里，"
                          "不是独立成段，说明不是在问那个手法"),
        miss("并非痛包", why="「痛包」是《二次元/谷子/痛包》标题里的一段，这里在否认"),
        miss("看到立绘脸红吗", why="在说角色的立绘，不是问 vtuber 的皮套概念"),
        miss("我干脆直接入坑邦邦得了", why="「入坑」是 vtuber 条目别名，但语境是 BanG Dream"),
        miss("什么雷霆封面", why="「雷霆」是定语，在说封面"),
        miss("光是看外貌和性格也能看出来", why="在陈述别人的性格，不是问 Miruku 的性格。"
                                "这句会 clean 出独立的「性格」段，所以弱词标题分支也要挡"),
        # ---- 别名 clean 命中不能外溢到非 self 主题 ----
        # 这条规则如果对全主题生效，别名 clean 后退化成的常用词会大面积误命中，
        # 下面三条就是全量审计里实测新冒出来的（都属真实语料的日常用法）。
        miss("什么意思", why="「什么意思」是《何意味》的别名，clean 成「意思」后曾注入 29.0"),
        miss("真的假的", why="「真的假的」是《会赢的》的别名，clean 成「真/假」后曾注入 20.0"),
        miss("你是格调", why="「有格调」是 Λzure Vixen 的别名，clean 成「格调」后曾注入 25.0"),
    ],
    "敏感条目不得注入": [
        miss("开盒是什么意思", not_slug="wei-pi"),
        miss("炎上是怎么起来的", not_slug="yan-shang"),
        miss("卫批这个词", not_slug="wei-pi"),
        miss("雌小鬼是啥", not_slug="ci-xiao-gui"),
        miss("女装去漫展", not_slug="nv-zhuang"),
        miss("A-SOUL现在怎么样了", not_slug="a-soul"),
        miss("VShojo解散了吗", not_slug="vshojo"),
        miss("你叫什么名字", why="隐私向问句：自身条目里没有真名/住址，但也不该被别的条目顶上"),
        miss("你家住哪", why="同上"),
    ],
}

META = {
    "version": 4,
    "updated": "2026-10-22",
    "task": "DS-02 / DS-03",
    "notes": [
        "expect=hit 时按 rank（默认 1）断言名次；给了 max_rank 则只要求不差于该名次。",
        "expect=miss 要求 inject.build_block 返回空字符串，即真的不注入，"
        "而不是「没有期望条目」。",
        "not_slug 是附加断言：即使整体判定通过，这些条目也不能出现在注入结果里。",
        "所有用例都要求注入文本 ≤ 600 字符，且不含路径/账号/密钥。",
        "DS-03 起，弱词（WEAK_ALIASES：性格/旋转/入坑/立绘/痛包/雷霆/天爆）的正例与负例成对存在。"
        "只测负例会退化成「把弱词整组禁掉」；只测正例会退化成「什么都注入」。"
        "两边必须同时通过，改动才算成立。",
        "DS-03 修订起，「别名 clean 后等于查询」这条只对 self 主题生效，"
        "且正例（你打舞萌吗/你几岁/你唱歌吗/你什么段位）与负例（什么意思/真的假的/你是格调）"
        "必须成对存在——只测正例会让这条规则外溢到其他主题，"
        "别名 clean 后退化成常用词就会误注入（实测三条各 29.0/20.0/25.0）。",
    ],
}


def main() -> int:
    payload = {"meta": META}
    payload.update(CASES)
    total = sum(len(v) for v in CASES.values())
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("wrote %s" % OUT)
    for name, items in CASES.items():
        print("  %-12s %d" % (name, len(items)))
    print("  total        %d" % total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
