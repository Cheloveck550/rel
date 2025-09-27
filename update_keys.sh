#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="/usr/local/etc/xray/config.json"
SERVER_PY="$HOME/rel/server.py"

# ====== ТВОИ НОВЫЕ КЛЮЧИ ======
PRIVATE_KEY="-N0J53N3H9YhAJsha7SPjhG4culuTm3BABpE5CcdJWs"
PUBLIC_KEY="m7n-24tmvfTdp2-Szr-vAaM3t9NzGDpTNrva6xM6-ls"

UUID="29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"
SHORTID="ba4211bb433df45d"
DEST="www.google.com:443"
SERVERNAME="www.google.com"
PORT=443

echo "🔑 Обновляем config.json с новым PrivateKey..."
sudo tee "$CONFIG_PATH" > /dev/null <<EOF
{
  "log": {
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "port": ${PORT},
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "${UUID}",
            "flow": "xtls-rprx-vision"
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "dest": "${DEST}",
          "serverNames": ["${SERVERNAME}"],
          "privateKey": "${PRIVATE_KEY}",
          "shortIds": ["${SHORTID}"]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls"]
      }
    }
  ],
  "outbounds": [
    {"protocol": "freedom"},
    {"protocol": "blackhole"}
  ]
}
EOF

echo "✅ config.json обновлён."

echo "🔧 Обновляем server.py с новым PublicKey..."
if [ -f "$SERVER_PY" ]; then
  sed -i "s|^PUBKEY *=.*|PUBKEY   = \"${PUBLIC_KEY}\"|" "$SERVER_PY"
  echo "✅ server.py обновлён."
else
  echo "⚠️ Внимание: файл server.py не найден в $SERVER_PY"
fi

echo "🔄 Перезапускаем Xray..."
sudo systemctl restart xray || true
sleep 2
sudo systemctl status xray --no-pager | head -n 15
