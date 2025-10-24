#!/usr/bin/env bash
set -euo pipefail

# === Defaults ===
CONFIG="/usr/local/etc/xray/config.json"
HOST_GIVEN=""
OUT="/tmp/reality_doctor.out"
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'

usage() {
  cat <<EOF
Usage: $0 [-c /path/to/config.json] [-H your.domain.com] [-o /path/to/output.txt]

- c: путь к Xray config.json (по умолчанию: $CONFIG)
- H: домен/IPv4 для ссылки (если не задать, попробуем autodetect)
- o: файл, куда сохранить итоговые ссылки (по умолчанию: $OUT)

Пример:
  sudo $0 -H vpn.example.com
EOF
  exit 1
}

while getopts "c:H:o:h" opt; do
  case "$opt" in
    c) CONFIG="$OPTARG" ;;
    H) HOST_GIVEN="$OPTARG" ;;
    o) OUT="$OPTARG" ;;
    h|*) usage ;;
  esac
done

say() { printf "%b\n" "$1"; }
ok()  { say "${GRN}✔${NC} $1"; }
warn(){ say "${YLW}⚠${NC} $1"; }
err() { say "${RED}✖${NC} $1"; }

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    err "Не найдено: $1. Установите и запустите снова."
    MISSING=1
  fi
}

# === Pre-flight ===
MISSING=0
need jq
need ss
need systemctl
need awk
need sed
need base64
# xray желательно, но не обязательно (fallback на wg)
if ! command -v xray >/dev/null 2>&1 && ! command -v wg >/dev/null 2>&1; then
  warn "Нет xray и wg — не смогу корректно пересчитать pbk из privateKey."
fi

[ -f "$CONFIG" ] || { err "Не найден конфиг: $CONFIG"; exit 1; }
[ "${MISSING:-0}" -eq 1 ] && exit 1

say "${BLU}==> Старт диагностики Reality/Xray${NC}"

# === 1) Xray статус и версия ===
if systemctl is-active --quiet xray; then
  ok "Сервис xray активен"
else
  err "Сервис xray не активен. Проверьте: systemctl status xray"
fi
if command -v xray >/dev/null 2>&1; then
  XRVER=$(xray version 2>/dev/null | head -n1 | awk '{print $2}')
  say "Версия xray: ${XRVER:-unknown}"
  if [[ "${XRVER:-0}" < "1.8" ]]; then
    warn "Рекомендуется xray >= 1.8.x для стабильной работы Reality."
  fi
fi

