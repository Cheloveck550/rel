#!/usr/bin/env bash
set -euo pipefail

CFG_DIR="/usr/local/etc/xray"
CFG="$CFG_DIR/config.json"

UUID="29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"
PRIV="-N0J53N3H9YhAJsha7SPjhG4culuTm3BABpE5CcdJWs"
SHORTID="ba4211bb433df45d"
SNI="google.com"             # важный фикс: без www
DEST="google.com:443"

echo "==> Готовлю каталог $CFG_DIR и права…"
sudo mkdir -p "$CFG_DIR"
sudo chown root:root "$CFG_DIR"
sudo chmod 755 "$CFG_DIR"

echo "==> Пишу новый Reality-конфиг в $CFG…"
sudo tee "$CFG" >/dev/null <<EOF
{
  "log": { "loglevel": "warning" },
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
  "outbounds": [ { "protocol": "freedom" }, { "protocol": "blackhole" } ]
}
EOF

echo "==> Выставляю права на файл…"
sudo chown root:root "$CFG"
sudo chmod 644 "$CFG"

echo "==> Проверяю JSON…"
jq empty "$CFG" >/dev/null

echo "==> Перезапускаю Xray…"
sudo systemctl restart xray
sleep 1
sudo systemctl status xray --no-pager -l | head -n 20

echo "==> Проверяю, слушает ли порт 443…"
ss -tlnp | grep ':443' || (echo '⚠️  443 не слушается' && exit 1)

echo "✅ Готово."
