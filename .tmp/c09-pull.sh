#!/bin/bash
# 拉取线上 proactive_chat 的 5 个待改文件，打包回传
set -uo pipefail
P=/AstrBot/data/plugins/astrbot_plugin_proactive_chat
docker exec astrbot tar -cf /tmp/c09.tar \
  $P/core/services/sender_service.py \
  $P/core/services/scheduler_service.py \
  $P/core/features/deliver/split_delivery.py \
  $P/core/features/record/history_writer.py \
  $P/core/pipeline/flow_orchestrator.py
docker cp astrbot:/tmp/c09.tar /tmp/c09.tar
ls -la /tmp/c09.tar
