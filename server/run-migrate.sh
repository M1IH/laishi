#!/usr/bin/env bash
set -e
cd /opt/miruku/server
sed -i 's/\r$//' assemble.sh migrate_config.py
bash assemble.sh
echo "=== migrate ==="
python3 migrate_config.py
