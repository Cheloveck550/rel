#!/usr/bin/env bash
set -euo pipefail

# ===== Defaults =====
CONFIG="/usr/local/etc/xray/config.json"
HOST_GIVEN="64.188.64.214"   # <-- твой IP по умолчанию
OUT="/tmp/reality_doctor.out"
SUB_TXT="/tmp/happvpn_subscription.txt"
LOG_SCAN_HOURS="24"

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'
say() { printf "%b\n" "$1"; }
ok()  { say "${GRN}✔${NC} $1"; }
warn(){ say "${YLW}⚠${NC} $1"; }
err() { say "${RED}✖${NC} $1"; }

usage() {
  cat <<EOF
Usage: sudo $0 [-c /path/to/config.json] [-H host_or_ip] [-o /path/out.txt] [--hours N]

  -c   Путь к xray config.json (default: $CONFIG)
  -H   Домен/IP для ссылок (default: $HOST_GIVEN)
  -o   Путь для отчёта (default: $OUT)
  --hours N  Сколько часов логов смотреть (default: $LOG_SCAN_HOURS)

Примеры:
  sudo $0
  sudo $0 -H vpn.example.com --hours 6
EOF
  exit 1
}

# ---- argv parse ----
OPTS=()
while (( "$#" )); do
  case "$1" in
    -c) CONFIG="$2"; shift 2 ;;
    -H) HOST_GIVEN="$2"; shift 2 ;;
    -o) OUT="$2"; shift 2 ;;
    --hours) LOG_SCAN_HOURS="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) OPTS+=("$1"); shift ;;
  case_esac_done=true
  esac
done

# ---- prerequisites ----
need() { command -v "$1" >/dev/null 2>&1 || { err "Не найдено: $1"; MISSING=1; }; }
MISSING=0
need jq; need ss; need systemctl; need awk; need sed; need base64; need python3; need curl
[ -f "$CONFIG" ] || { err "Не найден конфиг: $CONFIG"; exit 1; }
[ $MISSING -eq 1 ] && exit 1

say "${BLU}==> Reality/Xray Doctor v2 (HappVPN edition)${NC}"

# ---- xray status / version ----
if systemctl is-active --quiet xray; then ok "xray активен"; else err "xray не активен (systemctl status xray)"; fi
if command -v xray >/dev/null 2>&1; then
  XRVER=$(xray version 2>/dev/null | head -n1 | awk '{print $2}')
  say "Версия xray: ${XRVER:-unknown}"
  [[ "${XRVER:-0}" < "1.8" ]] && warn "Рекомендуется xray >= 1.8.x для Reality."
fi

# ---- parse inbound reality ----
INBOUND_JSON=$(jq -c '.inbounds[]? | select((.streamSettings.security=="reality") or (.streamSettings.realitySettings!=null))' "$CONFIG" || true)
[ -n "$INBOUND_JSON" ] || { err "В конфиге нет inbound с Reality."; exit 1; }
INBOUND=$(printf "%s" "$INBOUND_JSON" | head -n1)

PORT=$(jq -r '.port' <<< "$INBOUND")
LISTEN=$(jq -r '.listen // "0.0.0.0"' <<< "$INBOUND")
TYPE=$(jq -r '.protocol // "vless"' <<< "$INBOUND")
NETWORK=$(jq -r '.streamSettings.network // "tcp"' <<< "$INBOUND")

UUID=$(jq -r '.settings.clients[0].id // empty' <<< "$INBOUND")
SERVER_NAMES=$(jq -r '.streamSettings.realitySettings.serverNames // [] | join(",")' <<< "$INBOUND")
SNI_ONE=$(jq -r '.streamSettings.realitySettings.serverNames[0] // empty' <<< "$INBOUND")
SHORT_IDS=$(jq -r '.streamSettings.realitySettings.shortIds // [] | join(",")' <<< "$INBOUND")
SID_ONE=$(jq -r '.streamSettings.realitySettings.shortIds[0] // empty' <<< "$INBOUND")
PK=$(jq -r '.streamSettings.realitySettings.privateKey // empty' <<< "$INBOUND")

ok "inbound найден: protocol=$TYPE, network=$NETWORK, listen=$LISTEN, port=$PORT"
say "serverNames: ${SERVER_NAMES:-none}"
say "shortIds:   ${SHORT_IDS:-none}"

# ---- pbk from privateKey ----
PBK=""
if [[ -n "$PK" && "$PK" != "null" ]]; then
  if command -v xray >/dev/null 2>&1; then
    PBK=$(printf "%s" "$PK" | xray x25519 -i 2>/dev/null | awk '/Public/{print $3}' | tr -d '\r\n' || true)
  fi
  if [[ -z "$PBK" && -n "$PK" ]] && command -v wg >/dev/null 2>&1; then
    PBK=$(printf "%s" "$PK" | base64 -d 2>/dev/null | wg pubkey 2>/dev/null | tr -d '\r\n' || true)
  fi
  [[ -n "$PBK" ]] && ok "pbk получен" || warn "pbk вычислить не удалось — ссылка будет без pbk"
else
  warn "В realitySettings нет privateKey — pbk пропущен"
fi

# ---- host resolve ----
HOST="$HOST_GIVEN"
[[ -z "$HOST" || "$HOST" == "YOUR_DOMAIN_OR_IP" ]] && HOST="$(hostname -f 2>/dev/null || echo "YOUR_DOMAIN_OR_IP")"
ok "HOST для ссылок: $HOST"

