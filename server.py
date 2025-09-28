import aiosqlite
import base64
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

app = FastAPI()

# ==================== Конфигурация ====================
DOMAIN = "64.188.64.214"
PORT = 443
UUID = "29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"
SNI = "www.google.com"
SHORT_ID = "ba4211bb433df45d"
PUBLIC_KEY = "m7n-24tMvfTdp2-2sr-vAaM3t9NzGDpTNrva6xM6-ls"

# ==================== Генератор ссылки ====================
def generate_vless_link() -> str:
    """
    Генерация VLESS-ссылки без flow (для стабильности)
    """
    return (
        f"vless://{UUID}@{DOMAIN}:{PORT}"
        f"?encryption=none"
        f"&security=reality"
        f"&sni={SNI}"
        f"&fp=chrome"
        f"&pbk={PUBLIC_KEY}"
        f"&sid={SHORT_ID}"
        f"&type=tcp"
        f"&headerType=none"
        f"#Pro100VPN"
    )

# ==================== Роуты ====================
@app.get("/subs/{token}", response_class=HTMLResponse)
async def subscription_page(token: str):
    """
    HTML-страница с кнопкой
    """
    async with aiosqlite.connect("bot_database.db") as db:
        cursor = await db.execute("SELECT 1 FROM subscriptions WHERE token=?", (token,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Подписка не найдена")

    sub_link = f"http://{DOMAIN}/sub/{token}"

    html = f"""
    <html>
    <head><title>Подписка Pro100VPN</title></head>
    <body style="font-family:Arial; text-align:center; margin-top:50px;">
        <h2>Подписка Pro100VPN</h2>
        <p>Нажмите кнопку ниже, чтобы добавить сервер в HappVPN:</p>
        <a href="happ://add/{sub_link}">
            <button style="padding:10px 20px; font-size:16px;">Добавить в HappVPN</button>
        </a>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def subscription_file(token: str):
    """
    Subscription endpoint → HappVPN будет видеть подписку
    """
    async with aiosqlite.connect("bot_database.db") as db:
        cursor = await db.execute("SELECT 1 FROM subscriptions WHERE token=?", (token,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Подписка не найдена")

    vless = generate_vless_link()
    # HappVPN ждёт Base64 кодировку
    encoded = base64.b64encode(vless.encode()).decode()
    return PlainTextResponse(content=encoded)
