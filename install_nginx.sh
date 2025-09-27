#!/usr/bin/env bash
set -euo pipefail

API_PORT=8000
APP_DIR="/root/rel"
SERVICE_NAME="happvpn-api"

echo "🔧 Устанавливаем nginx..."
sudo apt update
sudo apt install -y nginx

echo "🔧 Создаём конфиг nginx..."
NGINX_CONF="/etc/nginx/sites-available/happvpn.conf"
sudo tee $NGINX_CONF > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:${API_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF

echo "🔗 Включаем конфиг..."
sudo ln -sf $NGINX_CONF /etc/nginx/sites-enabled/happvpn.conf
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl enable nginx
sudo systemctl restart nginx

echo "⚙️ Создаём systemd сервис для API..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
sudo tee $SERVICE_FILE > /dev/null <<EOF
[Unit]
Description=HappVPN API
After=network.target

[Service]
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/uvicorn server:app --host 127.0.0.1 --port ${API_PORT}
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "🔄 Перезапускаем systemd..."
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}

echo "✅ Всё готово!"
echo "API теперь доступен по адресу: http://$(curl -s ifconfig.me)/subs/<ваш_токен>"
