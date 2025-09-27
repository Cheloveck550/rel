#!/usr/bin/env bash
set -e

# Папка под конфиг
sudo mkdir -p /usr/local/etc/xray

# Записываем config.json
sudo tee /usr/local/etc/xray/config.json > /dev/null <<EOF
{
  "log": {
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log",
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [
          {
            "id": "29e9cdce-dff1-49f4-b94b-b26fa32a9a6b",
            "flow": "xtls-rprx-vision"
          }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "www.google.com:443",
          "serverNames": ["www.google.com"],
          "privateKey": "iEtW0aEEXGlQsJ4gD962DeUNx0L7NWBuhPBlUVB1XfGU",
          "shortIds": ["ba4211bb433df45d"]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls"]
      }
    }
  ],
  "outbounds": [
    { "protocol": "freedom" },
    { "protocol": "blackhole" }
  ]
}
EOF

# Перезапускаем Xray
sudo systemctl restart xray

echo "✅ Конфиг записан и Xray перезапущен!"
sudo systemctl status xray --no-pager | head -n 10
