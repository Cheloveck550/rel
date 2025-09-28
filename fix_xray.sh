#!/bin/bash

CONFIG="/usr/local/etc/xray/config.json"

echo "🔧 Чиним config.json для Xray (удаляем flow)..."

# Делаем резервную копию
cp $CONFIG ${CONFIG}.bak

# Убираем строку flow
jq 'del(.inbounds[].settings.clients[].flow)' $CONFIG > ${CONFIG}.tmp && mv ${CONFIG}.tmp $CONFIG

# Проверяем JSON
if jq empty $CONFIG >/dev/null 2>&1; then
    echo "✅ JSON корректный"
else
    echo "❌ Ошибка в JSON"
    exit 1
fi

# Перезапуск Xray
systemctl restart xray
sleep 2
systemctl status xray --no-pager
