from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
import sqlite3

app = FastAPI()

DB_FILE = "/root/rel/bot_database.db"
SERVER_IP = "64.188.64.214"  # IP твоего сервера


def db_connect():
    return sqlite3.connect(DB_FILE)


@app.get("/sub/{token}", response_class=PlainTextResponse)
def get_subscription(token: str):
    conn = db_connect()
    cursor = conn.cursor()

    # 1. Найдём user_id по токену
    cursor.execute("SELECT user_id FROM subscriptions WHERE token=?", (token,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Subscription not found")

    user_id = row[0]

    # 2. Получим vpn_link для этого user_id
    cursor.execute("SELECT vpn_link FROM vpn_links WHERE user_id=?", (user_id,))
    vpn_row = cursor.fetchone()
    conn.close()

    if not vpn_row:
        raise HTTPException(status_code=404, detail="VPN link not found for this user")

    vpn_link = vpn_row[0]
    return vpn_link


@app.get("/subs/{token}", response_class=HTMLResponse)
def subs_page(token: str):
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
