#!/usr/bin/env bash
set -euo pipefail

CONFIG="/usr/local/etc/xray/config.json"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    apt-get update -y >/dev/null 2>&1 || true
    apt-get install -y "$1"
  }
}

need jq
need wireguard-tools

[[ -f "$CONFIG" ]] || { echo "✖ Не найден $CONFIG"; exit 1; }

PK_RAW="$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.privateKey' "$CONFIG")"
SNI="$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.serverNames[0] // .streamSettings.realitySettings.serverName' "$CONFIG")"
SID="$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.shortIds[0] // .streamSettings.realitySettings.shortId' "$CONFIG")"

if [[ -z "$PK_RAW" || "$PK_RAW" == "null" ]]; then
  echo "✖ В конфиге не найден realitySettings.privateKey"; exit 1;
fi

# ---- функция декодирования 32-байтового X25519 приватника из разных вариантов base64 ----
decode_pk() {
  local s="$1" out=""
  # убираем пробелы/переводы строк
  s="${s//$'\n'/}"; s="${s//$'\r'/}"

  # функция добавления паддинга '=' до кратности 4
  pad4() {
    local n=$(( ${#1} % 4 ))
    if   [[ $n -eq 2 ]]; then echo "${1}=="
    elif [[ $n -eq 3 ]]; then echo "${1}="
    elif [[ $n -eq 0 ]]; then echo "${1}"
    else echo "${1}"; fi
  }

  # 1) пробуем base64url -> base64
  if [[ "$s" =~ ^[A-Za-z0-9_-]+$ ]]; then
    local b64="$(pad4 "$(echo -n "$s" | tr '_-' '/+')")"
    if out="$(echo -n "$b64" | base64 -d 2>/dev/null)"; then
      printf '%s' "$out"; return 0
    fi
  fi

  # 2) пробуем обычный base64 (без паддинга)
  if [[ "$s" =~ ^[A-Za-z0-9+/=]+$ ]]; then
    local b64="$(pad4 "$s")"
    if out="$(echo -n "$b64" | base64 -d 2>/dev/null)"; then
      printf '%s' "$out"; return 0
    fi
  fi

  # 3) как крайний случай — попробовать декод с игнором мусора
  if out="$(echo -n "$s" | base64 -d --ignore-garbage 2>/dev/null)"; then
    printf '%s' "$out"; return 0
  fi

  return 1
}

BIN_PK="$(decode_pk "$PK_RAW" || true)"
LEN="${#BIN_PK}"

if [[ -z "$BIN_PK" || "$LEN" -ne 32 ]]; then
  echo "✖ Не удалось корректно декодировать privateKey."
  echo "  Длина после попытки декода: $LEN (ожидалось 32 байта)."
  echo "  Исходная строка (обрезано): ${PK_RAW:0:8}…${PK_RAW: -8}"
  exit 1
fi

# считаем публичный ключ и кодируем его в base64url без '='
PBK="$(printf '%s' "$BIN_PK" | wg pubkey | tr -d '\n' \
      | base64 -d 2>/dev/null || printf '%s' "$BIN_PK" >/dev/null)"

# wg pubkey выводит публичный ключ в обычном base64.
PBK_URL="$(printf '%s' "$BIN_PK" | wg pubkey \
  | tr -d '\n' \
  | base64 -d 2>/dev/null \
  | base64 2>/dev/null | tr '/+' '_-' | tr -d '=' 2>/dev/null || true)"

# Если предыдущая строка пустая (редко, но бывает из-за различий base64), используем стандартный путь:
if [[ -z "$PBK_URL" ]]; then
  PBK_URL="$(printf '%s' "$BIN_PK" | wg pubkey \
    | tr '/+' '_-' | tr -d '=')"
fi

mask_pk="${PK_RAW:0:6}…${PK_RAW: -6}"
echo "✅ Конфиг: $CONFIG"
echo "• serverName (SNI):  ${SNI:-<не задан>}"
echo "• shortId (SID):     ${SID:-<не задан>}"
echo "• privateKey:        $mask_pk"
echo "• PublicKey (pbk):   $PBK_URL"

# Тихий вывод для скриптов
[[ "${1:-}" == "--raw" ]] && echo -n "$PBK_URL"