# === 2) Парсим config.json, ищем inbound с reality ===
INBOUND_JSON=$(jq -c '
  .inbounds[]? 
  | select((.streamSettings.security=="reality") or (.streamSettings.realitySettings!=null))
' "$CONFIG" || true)

if [ -z "$INBOUND_JSON" ]; then
  err "В конфиге не найден inbound с Reality."
  exit 1
fi

# Берём первый подходящий inbound
INBOUND=$(printf "%s" "$INBOUND_JSON" | head -n1)
PORT=$(jq -r '.port' <<< "$INBOUND")
LISTEN=$(jq -r '.listen // "0.0.0.0"' <<< "$INBOUND")
SERVER_NAMES=$(jq -r '.streamSettings.realitySettings.serverNames // [] | join(",")' <<< "$INBOUND")
SNI_ONE=$(jq -r '.streamSettings.realitySettings.serverNames[0] // empty' <<< "$INBOUND")
SHORT_IDS=$(jq -r '.streamSettings.realitySettings.shortIds // [] | join(",")' <<< "$INBOUND")
SID_ONE=$(jq -r '.streamSettings.realitySettings.shortIds[0] // empty' <<< "$INBOUND")
PK=$(jq -r '.streamSettings.realitySettings.privateKey // empty' <<< "$INBOUND")
NETWORK=$(jq -r '.streamSettings.network // "tcp"' <<< "$INBOUND")
TYPE=$(jq -r '.protocol // "vless"' <<< "$INBOUND")

ok "Найден inbound: protocol=$TYPE, network=$NETWORK, listen=$LISTEN, port=$PORT"
say "serverNames: ${SERVER_NAMES:-none}"
say "shortIds:   ${SHORT_IDS:-none}"

# Клиентский UUID (берём первого)
UUID=$(jq -r '.settings.clients[0].id // empty' <<< "$INBOUND")
if [ -z "$UUID" ] || [ "$UUID" = "null" ]; then
  warn "Не найден UUID клиента в inbound.settings.clients[0].id — ссылка будет без него."
fi

# === 3) Пересчитываем publicKey (pbk) из privateKey ===
PBK=""
if [ -n "$PK" ] && [ "$PK" != "null" ]; then
  if command -v xray >/dev/null 2>&1; then
    # xray x25519 -i принимает privateKey (hex/base64) и печатает public
    PBK=$(printf "%s" "$PK" | xray x25519 -i 2>/dev/null | awk '/Public/{print $3}' | tr -d '\r\n')
  fi
  if [ -z "$PBK" ] && command -v wg >/dev/null 2>&1; then
    # Попытка через wg pubkey (ожидает сырой ключ в base64, пробуем)
    # Если PK в hex, этот способ не сработает — тогда PBK останется пустым.
    PBK=$(printf "%s" "$PK" | base64 -d 2>/dev/null | wg pubkey 2>/dev/null | tr -d '\r\n' || true)
  fi
  if [ -n "$PBK" ]; then
    ok "pbk успешно получен из privateKey"
  else
    warn "Не удалось автоматически вычислить pbk из privateKey. Ссылка будет без pbk."
  fi
else
  warn "В realitySettings нет privateKey — не смогу вычислить pbk."
fi

# === 4) Автоопределение HOST ===
HOST="$HOST_GIVEN"
if [ -z "$HOST" ]; then
  # Пытаемся взять FQDN, затем внеш. IP
  FQDN=$(hostname -f 2>/dev/null || true)
  PUBIP=$(curl -s --max-time 3 https://ifconfig.me 2>/dev/null || true)
  if [[ "$FQDN" =~ \. ]]; then
    HOST="$FQDN"
  elif [[ "$PUBIP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    HOST="$PUBIP"
  else
    HOST="YOUR_DOMAIN_OR_IP"
    warn "Не удалось определить домен/IP. Передайте -H your.domain.com для корректной ссылки."
  fi
fi
ok "HOST для ссылки: $HOST"

# === 5) Проверка порта и фаервола ===
if ss -lnpt | grep -q ":$PORT "; then
  ok "Порт $PORT слушается"
else
  err "Порт $PORT не слушается. Проверьте конфиг/слушающий адрес."
fi

# UFW / nft / iptables (поверхностно)
if command -v ufw >/dev/null 2>&1; then
  if ufw status | grep -q "Status: active"; then
    if ufw status | grep -q "$PORT"; then
      ok "UFW: порт $PORT разрешён"
    else
      warn "UFW активен и порт $PORT, возможно, не разрешён"
    fi
  fi
fi

# === 6) Время и синхронизация ===
if command -v timedatectl >/dev/null 2>&1; then
  TD=$(timedatectl 2>/dev/null || true)
  say "Время (timedatectl):"
  echo "$TD" | sed 's/^/  /'
  if echo "$TD" | grep -q "System clock synchronized: yes"; then
    ok "Часы синхронизированы"
  else
    warn "Часы не синхронизированы — Reality может отбрасывать рукопожатия."
  fi
fi

# === 7) Выход в интернет с сервера ===
if curl -I -s --max-time 8 https://www.cloudflare.com >/dev/null; then
  ok "Исходящий интернет у сервера есть"
else
  warn "curl не смог достучаться до https://www.cloudflare.com — проверьте выход наружу / DNS."
fi

# === 8) Генерация VLESS ссылок ===
urlenc() { python3 - <<'PY' "$1"; PYEOF
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))
PY
}

QS_COMMON=""
[ -n "$PBK" ]   && QS_COMMON+="&pbk=$(urlenc "$PBK")"
[ -n "$SNI_ONE" ] && QS_COMMON+="&sni=$(urlenc "$SNI_ONE")"
[ -n "$SID_ONE" ] && QS_COMMON+="&sid=$(urlenc "$SID_ONE")"
QS_COMMON+="&fp=chrome&alpn=h2,http/1.1"
QS_BASE="type=${NETWORK}&security=reality${QS_COMMON}"

IDPART="$UUID"
if [ -z "$IDPART" ] || [ "$IDPART" = "null" ]; then
  IDPART="YOUR-UUID"
  warn "Вставьте в ссылку фактический UUID пользователя."
fi

VLESS_WITH_FLOW="vless://${IDPART}@${HOST}:${PORT}?${QS_BASE}&flow=xtls-rprx-vision#Reality_Vision"
VLESS_NO_FLOW="vless://${IDPART}@${HOST}:${PORT}?${QS_BASE}#Reality_NoFlow"

say ""
say "${BLU}==> Итоговые ссылки (скопируйте и импортируйте в клиент):${NC}"
echo "$VLESS_WITH_FLOW"
echo "$VLESS_NO_FLOW"

mkdir -p "$(dirname "$OUT")"
{
  echo "# Reality doctor @ $(date -Is)"
  echo "HOST=$HOST  PORT=$PORT  SNI=$SNI_ONE  SID=$SID_ONE"
  echo "UUID=$UUID"
  echo "PBK=$PBK"
  echo
  echo "VLESS (VISION): $VLESS_WITH_FLOW"
  echo "VLESS (NO FLOW): $VLESS_NO_FLOW"
} > "$OUT"

ok "Ссылки и параметры сохранены в: $OUT"

# === 9) Подсказки по симптомам HappVPN ===
say ""
say "${BLU}==> Хинты для HappVPN:${NC}"
say " - Если в клиенте «подключается, но нет интернета» — попробуйте ссылку без flow (NoFlow)."
say " - Убедитесь, что sni в ссылке совпадает с одним из serverNames в конфиге."
say " - Если всё равно пусто — проверьте логи:  journalctl -u xray -e --no-pager"
