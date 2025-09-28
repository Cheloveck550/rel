#!/bin/bash
CONFIG="/usr/local/etc/xray/config.json"
SERVER_PY="/root/rel/server.py"

echo "🔧 Проверяем конфиг Xray..."

# Чистим лишний параметр encryption
sed -i '/"encryption":/d' $CONFIG

# Проверка и исправление порта
jq '.inbounds[0].port' $CONFIG | grep -q 443
if [ $? -ne 0 ]; then
  echo "⚠️ Порт не 443 — исправляем"
  tmp=$(mktemp)
  jq '.inbounds[0].port = 443' $CONFIG > "$tmp" && mv "$tmp" $CONFIG
fi

# Проверяем синтаксис JSON
jq . $CONFIG >/dev/null
if [ $? -ne 0 ]; then
  echo "❌ Ошибка в JSON. Проверь config.json"
  exit 1
fi

echo "✅ Конфиг исправлен и проверен"
systemctl restart xray
systemctl status xray --no-pager -l | head -n 20
