#!/usr/bin/env bash
set -euo pipefail

CFG_DIR="/usr/local/etc/xray"
CFG="$CFG_DIR/config.json"

# === ТВОИ ДАННЫЕ ===
UUID="29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"
PRIVATE_KEY="-N0J53N3H9YhAJsha7SPjhG4culuTm3BABpE5CcdJWs"
SHORT_ID="ba4211bb"                 # 8 символов — совместимый вариант
SNI="www.google.com"                # самый совместимый вариант
DEST="www.google.com:443"
LOG_DIR="/var/log/xray"

echo "==> Готовлю директории и права…"
mkdir -p "$CFG_DIR" "$LOG_DIR"
chown root:root "$CFG_DIR"
chmod 755 "$CFG_DIR"
chown nobody:nogroup "$LOG_DIR" || true
chmod 755 "$LOG_DIR"

echo "==> Бэкап старого конфига (если был)…"
if [ -f "$CFG" ]; then
  cp -a "$CFG" "$CFG.bak.$(date +%s)"
fi

echo "==> Пишу НОВЫЙ Reality-конфиг…"
cat >"$CFG" <<'EOF'
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
          { "id": "REPL_UUID", "flow": "xtls-rprx-vision" }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "REPL_DEST",
          "serverNames": ["REPL_SNI"],
          "privateKey": "REPL_PRIV",
          "shortIds": ["REPL_SID"]
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

# подставляем твои значения
sed -i \
  -e "s/REPL_UUID/$UUID/" \
  -e "s#REPL_PRIV#$PRIVATE_KEY#" \
  -e "s/REPL_SID/$SHORT_ID/" \
  -e "s/REPL_SNI/$SNI/" \
  -e "s/REPL_DEST/$DEST/" \
  "$CFG"

echo "==> Проверяю синтаксис JSON…"
jq empty "$CFG"

echo "==> Права на файл…"
chown root:root "$CFG"
chmod 644 "$CFG"

echo "==> Перезапуск Xray…"
systemctl restart xray
sleep 1
systemctl status xray --no-pager -l | head -n 20

echo "==> Проверка порта 443…"
ss -tlnp | grep ':443' || (echo '⚠️ Xray не слушает 443' && exit 1)

echo "==> Готово."
