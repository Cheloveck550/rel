#!/usr/bin/env bash
set -euo pipefail

CONFIG="/usr/local/etc/xray/config.json"
SERVER_PY="/root/rel/server.py"

echo "==> Проверяю наличие jq..."
if ! command -v jq >/dev/null 2>&1; then
  apt-get update && apt-get install -y jq
fi

echo "==> Бэкап конфига Xray..."
cp -a "$CONFIG" "${CONFIG}.bak.$(date +%s)"

echo "==> Чищу лишний 'encryption' в clients (он запрещён в inbound VLESS)..."
tmp="$(mktemp)"
jq '(.inbounds[]?.settings?.clients? // []) as $c
  | .inbounds |= (map(
      if .settings?.clients then
        .settings.clients |= (map(del(.encryption)))
      else .
      end
    ))' "$CONFIG" > "$tmp" && mv "$tmp" "$CONFIG"

echo "==> Проставляю flow=xtls-rprx-vision для всех inbound VLESS клиентов..."
tmp="$(mktemp)"
jq '(.inbounds[]? | select(.protocol=="vless") | .settings.clients) |=
      (map(.flow = "xtls-rprx-vision"))' "$CONFIG" > "$tmp" && mv "$tmp" "$CONFIG"

echo "==> Проверяю, что privateKey и shortIds находятся ВНУТРИ realitySettings..."
have_priv=$(jq -r '(.inbounds[]? | select(.protocol=="vless") | .streamSettings.realitySettings.privateKey) // empty' "$CONFIG")
have_sid=$(jq -r '(.inbounds[]? | select(.protocol=="vless") | .streamSettings.realitySettings.shortIds[0]) // empty' "$CONFIG")
if [[ -z "$have_priv" || -z "$have_sid" ]]; then
  echo "❌ ВАЖНО: В realitySettings отсутствуют privateKey или shortIds. Исправьте вручную."
  exit 1
fi

echo "==> Проверяю синтаксис JSON..."
jq empty "$CONFIG" >/dev/null

echo "==> Сравниваю ключевые поля config.json ↔ server.py ..."
cfg_uuid=$(jq -r '(.inbounds[]? | select(.protocol=="vless") | .settings.clients[0].id) // empty' "$CONFIG")
cfg_sni=$(jq -r '(.inbounds[]? | select(.protocol=="vless") | .streamSettings.realitySettings.serverNames[0]) // empty' "$CONFIG")
cfg_sid=$(jq -r '(.inbounds[]? | select(.protocol=="vless") | .streamSettings.realitySettings.shortIds[0]) // empty' "$CONFIG")
cfg_port=$(jq -r '(.inbounds[]? | select(.protocol=="vless") | .port) // empty' "$CONFIG")

# Парсим константы из server.py
srv_domain=$(grep -E '^\s*DOMAIN\s*=' "$SERVER_PY" | sed -E 's/.*=\s*"[^\"]*"?/ &/; s/.*"([^"]*)".*/\1/')
srv_port=$(grep -E '^\s*PORT\s*=' "$SERVER_PY"   | awk -F= '{gsub(/ /,"",$2);print $2}')
srv_uuid=$(grep -E '^\s*UUID\s*=' "$SERVER_PY"   | sed -E 's/.*"([^"]*)".*/\1/')
srv_sni=$(grep -E '^\s*SNI\s*=' "$SERVER_PY"     | sed -E 's/.*"([^"]*)".*/\1/')
srv_sid=$(grep -E '^\s*SHORT_ID\s*=' "$SERVER_PY"| sed -E 's/.*"([^"]*)".*/\1/')
srv_pbk=$(grep -E '^\s*PUBLIC_KEY\s*=' "$SERVER_PY" | sed -E 's/.*"([^"]*)".*/\1/')

echo "  • config.json UUID:     $cfg_uuid"
echo "  • server.py   UUID:     $srv_uuid"
echo "  • config.json SNI:      $cfg_sni"
echo "  • server.py   SNI:      $srv_sni"
echo "  • config.json shortId:  $cfg_sid"
echo "  • server.py   shortId:  $srv_sid"
echo "  • config.json port:     $cfg_port"
echo "  • server.py   PORT:     $srv_port"
echo "  • server.py   DOMAIN:   $srv_domain"
echo "  • server.py   PUBLIC_KEY (pbk): $srv_pbk"
echo "  ⚠️  Публичный ключ (pbk) в config.json не хранится — сверить его здесь невозможно."

mismatch=0
[[ "$cfg_uuid" != "$srv_uuid" ]] && echo "❌ UUID не совпадает!" && mismatch=1
[[ "$cfg_sni"  != "$srv_sni"  ]] && echo "❌ SNI не совпадает!" && mismatch=1
[[ "$cfg_sid"  != "$srv_sid"  ]] && echo "❌ shortId не совпадает!" && mismatch=1
[[ "$cfg_port" != "$srv_port" ]] && echo "❌ PORT не совпадает!" && mismatch=1

if [[ $mismatch -ne 0 ]]; then
  echo "‼️ Обнаружены несоответствия между server.py и config.json — соединение будет рваться. Исправьте и запустите заново."
  exit 2
fi

echo "==> Перезапускаю Xray..."
systemctl restart xray
sleep 2
systemctl status xray --no-pager -l | head -n 30

echo "==> Проверяю, слушает ли Xray порт $cfg_port ..."
ss -tlnp | grep ":$cfg_port" || echo "⚠️ Порт $cfg_port не найден в LISTEN!"

echo "✅ Готово."
