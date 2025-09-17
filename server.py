import sqlite3
import secrets
import json
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

# ===================== ПАРАМЕТРЫ =====================
DOMAIN = "193.58.122.47"   # IP или домен
PORT = 443                 # порт VLESS+Reality
UUID = "4f09a57e-76c7-497c-a878-db737cd6a5b5"
REALITY_PUBLIC_KEY = "bb45e9b132a66a07"
REALITY_SHORT_ID = "bb45e9b132a66a07"
SNI = "www.cloudflare.com"

DB_FILE = "bot_database.db"

# ===================== ВСПОМОГАТЕЛЬНОЕ =====================
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
    if exp and exp < now_utc():
        return None
    return user_id, exp

# ===================== FASTAPI =====================
app = FastAPI()

@app.get("/configs/{token}.json", response_class=JSONResponse)
def get_config(token: str):
    sub = is_active_subscription(token)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found or expired")
    config = {
        "version": 1,
        "nodes": [
            {
                "type": "vless",
                "name": "Pro100VPN",
                "server": DOMAIN,
                "port": PORT,
                "uuid": UUID,
                "security": "reality",
                "flow": "",
                "tlsSettings": {
                    "serverName": SNI
                },
                "realitySettings": {
                    "publicKey": REALITY_PUBLIC_KEY,
                    "shortId": REALITY_SHORT_ID
                }
            }
        ]
    }
    return JSONResponse(content=config)

@app.get("/subs/{token}", response_class=HTMLResponse)
def subs_page(token: str):
    sub = is_active_subscription(token)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    user_id, exp = sub
    active = exp is not None and exp > now_utc()
    exp_text = exp.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC") if exp else "—"

    config_url = f"http://{DOMAIN}/configs/{token}.json"
    deeplink = f"happ://add/{config_url}"

    html = f"""
    <!doctype html>
    <html lang="ru">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width,initial-scale=1" />
      <title>Pro100VPN — Подписка</title>
      <style>
        :root{{ --bg:linear-gradient(135deg,#0f172a,#0b1220); --card:#0b1220; --accent:#06b6d4; --muted:#94a3b8; }}
        html,body{{ height:100%; margin:0; font-family:Inter,system-ui,Arial,sans-serif; background:var(--bg); color:#e6eef6; }}
        body{{ display:flex; justify-content:center; align-items:center; padding:2rem; }}
        .card{{ background:var(--card); padding:2rem; border-radius:1.5rem; box-shadow:0 8px 24px rgba(0,0,0,.5); max-width:480px; width:100%; }}
        h1{{ font-size:1.5rem; margin-top:0; color:#fff; }}
        .status{{ margin:1rem 0; padding:1rem; border-radius:.75rem; background:#1e293b; }}
        .ok{{ color:#22c55e; }}
        .bad{{ color:#ef4444; }}
        .btn{{ display:block; text-align:center; margin:.75rem 0; padding:.75rem 1.25rem; background:var(--accent); color:#fff; border-radius:.75rem; text-decoration:none; font-weight:500; transition:.2s; }}
        .btn:hover{{ opacity:.85; }}
        .muted{{ font-size:.9rem; color:var(--muted); margin-top:.5rem; }}
        pre{{ background:#0f172a; padding:.75rem; border-radius:.5rem; overflow-x:auto; }}
      </style>
    </head>
    <body>
      <div class="card">
        <h1>Pro100VPN</h1>
        <div class="status">
          <p>Статус: {"<span class='ok'>Активна</span>" if active else "<span class='bad'>Неактивна</span>"}</p>
          <p>Окончание: {exp_text}</p>
        </div>
        <a class="btn" href="{deeplink}">Открыть в HappVPN</a>
        <button id="copyConfig" class="btn" style="background:#3b82f6;border:none;cursor:pointer;width:100%;">Копировать ссылку конфигурации</button>
        <p class="muted">Если HappVPN не открывается, добавьте конфигурацию вручную:</p>
        <pre id="cfg">{config_url}</pre>
      </div>
      <script>
        document.getElementById("copyConfig").addEventListener("click", async () => {{
          const text = document.getElementById("cfg").innerText;
          try {{
            await navigator.clipboard.writeText(text);
            document.getElementById("copyConfig").innerText = "Скопировано!";
            setTimeout(()=>document.getElementById("copyConfig").innerText = "Копировать ссылку конфигурации",1500);
          }} catch (e) {{
            alert("Не удалось скопировать. Скопируйте вручную:\\n" + text);
          }}
        }});
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# ===================== ТЕСТ =====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
