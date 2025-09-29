bash -c '
set -euo pipefail
IP="64.188.64.214"
SNI="${SNI_OVERRIDE:-www.google.com}"   # можно поменять на www.cloudflare.com, www.apple.com и т.д.
NAME="Pro100VPN"

command -v jq >/dev/null 2>&1 || { apt update -y && apt install -y jq; }

[ -x /usr/local/bin/xray ] || { echo "Не найден /usr/local/bin/xray (проверь установку Xray)"; exit 1; }

UUID="$(cat /proc/sys/kernel/random/uuid)"
SID="$(head -c 8 /dev/urandom | od -An -tx1 | tr -d " \n")"
read PRIV PUB < <(/usr/local/bin/xray x25519 | awk "/Private/{p=\$2}/Public/{print p,\$2}")

echo "== Новые параметры =="; echo "UUID: $UUID"; echo "SNI: $SNI"; echo "shortId: $SID"; echo "PublicKey: $PUB"

CFG="/usr/local/etc/xray/config.json"
mkdir -p /usr/local/etc/xray /var/log/xray
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

ufw allow 443/tcp >/dev/null 2>&1 || true
systemctl restart xray
sleep 1

echo
echo "== Состояние Xray =="
systemctl --no-pager --full status xray.service | sed -n "1,25p" || true
echo
echo "== Порт 443 =="
ss -tlpn | grep ":443" || echo "⚠ Порт 443 не слушается"

VLESS_FLOW="vless://$UUID@$IP:443?type=tcp&security=reality&encryption=none&fp=randomized&sni=$SNI&pbk=$PUB&sid=$SID&flow=xtls-rprx-vision#$NAME"
VLESS_NOFLOW="vless://$UUID@$IP:443?type=tcp&security=reality&encryption=none&fp=randomized&sni=$SNI&pbk=$PUB&sid=$SID#$NAME"

python3 - <<PY
import urllib.parse
v1 = """$VLESS_FLOW"""
v2 = """$VLESS_NOFLOW"""
print("\\n=== ССЫЛКИ ДЛЯ КЛИЕНТА ===")
print("с flow (Vision):\\n"+v1+"\\n")
print("без flow:\\n"+v2+"\\n")
print("=== Deep-link для HappVPN (вариант с flow) ===")
print("happ://add/"+urllib.parse.quote(v1, safe=""))
PY

echo
echo "Готово."
'
