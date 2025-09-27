#!/usr/bin/env bash
set -euo pipefail

DOMAIN="64.188.64.214"
UUID="29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"
PRIVKEY="iEtW0aEEXGlQsJ4gD962DeUNx0L7NWBuhPBlUVB1XfGU"
PUBKEY="Gv3gbcD10M8gKdyqIRx8t_AkEh7yAjTjrjG2N62zHu"
SHORTID="ba4211bb433df45d"
SNI="www.google.com"
XRAY_PORT=443

cat >/usr/local/etc/xray/config.json <<EOF
{
  "log": { "access": "/var/log/xray/access.log", "error": "/var/log/xray/error.log", "loglevel": "warning" },
  "inbounds": [{
    "port": ${XRAY_PORT},
    "protocol": "vless",
    "settings": {
      "clients": [{ "id": "${UUID}", "flow": "xtls-rprx-vision" }],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "show": false,
        "dest": "${SNI}:443",
        "serverNames": ["${SNI}"],
        "privateKey": "${PRIVKEY}",
        "shortIds": ["${SHORTID}"]
      }
    },
    "sniffing": { "enabled": true, "destOverride": ["http", "tls"] }
  }],
  "outbounds": [{ "protocol": "freedom" }, { "protocol": "blackhole" }]
}
EOF

systemctl restart xray
echo "✅ Xray config обновлён!"
