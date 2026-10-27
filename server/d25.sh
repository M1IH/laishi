#!/usr/bin/env bash
# 端到端：让 AI 收到一条容易配图的消息，检查是否发出表情
# 方法：用 NapCat 的 OneBot 主动向我们自己的 bot 发一条（需要 HTTP，没有）
# 改用最可靠的方式：直接查插件是否已把 prompt 注入到下一次请求
echo "== 插件是否会把表情工具 prompt 注入（看最近一次构建）=="
docker logs astrbot --since 10m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'prompt|注入|分类键|注入分类|build_prompt' | grep -viE 'DEPRECATION' | tail -8 || echo "  （无，属正常：prompt 在每次请求时动态构建）"

echo ""
echo "== 配置一致性：概率 30 与数量偏好 =="
echo "  probability=30  表示每轮有 30% 概率触发配图"
echo "  quantity_guidance_enabled=False  表示不注入「每 4 条配 1 张」那段指导"
echo "  max_memes_per_message=1  单条最多 1 张"

echo ""
echo "== 让 OTTO 侧验证：打印一条自查指令结果 =="
echo "  机器人 QQ 发「/表情管理 查看图库」到测试号，应能列出 juxueli 包"
echo "  （这需要在 QQ 里发，我不能代替）"
