#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「遇陌生物先搜再答」的规则补进 DB 里生效的 miruku persona。
幂等：已含标记则跳过。失败不写库。"""
import sqlite3
import sys

DB = "/AstrBot/data/data_v4.db"
MARK = "先搜再答"

OLD1 = "别人认真求助或情绪低落时，收起嘲讽，简短认真说。"
NEW1 = (
    "别人认真求助或情绪低落时，收起嘲讽，简短认真说。"
    "碰到具体的东西你自己不确定——谱面名、术语、新梗、作品、赛事、机型、新闻——"
    "嫌麻烦归嫌麻烦，但还是得先搜再答：搜一次（query 带上领域词，舞萌的就写 maimai 或 舞萌），"
    "看完简短说结论，别复述搜出来的句子。搜不到就说“没刷过”“不清楚”，不许凭印象编细节。"
)

OLD2 = "也不要描述自己的思考过程、内部步骤或“我这就去查”。"
NEW2 = "也不要描述自己的思考过程、内部步骤或“我这就去查”（搜东西不用跟他报备，直接搜完答就行，这不算描述步骤）。"

con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("SELECT system_prompt FROM personas WHERE persona_id='miruku'")
row = cur.fetchone()
if not row:
    print("FAIL no persona")
    sys.exit(1)
sp = row[0]
before_len = len(sp)

if MARK in sp:
    print("SKIP already patched, len=%d" % before_len)
    sys.exit(0)

c1 = sp.count(OLD1)
c2 = sp.count(OLD2)
print("anchor1 count =", c1)
print("anchor2 count =", c2)
if c1 != 1 or c2 != 1:
    print("FAIL anchors not unique")
    sys.exit(1)

new = sp.replace(OLD1, NEW1, 1).replace(OLD2, NEW2, 1)

# 落库前自检
assert MARK in new, "mark missing"
assert new.count("先搜再答") == 1, "mark duplicated"
assert len(new) > before_len, "not longer"
# NEW1/NEW2 都是 OLD 的前缀扩展，所以 OLD 会出现在 NEW 里一次。
# 正确的校验：结果里 NEW 各出现一次，且长度正好是 before + 两段新增。
assert new.count(NEW1) == 1, "new1 count"
assert new.count(NEW2) == 1, "new2 count"
expect_len = before_len + (len(NEW1) - len(OLD1)) + (len(NEW2) - len(OLD2))
assert len(new) == expect_len, "len %d != %d" % (len(new), expect_len)

cur.execute("UPDATE personas SET system_prompt=? WHERE persona_id='miruku'", (new,))
con.commit()

cur.execute("SELECT system_prompt FROM personas WHERE persona_id='miruku'")
verify = cur.fetchone()[0]
print("COMMITTED %d -> %d" % (before_len, len(verify)))
print("verify mark =", MARK in verify)
print("verify char stable =", verify == new)
con.close()
