# server.py
import os, sqlite3
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

DB_FILE = os.getenv("HAPPVPN_DB", "/opt/happvpn/bot_database.db")

DOMAIN = "64.188.64.214"
UUID = "29e9cdce-dff1-49f4-b94b-b26fa32a9a6b"
PUBKEY = "Gv3gbcD10M8gKdyqIRx8t_AkEh7yAjTjrjG2N62zHu"
SHORTID = "ba4211bb433df45d"
SNI = "www.google.com"
XRAY_PORT = 443

def db_connect(): return sqlite3.connect(DB_FILE)
def now_utc(): return datetime.now(timezone.utc)

def is_active_subscription(token: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id, expires_at FROM subscriptions WHERE token=?", (token,))
    row = cur.fetchone()
    conn.close()
    if not row: return None
    user_id, exp_str = row
    exp = datetime.fromisoformat(exp_str) if exp_str else None
    if not exp or exp < now_utc(): return None
    return user_id, exp

app = FastAPI()

@app.get("/configs/{token}.json", response_class=JSONResponse)
def get_config(token: str):
    sub = is_active_subscription(token)
    if not sub: raise HTTPException(status_code=404, detail="Subscription expired")

    cfg = {
        "version": 1,
        "nodes": [{
            "type": "vless",
            "name": "Pro100VPN",
            "server": DOMAIN,
            "port": XRAY_PORT,
            "uuid": UUID,
            "security": "reality",
            "flow": "xtls-rprx-vision",
            "tlsSettings": {"serverName": SNI},
            "realitySettings": {"publicKey": PUBKEY, "shortId": SHORTID},
            "network": "tcp"
        }]
    }
    return JSONResponse(content=cfg)

@app.get("/subs/{token}", response_class=HTMLResponse)
def subs_page(token: str):
    sub = is_active_subscription(token)
    if not sub: raise HTTPException(status_code=404, detail="Subscription expired")

    _, exp = sub
    exp_text = exp.strftime("%d.%m.%Y %H:%M UTC")
    config_url = f"http://{DOMAIN}/configs/{token}.json"
    deeplink = f"happ://add/{config_url}"

    html = f"""
    <html><body style="font-family:sans-serif;background:#0f172a;color:white;padding:2rem">
    <h1>Pro100VPN</h1>
    <p>Подписка активна до: {exp_text}</p>
    <a href="{deeplink}">📲 Добавить в HappVPN</a><br><br>
    <a href="{config_url}">📄 Скачать конфиг JSON</a>
    </body></html>
    """
    return HTMLResponse(content=html)
