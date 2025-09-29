#!/usr/bin/env bash
set -euo pipefail

CFG="/usr/local/etc/xray/config.json"
BACKUP="/usr/local/etc/xray/config.json.bak.$(date +%s)"
cp -a "$CFG" "$BACKUP"

jq '
  .inbounds |= (map(
    if .protocol=="vless" then
      .streamSettings.realitySettings.serverNames = ["www.google.com"]
      | .streamSettings.realitySettings += { "dest": "www.google.com:443" }
    else .
    end
  ))
' "$BACKUP" > "$CFG"

chmod 644 "$CFG"
systemctl restart xray
sleep 1
systemctl status xray --no-pager -l | head -n 20

echo "==> Проверка 443…"
ss -tlnp | grep ':443' || (echo '⚠️ порт 443 не слушается' && exit 1)

echo "==> Новый SNI/DEST применены. Теперь повтори импорт."
