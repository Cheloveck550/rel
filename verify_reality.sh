#!/usr/bin/env bash
set -euo pipefail

CFG="/usr/local/etc/xray/config.json"
HOST="64.188.64.214"   # host в ссылке = адрес твоего сервера
FP="chrome"

XRAY="/usr/local/bin/xray"
if ! [ -x "$XRAY" ]; then XRAY="$(command -v xray || true)"; fi
if ! [ -x "${XRAY:-/nonexistent}" ]; then
  echo "❌ Не найден xray (ожидался /usr/local/bin/xray)"; exit 1
fi

uuid=$(jq -r '.inbounds[]|select(.protocol=="vless")|.settings.clients[0].id' "$CFG")
port=$(jq -r '.inbounds[]|select(.protocol=="vless")|.port' "$CFG")
sni=$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.serverNames[0] // .inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.serverName' "$CFG")
sid=$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.shortIds[0] // .inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.shortId' "$CFG")
priv=$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.privateKey' "$CFG")

out="$("$XRAY" x25519 -i "$priv" 2>&1 || true)"
pbk="$(printf '%s\n' "$out" | sed -n 's/.*PublicKey[: ]\s*//p; s/.*Password[: ]\s*//p' | head -n1)"

echo "UUID: $uuid"
echo "PORT: $port"
echo "SNI : $sni"
echo "SID : $sid"
echo "PBK : $pbk"
echo
base="vless://$uuid@$HOST:$port?type=tcp&security=reality&encryption=none&fp=$FP&sni=$sni&pbk=$pbk&sid=$sid"
echo "с flow   : ${base}&flow=xtls-rprx-vision#Pro100VPN"
echo "без flow : ${base}#Pro100VPN"
