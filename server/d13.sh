#!/usr/bin/env bash
# 重启 astrbot 加载 meme_manager，检查加载结果与报错
echo "== 重启 astrbot =="
docker restart astrbot >/dev/null 2>&1
echo "  等待启动..."
for i in $(seq 1 20); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:6185/api/v1/system-config 2>/dev/null || echo 000)
  [ "$code" = "401" ] || [ "$code" = "200" ] && { echo "  面板已就绪 (t+$((i*5))s, code=$code)"; break; }
done

echo ""
echo "== meme_manager 加载情况 =="
docker logs astrbot --since 3m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'meme_manager|meme' | tail -12

echo ""
echo "== 有无依赖缺失/异常 =="
docker logs astrbot --since 3m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'ModuleNotFound|ImportError|Traceback|requirements|pip install' | tail -8 || echo "  （无）"

echo ""
echo "== 已加载插件总数 =="
docker logs astrbot --since 3m 2>&1 | grep -c 'Loading plugin' | sed 's/^/  /'
