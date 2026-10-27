#!/usr/bin/env bash
# 真实验证：通过 astrbot 的 dashboard API 发一条模拟消息，触发一次 LLM 请求
# 观察：①工具是否被调用 ②输出里是否出现 &&分类键&& 标记 ③标记是否被转成图片
echo "== 找可用的测试入口 =="
curl -s --max-time 6 http://127.0.0.1:6185/api/v1/system-config -o /dev/null -w '  system-config: %{http_code}\n'
curl -s --max-time 6 http://127.0.0.1:6185/api/v1/chat/threads -o /dev/null -w '  chat/threads: %{http_code}\n'

echo ""
echo "== 最可靠的办法：直接读插件的发送日志格式，确认标记转换逻辑存在 =="
grep -oE '&&[^&]*&&|分类键|remove_markup|replace_tag' /opt/miruku/astrbot/data/plugins/meme_manager/main.py 2>/dev/null | sort -u | head -8

echo ""
echo "== 插件是否有 WebUI 页面（你可以直接去看图库）=="
grep -oE '"/[a-z_-]*meme[a-z_-]*"|/api/plugin/meme[^"]*' /opt/miruku/astrbot/data/plugins/meme_manager/mixins/web_api.py 2>/dev/null | sort -u | head -6
