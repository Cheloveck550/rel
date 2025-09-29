#!/bin/bash
set -e

# === Константы ===
UUID="10dad63d-53ac-4136-a725-eb0b75164ed5"
PRIV="SEqS8SST99euUoBDqVYQYjq-UEoA9EV4oHhNQqsHs"
PBK="wr6EkbDM_3SDXL_6zh4MPH_aB3Gb1tBU205a2k12kM"
SID="ebc55ee42cdea080"
DOMAIN="64.188.64.214"
SNI="www.google.com"
XRAY_CONFIG="/usr/local/etc/xray/config.json"

echo "→ Бэкапим $XRAY_CONFIG ..."
cp $XRAY_CONFIG $XRAY_CONFIG.bak.$(date +%s) || true

# === Генерируем новый конфиг ===
cat > $XRAY_CONFIG <<JSON
{
  "inbounds": [
    {
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "$UUID",
            "flow": "xtls-rprx-vision",
            "encryption": "none"
          }
        ]
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "$SNI:443",
          "xver": 0,
          "serverNames": ["$SNI"],
          "privateKey": "$PRIV",
          "shortIds": ["$SID"]
        }
      }
    }
  ],
  "outbounds": [
    { "protocol": "freedom" },
    { "protocol": "blackhole", "tag": "blocked" }
  ]
}
JSON

echo "→ Перезапускаем Xray ..."
systemctl restart xray

sleep 2
echo "→ Проверяем порт 443:"
ss -tlnp | grep ":443" || echo "✖ Порт 443 не слушается"

echo
echo "== Готовые VLESS ссылки =="

echo "с flow:"
echo "vless://$UUID@$DOMAIN:443?type=tcp&security=reality&encryption=none&fp=chrome&sni=$SNI&pbk=$PBK&sid=$SID&flow=xtls-rprx-vision#Pro100VPN"
echo
echo "без flow:"
echo "vless://$UUID@$DOMAIN:443?type=tcp&security=reality&encryption=none&fp=chrome&sni=$SNI&pbk=$PBK&sid=$SID#Pro100VPN"

echo
echo "== Deep-link для HappVPN (с flow) =="
LINK="vless://$UUID@$DOMAIN:443?type=tcp&security=reality&encryption=none&fp=chrome&sni=$SNI&pbk=$PBK&sid=$SID&flow=xtls-rprx-vision#Pro100VPN"
echo "happ://add/$(python3 -c "import urllib.parse; print(urllib.parse.quote('$LINK'))")"

echo
echo "✔ Готово."
