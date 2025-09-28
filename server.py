import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI()

# ==================== Конфигурация ====================
DOMAIN = "64.188.64.214"   # IP сервера
PORT = 443                 # Порт Xray
USER_ID = "29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"  # UUID клиента
SNI = "www.google.com"     # Серверное имя
SHORT_ID = "ba4211bb433df45d"  # shortId из config.json
PUBLIC_KEY = "m7n-24tMvfTdp2-2sr-vAaM3t9NzGDpTNrva6xM6-ls"


# ==================== Генератор ссылки ====================
def generate_vless_link(token: str) -> str:
    """
    Генерирует VLESS ссылку для HappVPN
    """
    vless_url = (
        f"vless://{USER_ID}@{DOMAIN}:{PORT}"
        f"?encryption=none"
        f"&security=reality"
        f"&flow=xtls-rprx-vision"
        f"&sni={SNI}"
        f"&fp=chrome"
        f"&pbk={PUBLIC_KEY}"
        f"&sid={SHORT_ID}"
        f"&type=tcp"
        f"&headerType=none"
        f"#{DOMAIN}-Pro100VPN"
    )
    # HappVPN требует обёртку
    return f"happ://add/{vless_url}"

# ==================== Роуты ====================
@app.get("/subs/{token}", response_class=HTMLResponse)
async def subscription_page(token: str):
    """
    Страница с кнопкой "Добавить в HappVPN"
    """
    async with aiosqlite.connect("bot_database.db") as db:
        cursor = await db.execute("SELECT 1 FROM subscriptions WHERE token=?", (token,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Подписка не найдена")

    link = generate_vless_link(token)

    html = f"""
    <html>
    <head><title>Подписка Pro100VPN</title></head>
    <body style="font-family:Arial; text-align:center; margin-top:50px;">
        <h2>Подписка Pro100VPN</h2>
        <p>Нажмите кнопку ниже, чтобы добавить сервер в HappVPN:</p>
        <a href="{link}">
            <button style="padding:10px 20px; font-size:16px;">Добавить в HappVPN</button>
        </a>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/sub/{token}")
async def get_vless(token: str):
    """
    API для получения чистой VLESS ссылки
    """
    async with aiosqlite.connect("bot_database.db") as db:
        cursor = await db.execute("SELECT 1 FROM subscriptions WHERE token=?", (token,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="VPN link not found for this user")

    return {"link": generate_vless_link(token)}
