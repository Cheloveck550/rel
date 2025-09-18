#!/bin/bash
set -e

echo "[*] Чиним XRay конфиг и запускаем сервис..."

mkdir -p /usr/local/etc/xray

cat > /usr/local/etc/xray/config.json <<EOF
{
  "inbounds": [
    {
      "port": 8443,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "4f09a57e-76c7-497c-a878-db737cd6a5b5",
            "flow": ""
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "www.cloudflare.com:443",
          "xver": 0,
          "serverNames": [
            "www.cloudflare.com"
          ],
          "privateKey": "4CRoGnZdT15MMRx81RzXAieoa1HHzLXUnvClo10q1mQ",
          "shortIds": [
            "09abf7341e035c7d"
          ]
        }
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "freedom"
    }
  ]
}
EOF

echo "[*] Проверяем конфиг..."
/usr/local/bin/xray run -test -config /usr/local/etc/xray/config.json

echo "[*] Перезапускаем XRay..."
systemctl restart xray
systemctl enable xray

echo "[+] XRay перезапущен успешно!"
systemctl status xray --no-pager

