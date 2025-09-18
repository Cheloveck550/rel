#!/usr/bin/env python3
# server.py
# FastAPI server для Pro100VPN (отдаёт Base64 VLESS+Reality подписки + красивую страницу)
#
# Перед запуском: убедись, что VLESS_UUID, REALITY_PUBLIC_KEY и REALITY_SHORT_ID
# совпадают с теми, что в конфиге XRay (в /usr/local/etc/xray/config.json).

import os
import sqlite3
import base64
import asyncio
import random
import string
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse

# ---------------- CONFIG ----------------
DB_PATH = os.environ.get("PRO100VPN_DB_PATH", os.path.join(os.getcwd(), "bot_database.db"))
DOMAIN = os.environ.get("PRO100VPN_DOMAIN", "193.58.122.47")  # IP или домен
SERVER_IP = DOMAIN
SERVER_PORT = int(os.environ.get("PRO100VPN_VLESS_PORT", "8443"))

# ВАЖНО: поменяй на UUID, который прописан в XRay (inbound clients)
VLESS_UUID = os.environ.get("PRO100VPN_VLESS_UUID", "4f09a57e-76c7-497c-a878-db737cd6a5b5")

# Reality keys (те, что ты сгенерировал)
REALITY_PUBLIC_KEY = os.environ.get("PRO100VPN_REALITY_PUBKEY", "jrw_17a0eN01fEvg14NVze2iPF2ddpgdDwU_Y90-TEA")
REALITY_SHORT_ID = os.environ.get("PRO100VPN_REALITY_SHORTID", "sLeXmgrNQDKmyM-2Bf1f6_qek30XVQMqALy1B0bHVp4")
REALITY_SNI = os.environ.get("PRO100VPN_REALITY_SNI", "www.cloudflare.com")

CLEANUP_INTERVAL = 300  # фон. задача — чистка (сек)

app = FastAPI(title="Pro100VPN subscription server (VLESS+Reality)")

