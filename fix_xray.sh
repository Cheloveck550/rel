cat >/root/rel/rebuild_reality.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

# === Параметры сервера ===
IP="64.188.64.214"                   # твой внешний IP
SNI="${SNI_OVERRIDE:-www.cloudflare.com}"   # можно сменить на www.google.com позже
NAME="Pro100VPN"

# === Проверка зависимостей ===
command -v jq >/dev/null || { echo "Установи jq: apt update && apt install -y jq"; exit 1; }
[ -x /usr/local/bin/xray ] || { echo "Не найден /usr/local/bin/xray"; exit 1; }

# === Генерация UUID/shortId/ключей x25519 ===
UUID="$(cat /proc/sys/kernel/random/uuid)"
SID="$(head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n')"   # 16 hex
read PRIV PUB < <(/usr/local/bin/xray x25519 | awk '/Private/{p=$2}/Public/{print p,$2}')

echo "== Новые параметры =="
echo "UUID    : $UUID"
echo "SNI     : $SNI"
echo "shortId : $SID"
echo "Private : $PRIV"
echo "Public  : $PUB"

# === Бэкап и запись конфига Xray (VLESS+Reality inbound на 443, Vision-flow) ===
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
          "dest": "$SNI:443",
          "serverNames": ["$SNI"],
          "privateKey": "$PRIV",
          "shortIds": ["$SID"]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http","tls"]
      }
    }
  ],
  "outbounds": [
    { "protocol": "freedom" },
    { "protocol": "blackhole", "tag": "blocked" }
  ]
}
JSON

# === Фаервол (на всякий случай) ===
ufw allow 443/tcp >/dev/null 2>&1 || true

# === Перезапуск Xray и проверка ===
systemctl restart xray
sleep 1
systemctl --no-pager --full status xray.service || true
ss -tlpn | grep ':443' || { echo "Порт 443 не слушается!"; exit 1; }

# === Формирование ссылок ===
VLESS_FLOW="vless://$UUID@$IP:443?type=tcp&security=reality&encryption=none&fp=randomized&sni=$SNI&pbk=$PUB&sid=$SID&flow=xtls-rprx-vision#$NAME"
VLESS_NOFLOW="vless://$UUID@$IP:443?type=tcp&security=reality&encryption=none&fp=randomized&sni=$SNI&pbk=$PUB&sid=$SID#$NAME"

# deep-link для HappVPN: кодируем vless-ссылку с flow
ENCODED="$(python3 - <<PY
import urllib.parse,sys
s = "$VLESS_FLOW"
print("happ://add/" + urllib.parse.quote(s, safe=""))
PY
)"

echo
echo "=== ССЫЛКИ ДЛЯ КЛИЕНТА ==="
echo "с flow (Vision):"
echo "$VLESS_FLOW"
echo
echo "без flow:"
echo "$VLESS_NOFLOW"
echo
echo "=== Deep-link для HappVPN (вариант с flow) ==="
echo "$ENCODED"
echo
echo "Готово."
SH
chmod +x /root/rel/rebuild_reality.sh
sudo /root/rel/rebuild_reality.sh
