from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import random
import string

app = FastAPI()

# Константы для конфигурации VLESS+Reality
CLIENT_UUID = "4f09a57e-76c7-497c-a878-db737cd6a5b5"
REALITY_PUBLIC_KEY = "jrw_17a0eN01fEvg14NVze2iPF2ddpgdDwU_Y90-TEA"
REALITY_SHORT_ID = "sLeXmgrNQDKmyM-2Bf1f6_qek30XVQMqALy1B0bHVp4"
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


@app.get("/configs/{token}.json")
async def get_config(token: str):
    config = {
        "version": 1,
        "nodes": [
            {
                "type": "vless",
                "name": "Pro100VPN",
                "server": SERVER_IP,
                "port": 443,
                "uuid": CLIENT_UUID,
                "security": "reality",
                "tls": True,
                "flow": "",
                "realitySettings": {
                    "publicKey": REALITY_PUBLIC_KEY,
                    "shortId": REALITY_SHORT_ID,
                    "serverName": "www.cloudflare.com"
                }
            }
        ]
    }
    return JSONResponse(content=config)
