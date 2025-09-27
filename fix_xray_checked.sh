#!/usr/bin/env bash
set -e

CONFIG_PATH="/usr/local/etc/xray/config.json"

# Создаём папку на всякий случай
sudo mkdir -p /usr/local/etc/xray

# Пишем новый конфиг
sudo tee $CONFIG_PATH > /dev/null <<EOF
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
          "serverNames": ["www.google.com"],
          "privateKey": "iEtW0aEEXGlQsJ4gD962DeUNx0L7NWBuhPBlUVB1XfGU",
          "shortIds": ["ba4211bb433df45d"]
        }
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "freedom"
    }
  ]
}
EOF

echo "🔍 Проверяем JSON валидность..."
if ! jq . $CONFIG_PATH > /dev/null 2>&1; then
  echo "❌ Ошибка: config.json невалидный JSON!"
  exit 1
fi

echo "✅ JSON валидный. Перезапускаем Xray..."
sudo systemctl restart xray

sleep 2
sudo systemctl status xray --no-pager | head -n 15
