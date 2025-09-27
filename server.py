# server.py
import os
import sqlite3
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

DB_FILE = os.getenv("HAPPVPN_DB", "/opt/happvpn/bot_database.db")

def read_env(path="/etc/xray/reality.env"):
    env = {}
    try:
        with open(path, "r") as f:
            for line in f:
                line=line.strip()
                if not line or line.startswith("#"): continue
                k,v = line.split("=",1)
                env[k]=v
    except FileNotFoundError:
        pass
    return env

ENV = read_env()
DOMAIN  = ENV.get("DOMAIN","127.0.0.1")
UUID    = ENV.get("UUID","")
PUBKEY  = ENV.get("PUBKEY","")
SHORTID = ENV.get("SHORTID","")
SNI     = ENV.get("SNI","www.google.com")
XRAY_PORT = int(ENV.get("XRAY_PORT","443"))

def now_utc(): return datetime.now(timezone.utc)
def db(): return sqlite3.connect(DB_FILE)

def is_active(token: str):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, expires_at FROM subscriptions WHERE token=?", (token,))
        row = cur.fetchone()
    if not row: return None
    uid, exp = row
    try:
        dt = datetime.fromisoformat(exp)
    except:
        return None
    return (uid, dt) if dt > now_utc() else None

app = FastAPI()

@app.get("/configs/{token}.json", response_class=JSONResponse)
def get_cfg(token: str):
    sub = is_active(token)
    if not sub: raise HTTPException(404, "Subscription not found or expired")
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
def subs(token: str):
    sub = is_active(token)
    if not sub: raise HTTPException(404, "Subscription not found or expired")
    _, exp = sub
    exp_s = exp.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    cfg_url = f"http://{DOMAIN}/configs/{token}.json"
    deeplink = f"happ://add/{cfg_url}"
    html = f"""<!doctype html><html><head><meta charset="utf-8"/>
<style>
body{{margin:0;background:#0f172a;color:#e6eef6;font-family:Inter,system-ui,Arial,sans-serif}}
.wrap{{max-width:560px;margin:5vh auto;background:#0b1220;padding:24px;border-radius:16px}}
.btn{{display:block;background:#06b6d4;color:#fff;text-decoration:none;padding:12px 16px;border-radius:12px;text-align:center;font-weight:600;margin:.5rem 0}}
.small{{color:#94a3b8}}
pre{{background:#0f172a;padding:10px;border-radius:8px;overflow:auto}}
</style></head><body><div class="wrap">
  <h1>Pro100VPN</h1>
  <p>Статус: активна до <b>{exp_s}</b></p>
  <a class="btn" href="{deeplink}">📲 Добавить в HappVPN</a>
  <a class="btn" style="background:#3b82f6" href="{cfg_url}">📄 Открыть конфиг JSON</a>
  <p class="small">Если deeplink не срабатывает — добавьте конфиг вручную по ссылке ниже:</p>
  <pre>{cfg_url}</pre>
</div></body></html>"""
    return HTMLResponse(content=html)