# ---------------- DB helpers ----------------
def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_tables():
    with db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                token TEXT PRIMARY KEY,
                user_id INTEGER,
                expires_at TEXT
            )
        """)
        conn.commit()

def parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
    except Exception:
        try:
            if dt_str.endswith("Z"):
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            else:
                # fallback
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def is_active_subscription(token: str) -> Optional[Tuple[int, Optional[datetime]]]:
    """
    Возвращает (user_id, expires_at) если подписка найдена (expires_at может быть None).
    Если нет записи — возвращает None.
    """
    with db_conn() as conn:
        cur = conn.execute("SELECT user_id, expires_at FROM subscriptions WHERE token = ?", (token,))
        row = cur.fetchone()
        if not row:
            return None
        exp = parse_iso(row["expires_at"])
        return (row["user_id"], exp)

# ---------------- Background cleanup ----------------
async def periodic_cleanup():
    """Удаляем просроченные подписки (необязательно) — и просто держим БД аккуратной."""
    while True:
        try:
            with db_conn() as conn:
                cur = conn.execute("SELECT token, expires_at FROM subscriptions")
                rows = cur.fetchall()
                for r in rows:
                    token, exp_str = r["token"], r["expires_at"]
                    exp = parse_iso(exp_str)
                    if exp and exp <= now_utc():
                        conn.execute("DELETE FROM subscriptions WHERE token = ?", (token,))
                conn.commit()
        except Exception as e:
            # не критично — логируем в консоль
            print("periodic_cleanup error:", e)
        await asyncio.sleep(CLEANUP_INTERVAL)

@app.on_event("startup")
async def startup_event():
    ensure_tables()
    asyncio.create_task(periodic_cleanup())

# ---------------- Helpers ----------------
def generate_token(n: int = 22) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))

def build_vless_link(uuid: str, server: str, port: int,
                     pbk: str, sid: str, sni: str, name: str = "Pro100VPN") -> str:
    """
    Собирает vless:// строку с параметрами Reality.
    """
    # Используем параметры pbk (public key) и sid (short id)
    # fp=chrome добавлено для совместимости клиентов
    return (
        f"vless://{uuid}@{server}:{port}"
        f"?encryption=none&security=reality&fp=chrome"
        f"&sni={sni}&pbk={pbk}&sid={sid}&type=tcp"
        f"#{name}"
    )

# ---------------- ROUTES ----------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    token = generate_token()
    config_url = f"http://{DOMAIN}/configs/{token}.json"
    deeplink = f"happ://add/{config_url}"

    # ВНИМАНИЕ: в f-string все фигурные скобки в CSS/JS экранируются двойными {{ }}
    html = f"""
    <!doctype html>
    <html lang="ru">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width,initial-scale=1" />
      <title>Pro100VPN — подписка</title>
      <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-900 text-slate-100 min-h-screen flex items-center justify-center">
      <div class="max-w-md w-full p-6 bg-slate-800 rounded-2xl shadow-xl">
        <h1 class="text-2xl font-semibold mb-2">🚀 Pro100VPN</h1>
        <p class="text-sm text-slate-300 mb-4">Генератор подписок VLESS+Reality</p>

        <a href="{deeplink}" class="block w-full text-center bg-emerald-500 hover:bg-emerald-600 text-slate-900 font-semibold py-3 rounded-lg">Открыть в HappVPN</a>

        <div class="mt-4 text-sm text-slate-400">Если кнопка не сработает — используйте эту ссылку вручную:</div>
        <div class="mt-2 break-words text-emerald-300 text-sm">{config_url}</div>

        <div class="mt-6 text-xs text-slate-400">Подписка работает, только если токен существует в БД и не просрочен.</div>
      </div>

      <script>
        // nothing fancy
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token: str):
    sub = is_active_subscription(token)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    user_id, exp = sub
    active = (exp is not None and exp > now_utc())
    exp_text = exp.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC") if exp else "—"
    config_url = f"http://{DOMAIN}/configs/{token}.json"
    deeplink = f"happ://add/{config_url}"

    html = f"""
    <!doctype html>
    <html lang="ru">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width,initial-scale=1" />
      <title>Pro100VPN — подписка</title>
      <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-900 text-slate-100 min-h-screen flex items-center justify-center">
      <div class="max-w-md w-full p-6 bg-slate-800 rounded-2xl shadow-xl">
        <h1 class="text-2xl font-semibold mb-2">🚀 Pro100VPN</h1>
        <div class="text-sm text-slate-300 mb-2">Токен: <span class="font-mono text-emerald-300">{token}</span></div>
        <div class="p-3 rounded-lg bg-slate-700 mb-4">
          <div>Статус: <span class="font-semibold {'text-emerald-400' if active else 'text-rose-400'}">{'Активна' if active else 'Неактивна'}</span></div>
          <div class="text-xs text-slate-400">Окончание: {exp_text}</div>
        </div>

        <a href="{deeplink}" class="block w-full text-center bg-emerald-500 hover:bg-emerald-600 text-slate-900 font-semibold py-3 rounded-lg">Добавить в HappVPN</a>

        <div class="mt-4 text-xs text-slate-400">Если приложение не открывается автоматически — скопируйте ссылку и вставьте в HappVPN вручную.</div>
        <div class="mt-3 break-words text-emerald-300 text-sm">{config_url}</div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/configs/{token}.json", response_class=PlainTextResponse)
async def configs(token: str):
    """
    Возвращает Base64(subscription) — то, что ожидает HappVPN при добавлении.
    Пример содержимого (до base64):
    vless://UUID@server:port?encryption=none&security=reality&fp=chrome&sni=...&pbk=...&sid=...#Pro100VPN
    """
    sub = is_active_subscription(token)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    user_id, exp = sub
    if not exp or exp <= now_utc():
        raise HTTPException(status_code=410, detail="Subscription expired")

    vless_link = build_vless_link(
        uuid=VLESS_UUID,
        server=SERVER_IP,
        port=SERVER_PORT,
        pbk=REALITY_PUBLIC_KEY,
        sid=REALITY_SHORT_ID,
        sni=REALITY_SNI,
        name="Pro100VPN"
    )

    subscription_b64 = base64.b64encode(vless_link.encode()).decode()
    return PlainTextResponse(subscription_b64)

@app.get("/deeplink/{token}", response_class=PlainTextResponse)
async def deeplink(token: str):
    config_url = f"http://{DOMAIN}/configs/{token}.json"
    return PlainTextResponse(f"happ://add/{config_url}")

@app.get("/health", response_class=JSONResponse)
async def health():
    return JSONResponse({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})

# ---------------- Run (for debug) ----------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000)
