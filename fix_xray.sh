#!/bin/bash
set -e

CONFIG=/usr/local/etc/xray/config.json
BACKUP=/usr/local/etc/xray/config.json.bak.$(date +%s)

echo "-> Бэкапим $CONFIG в $BACKUP ..."
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
            "id": "10dad63d-53ac-4136-a725-eb0b75164ed5",
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
          "xver": 0,
          "serverNames": ["www.google.com"],
          "privateKey": "SEqS85ST599eUloBDqVYQYjq-UEsQ9Ev4oHhNQqsHs",
          "shortIds": ["ebc55ee42c0dea08"]
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

echo "-> Проверяем синтаксис..."
jq . "$CONFIG" > /dev/null || { echo "Ошибка JSON"; exit 1; }

echo "-> Перезапускаем Xray..."
systemctl restart xray

sleep 2
systemctl status xray --no-pager -l | head -n 20
