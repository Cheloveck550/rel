#!/usr/bin/env bash
set -euo pipefail

CFG_DIR="/usr/local/etc/xray"
CFG="$CFG_DIR/config.json"
LOG_DIR="/var/log/xray"

# === ТВОИ ДАННЫЕ ===
UUID="29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"
PRIVATE_KEY="-N0J53N3H9YhAJsha7SPjhG4culuTm3BABpE5CcdJWs"
SHORT_ID="ba4211bb"            # 8 символов — совместимый вариант
SNI="www.google.com"
DEST="${SNI}:443"
HOST="64.188.64.214"           # host в ссылке = адрес твоего сервера
FP="chrome"

echo "==> Готовлю каталоги и права…"
mkdir -p "$CFG_DIR" "$LOG_DIR"
chown root:root "$CFG_DIR"
chmod 755 "$CFG_DIR"
chown nobody:nogroup "$LOG_DIR" || true
chmod 755 "$LOG_DIR"

if [ -f "$CFG" ]; then
  cp -a "$CFG" "$CFG.bak.$(date +%s)"
  echo "==> Бэкап: $CFG.bak.$(date +%s)"
fi

echo "==> Пишу НОВЫЙ корректный Reality-конфиг…"
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
          "shortIds": ["$SHORT_ID"]
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
JSON

echo "==> Проверяю синтаксис JSON…"
jq empty "$CFG"

echo "==> Структурная проверка (inbounds — массив, protocol=vless)…"
jq -r '.inbounds | type' "$CFG"
jq -r '.inbounds[0].protocol' "$CFG"

echo "==> Права на файл…"
chown root:root "$CFG"
chmod 644 "$CFG"

echo "==> Получаю publicKey (у твоей сборки это строка Password)…"
/usr/local/bin/xray x25519 -i "$(jq -r '.inbounds[0].streamSettings.realitySettings.privateKey' "$CFG")" \
  | tee /tmp/x25519.out
PBK="$(sed -n 's/^PublicKey[: ]\+//p; s/^Password[: ]\+//p' /tmp/x25519.out | head -n1)"

if [ -z "$PBK" ]; then
  echo "❌ Не удалось извлечь publicKey из вывода xray x25519 -i"
  exit 2
fi

echo "==> Перезапускаю Xray…"
systemctl restart xray
sleep 1
systemctl status xray --no-pager -l | head -n 20

echo "==> Проверяю, слушает ли 443…"
ss -tlnp | grep ':443' || (echo '⚠️ Xray не слушает 443' && exit 1)

echo "==> Формирую канонические VLESS-ссылки (host=IP, encryption=none, SNI=$SNI, pbk из x25519)…"
BASE="vless://$UUID@$HOST:443?type=tcp&security=reality&encryption=none&fp=$FP&sni=$SNI&pbk=$PBK&sid=$SHORT_ID"
echo "с flow   : ${BASE}&flow=xtls-rprx-vision#Pro100VPN"
echo "без flow : ${BASE}#Pro100VPN"

echo "✅ Готово."
