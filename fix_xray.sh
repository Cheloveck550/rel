#!/usr/bin/env bash
set -euo pipefail

CONFIG="/usr/local/etc/xray/config.json"
XRAY_BIN="${XRAY_BIN:-/usr/local/bin/xray}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "→ Устанавливаю $1 ..."; apt-get update -y && apt-get install -y "$1"; }; }

# Требуются jq и wireguard-tools (wg)
need jq
need wireguard-tools
need coreutils

# 1) Читаем privateKey Reality из конфигурации
if [[ ! -f "$CONFIG" ]]; then
  echo "✖ Не найден $CONFIG"
  exit 1
fi

PRIV=$(jq -r '.inbounds[] | select(.protocol=="vless") | .streamSettings.realitySettings.privateKey // empty' "$CONFIG")

if [[ -z "$PRIV" || "$PRIV" == "null" ]]; then
  echo "✖ В $CONFIG не найден Reality privateKey"
  exit 1
fi

echo "✓ Нашёл privateKey в конфиге:"
echo "  $PRIV"
echo

# Функция: URL-safe base64 → обычный base64 с паддингом
to_std_b64() {
  local s="${1//-/+}"
  s="${s//_//}"
  local m=$(( ${#s} % 4 ))
  if (( m == 2 )); then s="${s}=="
  elif (( m == 3 )); then s="${s}="
  elif (( m == 1 )); then s="${s}==="  # на всякий случай
  fi
  printf '%s' "$s"
}

# Функция: обычный base64 → URL-safe без '='
to_url_b64() {
  printf '%s' "$1" | tr '+/' '-_' | tr -d '='
}

PBK=""

# 2) Попытка №1 — через xray x25519 -i (если поддерживается в твоей сборке)
if [[ -x "$XRAY_BIN" ]]; then
  OUT="$("$XRAY_BIN" x25519 -i "$PRIV" 2>/dev/null || true)"
  CANDIDATE="$(printf '%s\n' "$OUT" | awk '/PublicKey/ {print $2}' | head -n1)"
  if [[ -n "$CANDIDATE" ]]; then
    PBK="$CANDIDATE"
  fi
fi

# 3) Попытка №2 — через wg pubkey (надёжно)
if [[ -z "$PBK" ]]; then
  STD="$(to_std_b64 "$PRIV")" || true
  if ! BYTES=$(printf '%s' "$STD" | base64 -d 2>/dev/null); then
    echo "✖ Не удалось декодировать privateKey (base64). Проверь ключ."
    exit 1
  fi
  # wg pubkey ожидает сырой 32-байтовый приватник на stdin и возвращает base64 (обычный)
  WG_PUB=$(printf '%s' "$BYTES" | wg pubkey 2>/dev/null || true)
  if [[ -z "$WG_PUB" ]]; then
    echo "✖ wg pubkey вернул пусто. Ключ некорректный?"
    exit 1
  fi
  PBK="$(to_url_b64 "$WG_PUB")"
fi

echo "=============================="
echo "PUBLIC KEY (pbk) для Reality:"
echo "$PBK"
echo "=============================="
echo
echo "Подставляй этот pbk в клиентскую vless-ссылку как pbk=${PBK}"
