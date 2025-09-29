import json
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

app = FastAPI()

DB_FILE = "bot_database.db"
XRAY_CONFIG = Path("/usr/local/etc/xray/config.json")

# ХОСТ в vless:// — адрес твоего сервера (а не SNI)
DOMAIN_OR_IP = "64.188.64.214"

# Публичный ключ от твоего privateKey (override, т.к. derive не работал)
PUBLIC_KEY_OVERRIDE: Optional[str] = "m7n-24tMvfTdp2-2sr-vAaM3t9NzGDpTNrva6xM6-ls"

def db_has_token(token: str) -> bool:
    con = sqlite3.connect(DB_FILE)
    try:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM subscriptions WHERE token=?", (token,))
        return cur.fetchone() is not None
    finally:
        con.close()

def read_vless_from_config() -> Tuple[str, int, str, str]:
    if not XRAY_CONFIG.exists():
        raise RuntimeError(f"Xray config not found: {XRAY_CONFIG}")
    data = json.loads(XRAY_CONFIG.read_text(encoding="utf-8"))
    vless_in = next((ib for ib in data.get("inbounds", []) if ib.get("protocol") == "vless"), None)
    if not vless_in:
        raise RuntimeError("No VLESS inbound in config")

    clients = (vless_in.get("settings") or {}).get("clients") or []
    if not clients or not clients[0].get("id"):
        raise RuntimeError("No client id in config")
    uuid = clients[0]["id"]

    port = int(vless_in.get("port", 443))

    reality = (vless_in.get("streamSettings") or {}).get("realitySettings") or {}
    sni = (reality.get("serverNames") or [reality.get("serverName")])[0]
    if not sni:
        raise RuntimeError("serverName/serverNames missing")
    short_id = (reality.get("shortIds") or [reality.get("shortId")])[0]
    if not short_id:
        raise RuntimeError("shortId/shortIds missing")

    return uuid, port, sni, short_id

def make_vless(uuid: str, host: str, port: int, sni: str, pbk: str, short_id: str, use_flow: bool) -> str:
    base = (
        f"vless://{uuid}@{host}:{port}"
        f"?type=tcp&security=reality&fp=random"
        f"&sni={sni}&pbk={pbk}&sid={short_id}"
    )
    if use_flow:
        base += "&flow=xtls-rprx-vision"
    return base + "#Pro100VPN"

@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token: str):
    if not db_has_token(token):
        raise HTTPException(status_code=404, detail="Подписка не найдена")

    uuid, port, sni, short_id = read_vless_from_config()
    pbk = PUBLIC_KEY_OVERRIDE
    if not pbk:
        raise HTTPException(status_code=500, detail="PUBLIC_KEY_OVERRIDE пуст")

    # deeplink на подпись: HappVPN сходит на /sub/{token} и заберёт plain-text ссылку
    url_flow   = f"http://{DOMAIN_OR_IP}/sub/{token}?noflow=0"
    url_noflow = f"http://{DOMAIN_OR_IP}/sub/{token}?noflow=1"

    html = f"""
    <html>
      <head><title>Подписка Pro100VPN</title></head>
      <body style="font-family:Arial; text-align:center; margin-top:48px;">
        <h2>Подписка Pro100VPN</h2>
        <p>Выберите способ добавления в HappVPN:</p>
        <div style="margin:10px;">
            <a href="happ://add/{url_flow}">
                <button style="padding:10px 18px;">Добавить (с flow)</button>
            </a>
        </div>
        <div style="margin:10px;">
            <a href="happ://add/{url_noflow}">
                <button style="padding:10px 18px;">Добавить (без flow)</button>
            </a>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def sub_plain(token: str, noflow: int = Query(0, description="1 — без flow")):
    if not db_has_token(token):
        raise HTTPException(status_code=404, detail="Подписка не найдена")

    uuid, port, sni, short_id = read_vless_from_config()
    pbk = PUBLIC_KEY_OVERRIDE
    if not pbk:
        raise HTTPException(status_code=500, detail="PUBLIC_KEY_OVERRIDE пуст")

    host = DOMAIN_OR_IP                    # хост = IP сервера
    link = make_vless(uuid, host, port, sni, pbk, short_id, use_flow=(noflow != 1))
    return PlainTextResponse(link + "\n")

@app.get("/", response_class=PlainTextResponse)
async def root():
    return PlainTextResponse("OK")
