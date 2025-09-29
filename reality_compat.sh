#!/usr/bin/env bash
set -euo pipefail

CFG="/usr/local/etc/xray/config.json"
BACKUP="/usr/local/etc/xray/config.json.bak.$(date +%s)"

echo "==> Бэкап: $BACKUP"
cp -a "$CFG" "$BACKUP"

# текущее shortId и укороченная версия
SID="$(jq -r '.inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.shortIds[0] // .inbounds[]|select(.protocol=="vless")|.streamSettings.realitySettings.shortId' "$CFG")"
SID8="${SID:0:8}"

jq --arg sid8 "$SID8" '
  .inbounds |= (map(
    if .protocol=="vless" then
      .streamSettings.realitySettings.serverNames = ["www.google.com"]
      | .streamSettings.realitySettings += { "dest": "www.google.com:443" }
      | .streamSettings.realitySettings.shortIds = [$sid8]
    else . end
  ))
' "$BACKUP" > "$CFG"

chmod 644 "$CFG"
systemctl restart xray
sleep 1

echo "==> Статус Xray:"
systemctl status xray --no-pager -l | head -n 20
echo "==> Порт 443:"
ss -tlnp | grep ':443' || (echo '⚠️ порт 443 не слушается' && exit 1)
echo "==> Готово."
