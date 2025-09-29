#!/usr/bin/env bash
set -euo pipefail

CONFIG="/usr/local/etc/xray/config.json"

# ---- helpers ----
need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "• Устанавливаю $1 ..."
    apt-get update -y >/dev/null 2>&1 || true
    apt-get install -y "$1"
  }
}

# ---- checks ----
[[ -f "$CONFIG" ]] || { echo "✖ Не найден $CONFIG"; exit 1; }

need jq
need wireguard-tools   # для wg pubkey
need coreutils         # base64 есть здесь (обычно уже стоит)

# ---- pull values from config ----
PK="$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.privateKey' "$CONFIG")"
SNI="$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.serverNames[0] // .streamSettings.realitySettings.serverName' "$CONFIG")"
SID="$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.shortIds[0] // .streamSettings.realitySettings.shortId' "$CONFIG")"

if [[ -z "$PK" || "$PK" == "null" ]]; then
  echo "✖ В конфиге не найден realitySettings.privateKey"
  exit 1
fi

# ---- compute pbk (base64url) ----
# privateKey хранится в base64url; переводим в обычный base64, декодируем,
# считаем публичный ключ wg pubkey, снова кодируем и переводим в base64url.
PBK="$(printf '%s' "$PK" \
  | tr '_-' '/+' | sed -e 's/$/==/' \
  | base64 -d \
  | wg pubkey \
  | base64 \
  | tr '/+' '_-' | tr -d '=')"

# ---- output ----
mask_pk="${PK:0:6}…${PK: -6}"
echo "✅ Нашёл конфиг: $CONFIG"
echo "• serverName (SNI):  ${SNI:-<не задан>}"
echo "• shortId (SID):     ${SID:-<не задан>}"
echo "• privateKey:        $mask_pk"
echo "• PublicKey (pbk):   $PBK"

# режим «тихий» вывод только pbk:  --raw
if [[ "${1:-}" == "--raw" ]]; then
  echo -n "$PBK"
fi
