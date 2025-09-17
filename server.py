from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import random
import string
import base64

app = FastAPI()

# Константы для конфигурации VLESS+Reality
CLIENT_UUID = "4f09a57e-76c7-497c-a878-db737cd6a5b5"
REALITY_PUBLIC_KEY = "jrw_17a0eN01fEvg14NVze2iPF2ddpgdDwU_Y90-TEA"
REALITY_SHORT_ID = "bb45e9b132a66a07"
SERVER_IP = "193.58.122.47"


# Генерация случайного токена
def generate_token():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=22))


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    token = generate_token()
    json_url = f"http://{SERVER_IP}/configs/{token}.json"
    happvpn_url = f"happ://add/{json_url}"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Pro100VPN</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-white flex items-center justify-center h-screen">
        <div class="bg-gray-800 shadow-xl rounded-2xl p-8 w-96 text-center">
            <h1 class="text-2xl font-bold mb-4">🚀 Pro100VPN</h1>
            <p class="mb-6 text-gray-300">Ваш персональный VPN-конфиг готов!</p>
            
            <a href="{happvpn_url}" 
               class="block bg-blue-600 hover:bg-blue-700 text-white py-3 px-5 rounded-xl font-semibold transition">
               🔑 Открыть в HappVPN
            </a>
            
            <p class="mt-6 text-sm text-gray-400">Если кнопка не работает, используйте ссылку вручную:</p>
            <p class="text-xs text-blue-400 break-words">{happvpn_url}</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token: str):
    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Pro100VPN - Подписка</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-900 text-white flex items-center justify-center h-screen">
        <div class="bg-gray-800 shadow-xl rounded-2xl p-8 w-96 text-center">
            <h1 class="text-2xl font-bold mb-4">🚀 Pro100VPN</h1>
            <p class="mb-4">Токен: <code>{token}</code></p>
            <p class="mb-6 text-green-400">Статус: Активна</p>
            
            <a href="happ://add/http://{SERVER_IP}/configs/{token}.json" 
               class="block bg-green-600 hover:bg-green-700 text-white py-3 px-5 rounded-xl font-semibold transition">
               ✅ Добавить в HappVPN
            </a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ИСПРАВЛЯЕМ ЭТОТ РОУТ - возвращаем PlainTextResponse с Base64!
@app.get("/configs/{token}.json", response_class=PlainTextResponse)
async def get_config(token: str):
    # Генерируем VLESS ссылку
    vless_link = (
        f"vless://{CLIENT_UUID}@{SERVER_IP}:443"
        f"?encryption=none&security=reality&fp=chrome"
        f"&sni=www.cloudflare.com&pbk={REALITY_PUBLIC_KEY}&sid={REALITY_SHORT_ID}&type=tcp"
        f"#Pro100VPN"
    )
    
    # Кодируем в Base64 (HappVPN ожидает именно это!)
    subscription = base64.b64encode(vless_link.encode()).decode()
    
    return subscription


@app.get("/test")
async def test():
    return {"status": "ok", "message": "Server is working!"}
