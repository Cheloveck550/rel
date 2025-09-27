#!/usr/bin/env bash
set -euo pipefail

# === Настройки ===
DOMAIN="64.188.64.214"                     # твой IP
UUID="${UUID:-$(uuidgen)}"                 # генерим UUID автоматически
SNI="${SNI:-www.google.com}"               # маскирующий SNI
XRAY_PORT=443
APP_DIR="/opt/happvpn"

# === Установка пакетов ===
apt-get update
apt-get install -y curl wget unzip jq ufw nginx python3 python3-venv

# === Установка Xray-core ===
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install

# Генерация ключей Reality
PRIV=$(xray x25519 | awk '/Private key/{print $4}')
PUB=$(xray x25519 -p "${PRIV}" | awk '/Public key/{print $4}')
SHORTID=$(head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n')

mkdir -p /usr/local/etc/xray

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
        "privateKey": "${PRIV}",
        "shortIds": ["${SHORTID}"]
      }
    },
    "sniffing": { "enabled": true, "destOverride": ["http", "tls"] }
  }],
  "outbounds": [{ "protocol": "freedom" }, { "protocol": "blackhole" }]
}
EOF

systemctl enable xray
systemctl restart xray

# === Сохраняем параметры для FastAPI ===
mkdir -p /etc/xray
cat >/etc/xray/reality.env <<EOF
DOMAIN=${DOMAIN}
UUID=${UUID}
PUBKEY=${PUB}
SHORTID=${SHORTID}
SNI=${SNI}
XRAY_PORT=${XRAY_PORT}
EOF

# === Установка Python-приложения ===
mkdir -p "${APP_DIR}"
python3 -m venv "${APP_DIR}/venv"
source "${APP_DIR}/venv/bin/activate"
pip install --upgrade pip wheel
pip install fastapi uvicorn[standard] aiosqlite aiogram aiocryptopay yoomoney
deactivate

# systemd unit для FastAPI (server.py)
cat >/etc/systemd/system/happvpn-api.service <<EOF
[Unit]
Description=HappVPN FastAPI
After=network-online.target

[Service]
User=root
WorkingDirectory=${APP_DIR}
Environment=HAPPVPN_DB=${APP_DIR}/bot_database.db
Environment=HAPPVPN_DOMAIN=${DOMAIN}
ExecStart=${APP_DIR}/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable happvpn-api
systemctl restart happvpn-api

# === Настройка Nginx для проксирования FastAPI на 80 ===
cat >/etc/nginx/sites-available/happvpn.conf <<EOF
server {
  listen 80 default_server;
  listen [::]:80 default_server;
  server_name _;

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
  }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/happvpn.conf /etc/nginx/sites-enabled/happvpn.conf
nginx -t && systemctl reload nginx

# === Firewall ===
ufw allow 80/tcp || true
ufw allow 443/tcp || true

echo "======================================="
echo "Установка завершена!"
echo "DOMAIN=${DOMAIN}"
echo "UUID=${UUID}"
echo "PUBKEY=${PUB}"
echo "SHORTID=${SHORTID}"
echo "SNI=${SNI}"
echo "XRAY_PORT=${XRAY_PORT}"
echo "======================================="
