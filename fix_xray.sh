#!/usr/bin/env bash
set -euo pipefail

CFG_DIR="/usr/local/etc/xray"
CFG="$CFG_DIR/config.json"

# === ВАШИ ДАННЫЕ ===
UUID="29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"
PRIV="-N0J53N3H9YhAJsha7SPjhG4culuTm3BABpE5CcdJWs"
SHORTID="ba4211bb433df45d"
SNI="google.com"           # важно: без www (как в рабочем клиентском примере)
DEST="google.com:443"

echo "==> Готовлю каталог и права…"
mkdir -p "$CFG_DIR"
chown root:root "$CFG_DIR"
chmod 755 "$CFG_DIR"

echo "==> Пишу Reality-конфиг в $CFG…"
tee "$CFG" >/dev/null <<EOF
{
  "log": {
    "loglevel": "debug",
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log"
  },
  "inbounds": [
    {
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [
          { "id": "$UUID", "flow": "xtls-rprx-vision" }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "$DEST",
          "serverNames": ["$SNI"],
          "privateKey": "$PRIV",
          "shortIds": ["$SHORTID"]
        },
        "tcpSettings": { "header": { "type": "none" } }
      },
      "sniffing": { "enabled": true, "destOverride": ["http", "tls"] }
    }
  ],
  "outbounds": [
    { "protocol": "freedom" },
    { "protocol": "blackhole" }
  ]
}
EOF

echo "==> Права на файл…"
chown root:root "$CFG"
chmod 644 "$CFG"

echo "==> Логи для Xray…"
mkdir -p /var/log/xray
chown nobody:nogroup /var/log/xray || true
chmod 755 /var/log/xray

echo "==> Проверка JSON…"
jq empty "$CFG" >/dev/null

echo "==> Перезапуск Xray…"
systemctl restart xray
sleep 1
systemctl status xray --no-pager -l | head -n 20

echo "==> Проверка, слушает ли 443…"
ss -tlnp | grep ':443' || (echo '⚠️  Порт 443 не слушается Xray' && exit 1)

echo "==> Последние строки логов Xray:"
tail -n 50 /var/log/xray/error.log || true
