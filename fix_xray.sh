#!/usr/bin/env bash
set -euo pipefail

# === ПОДСТАВЛЕНЫ ТВОИ НОВЫЕ ДАННЫЕ ===
UUID="10dad63d-53ac-4136-a725-e0b075164ed5"
PRIV="SEqS8SST9599eUO0BqVQYjq-UE0sA9EV4oHhNQqsHs"
PUB="wr6EkbDM_3SDXL_6Zh4MPH_aB3Gb1IBu2O5a2k12kM"   # это PublicKey (у тебя Xray печатает его с меткой Password)
SID="ebc55ee42c0dea08"
SNI="www.google.com"
PORT=443

CFG="/usr/local/etc/xray/config.json"
mkdir -p /usr/local/etc/xray /var/log/xray

echo "→ Бэкапим $CFG ..."
cp -a "$CFG" "$CFG.bak.$(date +%s)" 2>/dev/null || true

cat >"$CFG" <<JSON
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log"
  },
  "inbounds": [
    {
      "port": $PORT,
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
          "dest": "$SNI:443",
          "serverNames": ["$SNI"],
          "privateKey": "$PRIV",
          "shortIds": ["$SID"]
        }
      },
      "sniffing": { "enabled": true, "destOverride": ["http","tls"] }
    }
  ],
  "outbounds": [
    { "protocol": "freedom" },
    { "protocol": "blackhole", "tag": "blocked" }
  ]
}
JSON

echo "→ Перезапускаем Xray ..."
ufw allow 443/tcp >/dev/null 2>&1 || true
systemctl restart xray

sleep 1
echo "→ Проверяем порт 443:"
ss -tlpn | grep ":443" || echo "⚠ Порт 443 не слушается"

echo
echo "== Готовые VLESS ссылки =="
VLESS_FLOW="vless://$UUID@64.188.64.214:$PORT?type=tcp&security=reality&encryption=none&fp=chrome&sni=$SNI&pbk=$PUB&sid=$SID&flow=xtls-rprx-vision#Pro100VPN"
VLESS_NOFLOW="vless://$UUID@64.188.64.214:$PORT?type=tcp&security=reality&encryption=none&fp=chrome&sni=$SNI&pbk=$PUB&sid=$SID#Pro100VPN"
echo "с flow:     $VLESS_FLOW"
echo "без flow:   $VLESS_NOFLOW"

echo
python3 - <<PY
import urllib.parse, os
v1=os.environ["VLESS_FLOW"]
print("== Deep-link для HappVPN (вариант с flow) ==")
print("happ://add/"+urllib.parse.quote(v1, safe=""))
PY

echo
echo "Готово."
