#!/bin/bash
set -e

UUID="10dad63d-53ac-4136-a725-eb0b75164ed5"
PRIVATE_KEY="SEqS85ST599eUloBDqVYQYjq-UEsQ9Ev4oHhNQqsHs"
SHORT_ID="ebc55ee42c0dea08"

CONFIG="/usr/local/etc/xray/config.json"
BACKUP="/usr/local/etc/xray/config.json.bak.$(date +%s)"

echo "-> Делаем бэкап в $BACKUP"
cp "$CONFIG" "$BACKUP"

cat > "$CONFIG" <<EOF
{
  "inbounds": [
    {
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "$UUID",
            "flow": "xtls-rprx-vision"
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "www.google.com:443",
          "serverNames": ["www.google.com"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SHORT_ID"]
        }
      }
    }
  ],
  "outbounds": [
    { "protocol": "freedom" },
    { "protocol": "blackhole", "tag": "blocked" }
  ]
}
EOF

echo "-> Проверяем JSON..."
jq . "$CONFIG" > /dev/null

echo "-> Перезапускаем xray..."
systemctl restart xray

sleep 1
systemctl status xray --no-pager -l | head -n 20
