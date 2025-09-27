# server.py
import os
import sqlite3
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

DB_FILE = os.getenv("HAPPVPN_DB", "/opt/happvpn/bot_database.db")

def read_env(path="/etc/xray/reality.env"):
    m = {}
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): 
                    continue
                k, v = line.split("=", 1)
                m[k] = v
    except FileNotFoundError:
        pass
    return m

ENV = read_env()
DOMAIN   = ENV.get("DOMAIN", "127.0.0.1")
UUID     = ENV.get("UUID", "")
PUBKEY   = ENV.get("PUBKEY", "")
SHORTID  = ENV.get("SHORTID", "")
SNI      = ENV.get("SNI", "www.google.com")
XRAY_PORT= int(ENV.get("XRAY_PORT", "443"))

def now_utc(): 
    return datetime.now(timezone.utc)

def db_connect(): 
    return sqlite3.connect(DB_FILE)

def is_active_subscription(token: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id, expires_at FROM subscriptions WHERE token=?", (token,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    user_id, exp_str = row
    exp = datetime.fromisoformat(exp_str) if exp_str else None
    if not exp or exp < now_utc():
        return None
    return user_id, exp

app = FastAPI(title="HappVPN API")

@app.get("/configs/{token}.json", response_class=JSONResponse)
def get_config(token: str):
    sub = is_active_subscription(token)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found or expired")

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
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found or expired")

    _, exp = sub
    exp_text = exp.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    config_url = f"http://{DOMAIN}/configs/{token}.json"
    deeplink = f"happ://add/{config_url}"

    html = f"""<!doctype html><html lang="ru"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Pro100VPN — Подписка</title>
<style>
:root{{--card:#0b1220;--accent:#06b6d4;--muted:#94a3b8}}
html,body{{height:100%;margin:0;background:linear-gradient(135deg,#0f172a,#0b1220);color:#e6eef6;font-family:system-ui,Arial}}
body{{display:flex;align-items:center;justify-content:center}}
.card{{background:var(--card);padding:2rem;border-radius:1rem;max-width:560px;box-shadow:0 12px 30px rgba(0,0,0,.5)}}
.btn{{display:block;margin:.5rem 0;padding:.8rem 1rem;background:var(--accent);border-radius:.6rem;color:#fff;text-decoration:none;text-align:center;font-weight:700}}
.muted{{color:var(--muted);font-size:.9rem}}
pre{{background:#0f172a;padding:.75rem;border-radius:.5rem;overflow:auto}}
</style></head><body>
<div class="card">
  <h1>Pro100VPN</h1>
  <p>Статус: <b style="color:#22c55e">Активна</b></p>
  <p>Окончание: {exp_text}</p>
  <a class="btn" href="{deeplink}">Открыть в HappVPN</a>
  <a class="btn" style="background:#3b82f6" href="{config_url}">Открыть конфиг JSON</a>
  <p class="muted">Если deeplink не срабатывает, добавьте конфиг вручную по ссылке ниже:</p>
  <pre>{config_url}</pre>
</div>
</body></html>"""
    return HTMLResponse(content=html)