# ---- port listen ----
ss -lnpt | grep -q ":$PORT " && ok "порт $PORT слушается" || warn "порт $PORT не слушается (или слушается на другом адресе)"

# ---- time sync ----
if command -v timedatectl >/dev/null 2>&1; then
  TD=$(timedatectl 2>/dev/null || true)
  echo "$TD" | sed 's/^/  /'
  grep -q "System clock synchronized: yes" <<< "$TD" && ok "часы синхронизированы" || warn "часы не синхронизированы (chrony/systemd-timesyncd)"
fi

# ---- server egress quick test ----
curl -I -s --max-time 8 https://www.cloudflare.com >/dev/null && ok "исходящий интернет у сервера есть" || warn "curl не достучался до cloudflare.com — проверьте DNS/egress/файрвол"

# ---- build VLESS links (HappVPN friendly first: NO FLOW) ----
urlenc() { python3 - <<'PY' "$1"; PYEOF
import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=''))
PY
}

IDPART="$UUID"; [[ -z "$IDPART" || "$IDPART" == "null" ]] && { IDPART="YOUR-UUID"; warn "UUID клиента не найден — подставлен шаблон YOUR-UUID"; }

QS_COMMON="type=${NETWORK}&security=reality&fp=chrome&alpn=h2,http/1.1"
[[ -n "$PBK"    ]] && QS_COMMON+="&pbk=$(urlenc "$PBK")"
[[ -n "$SNI_ONE" ]] && QS_COMMON+="&sni=$(urlenc "$SNI_ONE")"
[[ -n "$SID_ONE" ]] && QS_COMMON+="&sid=$(urlenc "$SID_ONE")"

VLESS_NO_FLOW="vless://${IDPART}@${HOST}:${PORT}?${QS_COMMON}#Reality_NoFlow"
VLESS_VISION="vless://${IDPART}@${HOST}:${PORT}?${QS_COMMON}&flow=xtls-rprx-vision#Reality_Vision"

say ""
say "${BLU}==> ССЫЛКИ ДЛЯ ИМПОРТА (сначала без flow — для HappVPN):${NC}"
echo "$VLESS_NO_FLOW"
echo "$VLESS_VISION"

mkdir -p "$(dirname "$OUT")"
{
  echo "# Reality doctor v2 @ $(date -Is)"
  echo "HOST=$HOST  PORT=$PORT  SNI=$SNI_ONE  SID=$SID_ONE"
  echo "UUID=$UUID"
  echo "PBK=$PBK"
  echo
  echo "VLESS (NO FLOW): $VLESS_NO_FLOW"
  echo "VLESS (VISION):  $VLESS_VISION"
} > "$OUT"
ok "Отчёт сохранён: $OUT"

printf "%s\n%s\n" "$VLESS_NO_FLOW" "$VLESS_VISION" > "$SUB_TXT"
ok "HappVPN текстовая подписка записана: $SUB_TXT"

# ---- LOG SCAN (journalctl + /var/log/xray/*) ----
say ""
say "${BLU}==> Анализ логов Xray за последние ${LOG_SCAN_HOURS}ч:${NC}"

# journalctl (служебные логи)
if systemctl status xray >/dev/null 2>&1; then
  JLOG=$(journalctl -u xray --since "${LOG_SCAN_HOURS} hours ago" --no-pager 2>/dev/null | tail -n 1000 || true)
  if [[ -n "$JLOG" ]]; then
    say "Журнал systemd (последние события):"
    echo "$JLOG" | tail -n 40 | sed 's/^/  /'
    # счётчики по паттернам
    PATS=("invalid short id" "invalid shortid" "no such user" "handshake error" "reality" "tls: handshake" "blocked" "rejected")
    for p in "${PATS[@]}"; do
      C=$(printf "%s" "$JLOG" | grep -i "$p" | wc -l | awk '{print $1}')
      [[ "$C" -gt 0 ]] && warn "journalctl: найдено $C совпад.: '$p'"
    done
  else
    warn "journalctl пуст за указанный период"
  fi
else
  warn "systemd не знает сервис xray — пропускаю journalctl"
fi

# access/error логи (если есть)
for f in /var/log/xray/access.log /var/log/xray/error.log; do
  if [[ -f "$f" ]]; then
    say ""
    say "Лог: $f (последние 60 строк)"
    tail -n 60 "$f" | sed 's/^/  /'
    # краткий разбор
    for p in "reality" "handshake" "rejected" "blocked" "invalid" "No such user" "short id"; do
      C=$(grep -i "$p" "$f" | tail -n 1000 | wc -l | awk '{print $1}')
      [[ "$C" -gt 0 ]] && warn "$f: совпадений '$p' = $C"
    done
  fi
done

# ---- Heuristics / Hints based on issues ----
say ""
say "${BLU}==> Диагностические подсказки:${NC}"
cat <<'HINTS'
• Если есть "invalid short id" — проверьте параметр sid= в ссылке и shortIds[] в config.json: они должны совпадать.
• "no such user" — UUID клиента в ссылке отличается от inbound.settings.clients[].id.
• "handshake error" / "tls: handshake" — проверьте sni= (должен быть одним из serverNames[]) и реальный dest в realitySettings.
• Есть подключение, но "интернета нет" — попробуйте ссылку без flow (NoFlow). Некоторые клиенты (в т.ч. HappVPN) нестабильны с xtls-rprx-vision.
• Никаких ошибок, но трафик не идёт — проверьте правила routing и DNS в конфиге, а также что внешний egress не блокируется фаерволом.
HINTS

say "${GRN}Готово!${NC} Импортируй файл подписки в HappVPN: ${SUB_TXT}"
