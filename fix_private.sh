#!/usr/bin/env bash
set -e

CONFIG_PATH="/usr/local/etc/xray/config.json"

echo "🔑 Генерируем новые Reality ключи..."
KEYS=$(xray x25519)

PRIV=$(echo "$KEYS" | grep "Private key" | awk '{print $3}')
PUB=$(echo "$KEYS" | grep "Public key" | awk '{print $3}')

if [ -z "$PRIV" ] || [ -z "$PUB" ]; then
  echo "❌ Ошибка: не удалось извлечь ключи"
  exit 1
fi

echo "✅ Новый PrivateKey: $PRIV"
echo "✅ Новый PublicKey:  $PUB"
echo "⚠️ Важно: этот PublicKey нужно будет вписать в клиент HappVPN!"

# Записываем новый config.json
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
          "privateKey": "$PRIV",
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

echo "🔄 Перезапускаем Xray..."
sudo systemctl restart xray
sleep 2
sudo systemctl status xray --no-pager | head -n 15
