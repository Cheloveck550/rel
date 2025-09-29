#!/usr/bin/env bash
set -euo pipefail

CFG="/usr/local/etc/xray/config.json"
HOST="64.188.64.214"           # host в ссылке = адрес твоего сервера
FP="chrome"                    # можно поменять на randomized

if ! command -v jq >/dev/null 2>&1; then
  apt-get update && apt-get install -y jq
fi

uuid=$(jq -r '.inbounds[] | select(.protocol=="vless") | .settings.clients[0].id' "$CFG")
port=$(jq -r '.inbounds[] | select(.protocol=="vless") | .port' "$CFG")
sni=$(jq -r '.inbounds[] | select(.protocol=="vless") | .streamSettings.realitySettings.serverNames[0] // .inbounds[]?.streamSettings?.realitySettings?.serverName' "$CFG")
sid=$(jq -r '.inbounds[] | select(.protocol=="vless") | .streamSettings.realitySettings.shortIds[0] // .inbounds[]?.streamSettings?.realitySettings?.shortId' "$CFG")
priv=$(jq -r '.inbounds[] | select(.protocol=="vless") | .streamSettings.realitySettings.privateKey' "$CFG")

if [[ -z "$uuid" || -z "$port" || -z "$sni" || -z "$sid" || -z "$priv" ]]; then
  echo "❌ Не удалось извлечь один из параметров (uuid/port/sni/sid/privateKey)."
  exit 1
fi

pbk=$(xray x25519 -i "$priv" | sed -n 's/^PublicKey: //p')
if [[ -z "$pbk" ]]; then
  echo "❌ Не удалось получить PublicKey через xray x25519 -i"
  exit 2
fi

echo "UUID:   $uuid"
echo "PORT:   $port"
echo "SNI:    $sni"
echo "SID:    $sid"
echo "PBK:    $pbk"

echo
echo "=== VLESS ссылки, которые ДОЛЖЕН принимать сервер ==="
link_base="vless://$uuid@$HOST:$port?type=tcp&security=reality&encryption=none&fp=$FP&sni=$sni&pbk=$pbk&sid=$sid"
echo "с flow:    ${link_base}&flow=xtls-rprx-vision#Pro100VPN"
echo "без flow:  ${link_base}#Pro100VPN"
