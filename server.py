import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

app = FastAPI()

# ==================== Конфигурация (должна совпадать с /usr/local/etc/xray/config.json) ====================
DOMAIN = "64.188.64.214"                             # публичный IP сервера (куда стучится клиент)
PORT   = 443                                         # порт inbound VLESS (из config.json)
UUID   = "29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"      # clients[0].id (из config.json)
SNI    = "www.google.com"                            # realitySettings.serverNames[0] (из config.json)
SHORT_ID   = "ba4211bb433df45d"                      # realitySettings.shortIds[0] (из config.json)
PUBLIC_KEY = "m7n-24tMvfTdp2-2sr-vAaM3t9NzGDpTNrva6xM6-ls"  # pbk из x25519 (в config.json НЕ хранится)

DB_PATH = "bot_database.db"   # локально рядом с сервером

# ==================== Генерация VLESS (с flow=xtls-rprx-vision для полной совместимости) ====================
def make_vless_url() -> str:
    # Важно: параметры должны соответствовать Reality-конфигу сервера.
    # Если HappVPN всё ещё рвёт соединение, можно временно убрать "&flow=xtls-rprx-vision"
    return (
        f"vless://{UUID}@{DOMAIN}:{PORT}"
        f"?encryption=none"
        f"&security=reality"
        f"&flow=xtls-rprx-vision"
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
async def subs_page(token: str):
    # Проверяем, что токен существует
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM subscriptions WHERE token=?", (token,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Подписка не найдена")

    # Ссылка для HappVPN: happ://add/{config_url}, где config_url отдаёт plain text с vless://
    config_url = f"http://{DOMAIN}/sub/{token}"
    happ_deeplink = f"happ://add/{config_url}"

    html = f"""
    <html>
      <head><title>Подписка Pro100VPN</title></head>
      <body style="font-family:Arial; text-align:center; margin-top:48px;">
        <h2>Подписка Pro100VPN</h2>
        <p>Нажмите кнопку ниже, чтобы добавить сервер в HappVPN:</p>
        <a href="{happ_deeplink}">
          <button style="padding:10px 20px; font-size:16px;">Добавить в HappVPN</button>
        </a>
        <p style="margin-top:16px; color:#777">Если кнопка не срабатывает — скопируйте ссылку и откройте вручную:<br>{happ_deeplink}</p>
      </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def subscription_plain(token: str):
    # Этот endpoint возвращает САМИ строки подписки (plain text).
    # Для одной строки — просто один vless:// (без base64).
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM subscriptions WHERE token=?", (token,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Подписка не найдена")

    vless = make_vless_url()
    # Если захотите несколько серверов — верните несколько строк, по одной ссылке на строку.
    return PlainTextResponse(vless + "\n")
