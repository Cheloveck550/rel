#!/bin/bash
set -e

# === Настройки под твой сервер ===
UUID="4f09a57e-76c7-497c-a878-db737cd6a5b5"
SNI="www.cloudflare.com"
DEST="www.cloudflare.com:443"
PRIVATE_KEY="ВСТАВЬ_СЮДА_СВОЙ_PRIVATE_KEY"
SHORT_ID="bb45e9b132a66a07"

CONFIG_PATH="/usr/local/etc/xray/config.json"

echo "[1/4] Делаем резервную копию старого config.json..."
if [ -f "$CONFIG_PATH" ]; then
    cp "$CONFIG_PATH" "$CONFIG_PATH.bak_$(date +%F_%T)"
    echo "✅ Резервная копия сохранена: $CONFIG_PATH.bak_$(date +%F_%T)"
fi

echo "[2/4] Перезаписываем новый config.json..."
cat > $CONFIG_PATH <<EOF
{
  "inbounds": [
    {
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "$UUID",
            "flow": ""
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "$DEST",
          "xver": 0,
          "serverNames": [ "$SNI" ],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": [ "$SHORT_ID" ]
        }
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "freedom",
      "settings": {}
    }
  ]
}
EOF

echo "[3/4] Проверяем синтаксис JSON..."
jq . $CONFIG_PATH > /dev/null
echo "✅ JSON корректный!"

echo "[4/4] Перезапускаем XRay..."
systemctl restart xray
sleep 2
systemctl status xray --no-pager
