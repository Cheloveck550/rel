#!/bin/bash
set -e

CONFIG_PATH="/usr/local/etc/xray/config.json"

echo "📂 Создаём новый config.json для Xray..."

cat > $CONFIG_PATH <<EOF
{
  "log": {
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "29e9cdce-dff1-49f4-b94b-b26fa32a9a6b",
            "flow": "xtls-rprx-vision"
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "dest": "www.google.com:443",
          "serverNames": [
            "www.google.com"
          ],
          "privateKey": "-N0J53N3H9YhAJsha7SPjhG4culuTm3BABpE5CcdJWs",
          "shortIds": [
            "ba4211bb433df45d"
          ]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": [
          "http",
          "tls"
        ]
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "freedom"
    },
    {
      "protocol": "blackhole"
    }
  ]
}
EOF

echo "✅ Конфиг записан в $CONFIG_PATH"

echo "🔎 Проверяем синтаксис JSON..."
if ! jq . $CONFIG_PATH > /dev/null 2>&1; then
  echo "❌ Ошибка: config.json некорректный!"
  exit 1
fi
echo "✅ JSON корректный"

echo "🔄 Перезапускаем Xray..."
systemctl restart xray

sleep 2
systemctl status xray --no-pager -l | head -n 20

echo "🔍 Проверяем, слушает ли Xray порт 443..."
ss -tlnp | grep 443 || echo "⚠️ Порт 443 не найден!"
