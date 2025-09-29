#!/usr/bin/env bash
set -euo pipefail

# === ВВОДНЫЕ (ЗАМЕНИ СВОИМИ!) ===
UUID="${UUID:-10dad63d-53ac-4136-a725-eb0b75164ed5}"     # из uuidgen
PRIVATE_KEY="${PRIVATE_KEY:-SEqS85ST599euUloBDqVYQYjq-UEsQ9Ev4oHhNQqsHs}"  # /usr/local/bin/xray x25519 (PrivateKey)
SHORT_ID="${SHORT_ID:-ebc55ee42c0dea08}"                 # 8–16 hex символов (например из: head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n')
SNI="${SNI:-www.google.com}"
PORT="${PORT:-443}"
NAME="${NAME:-Pro100VPN}"

CONFIG="/usr/local/etc/xray/config.json"
XRAY_BIN="/usr/local/bin/xray"

# Если хочешь жёстко проставить Host/IP в ссылке — задай HOST (иначе возьмём внешний IP)
HOST="${HOST:-}"

echo "-> Бэкапим $CONFIG ..."
cp -a "$CONFIG" "${CONFIG}.bak.$(date +%s)" || true

# Проверим, что jq установлен
if ! command -v jq >/dev/null 2>&1; then
  echo "Устанавливаю jq..."
  apt-get update -y && apt-get install -y jq
fi

# Сконструируем новый корректный конфиг (один inbound VLESS + Reality Vision)
TMP="$(mktemp)"
cat >"$TMP" <<JSON
{
  "log": { "loglevel": "warning" },
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
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SHORT_ID"]
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

# Лёгкая валидация
echo "-> Проверяем JSON..."
jq . "$TMP" >/dev/null

# Применяем конфиг
cp "$TMP" "$CONFIG"
rm -f "$TMP"

echo "-> Перезапускаем xray..."
systemctl restart xray || true
sleep 1

# Покажем сводку
systemctl --no-pager --full status xray.service | sed -n '1,25p' || true

# Проверим, что 443 слушается
echo "-> Проверяем порт $PORT..."
ss -ltnp | grep ":$PORT " || echo "* Порт $PORT не слушается"

# Получим PublicKey из PrivateKey (ОБЯЗАТЕЛЬНО! это то, что идёт в pbk=)
PUBK="$("$XRAY_BIN" x25519 -i "$PRIVATE_KEY" | awk '/PublicKey:/ {print $2}')"
if [[ -z "$PUBK" ]]; then
  echo "!! Не удалось получить PublicKey — проверь PRIVATE_KEY"
  exit 1
fi

# Определим хост для ссылок
if [[ -z "$HOST" ]]; then
  HOST="$(curl -4s ifconfig.co || true)"
  [[ -z "$HOST" ]] && HOST="127.0.0.1"
fi

# Сформируем ссылки
VLESS_FLOW="vless://$UUID@$HOST:$PORT?type=tcp&security=reality&encryption=none&fp=chrome&sni=$SNI&pbk=$PUBK&sid=$SHORT_ID&flow=xtls-rprx-vision#$NAME"
VLESS_NOFLOW="vless://$UUID@$HOST:$PORT?type=tcp&security=reality&encryption=none&fp=chrome&sni=$SNI&pbk=$PUBK&sid=$SHORT_ID#$NAME"

# Deeplink для HappVPN (вариант с flow)
python3 - <<'PY'
import urllib.parse, os
v = os.environ["VLESS_FLOW"]
print("== Deep-link для HappVPN (откроет приложение, с flow) ==")
print("happ://add/" + urllib.parse.quote(v, safe=""))
PY

echo
echo "== Готовые VLESS ссылки =="
echo "с flow:    $VLESS_FLOW"
echo "без flow:  $VLESS_NOFLOW"
echo
echo "== ВАЖНО =="
echo "PublicKey (для клиентов pbk=): $PUBK"
echo "PrivateKey (в конфиге):        $PRIVATE_KEY"
echo "ShortId:                       $SHORT_ID"
echo "UUID:                          $UUID"
echo "* Готово."
