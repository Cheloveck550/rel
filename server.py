from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
import sqlite3

app = FastAPI()

DB_FILE = "/root/rel/bot_database.db"
SERVER_IP = "64.188.64.214"  # IP твоего сервера
SERVER_PORT = 443
SNI = "www.google.com"

def db_connect():
    return sqlite3.connect(DB_FILE)


@app.get("/sub/{token}", response_class=PlainTextResponse)
def get_subscription(token: str):
    """
    Отдаёт VLESS-ссылку для HappVPN
    """
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT uuid, public_key, short_id FROM subscriptions WHERE token=?", (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Subscription not found")

    uuid, public_key, short_id = row

    # Формируем VLESS Reality ссылку
    link = (
        f"vless://{uuid}@{SERVER_IP}:{SERVER_PORT}?"
        f"type=tcp&security=reality&pbk={public_key}"
        f"&sni={SNI}&flow=xtls-rprx-vision&sid={short_id}#Pro100VPN"
    )
    return link


@app.get("/subs/{token}", response_class=HTMLResponse)
def subs_page(token: str):
    """
    HTML-страница с кнопкой добавления в HappVPN
    """
    # Проверим, есть ли такая подписка
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM subscriptions WHERE token=?", (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Subscription not found")

    html = f"""
    <html>
        <head>
            <title>VPN подписка</title>
        </head>
        <body style="text-align:center; font-family:Arial">
            <h2>Подписка Pro100VPN</h2>
            <p>Нажмите кнопку ниже, чтобы добавить сервер в HappVPN:</p>
            <a href="http://{SERVER_IP}/sub/{token}">
                <button style="padding:10px 20px; font-size:16px;">Добавить в HappVPN</button>
            </a>
        </body>
    </html>
    """
    return html
