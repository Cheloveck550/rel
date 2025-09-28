import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

# ---------------- Конфигурация Xray ---------------- #
UUID = "29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"   # твой UUID
SERVER_NAME = "www.google.com"                 # SNI / serverName
DOMAIN = "64.188.64.214"                       # IP или домен сервера
PUBLIC_KEY = "m7n-24tMvfTdp2-2sr-vAaM3t9NzGDpTNrva6xM6-ls"  # твой PublicKey
SHORT_ID = "ba4211bb433df45d"                  # ShortID из config.json
PORT = 443                                     # порт Xray
DB_FILE = "bot_database.db"                    # твоя база
# --------------------------------------------------- #

app = FastAPI()


def db_connect():
    """Подключение к SQLite."""
    return sqlite3.connect(DB_FILE)


def is_active_subscription(token: str) -> bool:
    """Проверяет, есть ли активная подписка с данным токеном."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT expires_at FROM subscriptions WHERE token = ?", (token,))
    row = cur.fetchone()
    conn.close()
    return row is not None


@app.get("/subs/{token}")
async def subs_page(token: str):
    """
    Страница с двумя ссылками (с flow и без).
    """
    if not is_active_subscription(token):
        raise HTTPException(status_code=404, detail="VPN link not found for this user")

    # VLESS-ссылка с flow
    vless_flow = (
        f"vless://{UUID}@{DOMAIN}:{PORT}"
        f"?type=tcp&security=reality&fp=random"
        f"&sni={SERVER_NAME}&pbk={PUBLIC_KEY}&sid={SHORT_ID}"
        f"&flow=xtls-rprx-vision#Pro100VPN"
    )

    # VLESS-ссылка без flow
    vless_noflow = (
        f"vless://{UUID}@{DOMAIN}:{PORT}"
        f"?type=tcp&security=reality&fp=random"
        f"&sni={SERVER_NAME}&pbk={PUBLIC_KEY}&sid={SHORT_ID}"
        f"#Pro100VPN"
    )

    # Формируем кнопки для HappVPN
    html = f"""
    <html>
        <head><title>Подписка Pro100VPN</title></head>
        <body style="text-align:center; font-family:Arial;">
            <h2>Подписка Pro100VPN</h2>
            <p>Выберите вариант подключения:</p>
            <a href="happ://add/{vless_flow}">
                <button style="padding:10px; margin:5px;">Добавить (с flow)</button>
            </a>
            <a href="happ://add/{vless_noflow}">
                <button style="padding:10px; margin:5px;">Добавить (без flow)</button>
            </a>
        </body>
    </html>
    """

    return HTMLResponse(content=html)


@app.get("/")
async def root():
    """Проверка, что API работает."""
    return {"status": "ok", "message": "HappVPN API is running"}
