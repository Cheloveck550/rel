#!/usr/bin/env bash
set -euo pipefail

CFG="/usr/local/etc/xray/config.json"
LOG_DIR="/var/log/xray"

# === текущие данные (из твоего вывода) ===
UUID="29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"
PRIVATE_KEY="-N0J53N3H9YhAJsha7SPjhG4culuTm3BABpE5CcdJWs"
SNI="www.google.com"
DEST="${SNI}:443"
HOST="64.188.64.214"

# ВАЖНО: делаем 16-символьный shortId (hex)
SHORT_ID="ba4211bb433df45d"

# fingerprint для линка — randomized (для HappVPN)
FP="randomized"

mkdir -p "$(dirname "$CFG")" "$LOG_DIR"
chown root:root "$(dirname "$CFG")"
chmod 755 "$(dirname "$CFG")"

if [ -f "$CFG" ]; then cp -a "$CFG" "$CFG.bak.$(date +%s)"; fi

cat >"$CFG" <<JSON
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
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SHORT_ID"],
          "spiderX": "/"
        },
        "tcpSettings": { "header": { "type": "none" } }
      },
      "sniffing": { "enabled": true, "destOverride": ["http","tls"] }
    }
  ],
  "outbounds": [
    { "protocol": "freedom" },
    { "protocol": "blackhole" }
  ]
}
JSON

jq empty "$CFG" >/dev/null

# pbk: у твоей сборки xray x25519 -i печатает строку Password — это и есть publicKey
PBK="$(/usr/local/bin/xray x25519 -i "$(jq -r '.inbounds[0].streamSettings.realitySettings.privateKey' "$CFG")" \
      | sed -n 's/^PublicKey[: ]\+//p; s/^Password[: ]\+//p' | head -n1)"

systemctl restart xray
sleep 1
ss -tlnp | grep ':443' || (echo 'Xray не слушает 443' && exit 1)

# Сформируем новые ссылки
BASE="vless://$UUID@$HOST:443?type=tcp&security=reality&encryption=none&fp=$FP&sni=$SNI&pbk=$PBK&sid=$SHORT_ID"
echo
echo "=== ССЫЛКИ ДЛЯ КЛИЕНТА ==="
echo "с flow (Vision):"
echo "${BASE}&flow=xtls-rprx-vision#Pro100VPN"
echo
echo "без flow:"
echo "${BASE}#Pro100VPN"
echo
echo "=== Deep-link для HappVPN (открывает приложение, вариант с flow) ==="
ENC="$(python3 - <<'PY'
import urllib.parse,sys
raw="""${BASE}&flow=xtls-rprx-vision#Pro100VPN"""
print("happ://add/"+urllib.parse.quote(raw, safe=''))
PY
)"
echo "$ENC"
echo
echo "Готово."
