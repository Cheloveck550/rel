from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
import sqlite3

app = FastAPI()

DB_FILE = "/root/rel/bot_database.db"
SERVER_IP = "64.188.64.214"  # твой сервер
SERVER_PORT = 443
SNI = "www.google.com"

# 🔑 ключи для reality
PUBLIC_KEY = "m7n-24tmvfTdp2-Szr-vAaM3t9NzGDpTNrva6xM6-ls"
SHORT_ID = "ba4211bb433df45d"


def db_connect():
    return sqlite3.connect(DB_FILE)


def get_vpn_link(user_id: int) -> str:
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT vpn_link FROM vpn_links WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return row[0]


@app.get("/sub/{token}", response_class=PlainTextResponse)
def sub_link(token: str):
    """
    Отдаёт VLESS ссылку в виде текста (для отладки/прямой проверки)
    """
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM subscriptions WHERE token=?", (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Subscription not found")

    user_id = row[0]
    vpn_link = get_vpn_link(user_id)
    if not vpn_link:
        raise HTTPException(status_code=404, detail="VPN link not found for this user")

    return vpn_link


@app.get("/subs/{token}", response_class=HTMLResponse)
def subs_page(token: str):
    """
    HTML-страница с кнопкой для открытия HappVPN
    """
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM subscriptions WHERE token=?", (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Subscription not found")

    user_id = row[0]
    vpn_link = get_vpn_link(user_id)
    if not vpn_link:
        raise HTTPException(status_code=404, detail="VPN link not found for this user")

    html = f"""
    <html>
        <head>
            <title>VPN подписка</title>
        </head>
        <body style="text-align:center; font-family:Arial">
            <h2>Подписка Pro100VPN</h2>
            <p>Нажмите кнопку ниже, чтобы добавить сервер в HappVPN:</p>
            <a href="{vpn_link}">
                <button style="padding:10px 20px; font-size:16px;">Добавить в HappVPN</button>
            </a>
        </body>
    </html>
    """
    return html
