import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

# Инициализация API
app = FastAPI()

# Файл базы данных
DB_FILE = "bot_database.db"

# ---------------- Конфигурация Xray ---------------- #
UUID = "29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"   # твой UUID
SERVER_NAME = "www.google.com"                 # SNI / serverName
DOMAIN = "64.188.64.214"                       # IP или домен сервера
PUBLIC_KEY = "m7n-24tMvfTdp2-2sr-vAaM3t9NzGDpTNrva6xM6-ls"  # твой PublicKey
SHORT_ID = "ba4211bb433df45d"                  # ShortID из config.json
PORT = 443                                     # порт Xray
# --------------------------------------------------- #


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
    Выдаёт ссылку для HappVPN, если токен найден в базе.
    """
    if not is_active_subscription(token):
        raise HTTPException(status_code=404, detail="VPN link not found for this user")

    # Генерация VLESS-ссылки
    vless_link = (
        f"vless://{UUID}@{DOMAIN}:{PORT}"
        f"?type=tcp&security=reality&fp=random"
        f"&sni={SERVER_NAME}&pbk={PUBLIC_KEY}&sid={SHORT_ID}"
        f"&flow=xtls-rprx-vision#Pro100VPN"
    )

    # Перенаправляем в HappVPN
    happ_link = f"happ://add/{vless_link}"
    return RedirectResponse(url=happ_link)


@app.get("/")
async def root():
    """Проверка, что API работает."""
    return {"status": "ok", "message": "HappVPN API is running"}
