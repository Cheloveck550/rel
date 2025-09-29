import json, sqlite3, subprocess, shlex
from pathlib import Path
from typing import Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

app = FastAPI()

DB_FILE     = "/root/rel/bot_database.db"              # твой абсолютный путь
XRAY_CONFIG = Path("/usr/local/etc/xray/config.json")
XRAY_BIN    = "/usr/local/bin/xray"
DOMAIN_OR_IP = "64.188.64.214"                          # хост для vless://

def db_has_token(token: str) -> bool:
    con = sqlite3.connect(DB_FILE)
    try:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM subscriptions WHERE token=?", (token,))
        return cur.fetchone() is not None
    finally:
        con.close()

def read_vless() -> Tuple[str,int,str,str,str]:
    if not XRAY_CONFIG.exists():
        raise RuntimeError("config.json not found")
    data = json.loads(XRAY_CONFIG.read_text(encoding="utf-8"))
    vless = next((i for i in data.get("inbounds",[]) if i.get("protocol")=="vless"), None)
    if not vless: raise RuntimeError("No VLESS inbound")

    uuid = (vless.get("settings") or {}).get("clients",[{}])[0].get("id")
    port = int(vless.get("port",443))
    r = (vless.get("streamSettings") or {}).get("realitySettings") or {}
    sni = (r.get("serverNames") or [r.get("serverName")])[0]
    sid = (r.get("shortIds") or [r.get("shortId")])[0]
    prv = r.get("privateKey")
    if not all([uuid, sni, sid, prv]): raise RuntimeError("incomplete realitySettings")
    return uuid, port, sni, sid, prv

def derive_public_key(private_key: str) -> str:
    # xray x25519 -i <private>
    cmd = f"{shlex.quote(XRAY_BIN)} x25519 -i {shlex.quote(private_key)}"
    out = subprocess.check_output(cmd, shell=True, text=True)
    for line in out.splitlines():
        if line.startswith("PublicKey:"):
            return line.split(":",1)[1].strip()
    raise RuntimeError("PublicKey not derived")

def make_vless(uuid: str, host: str, port: int, sni: str, pbk: str, sid: str, use_flow: bool) -> str:
    base = (
        f"vless://{uuid}@{host}:{port}"
        f"?type=tcp&security=reality&encryption=none&fp=chrome"
        f"&sni={sni}&pbk={pbk}&sid={sid}"
    )
    if use_flow:
        base += "&flow=xtls-rprx-vision"
    return base + "#Pro100VPN"

@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token: str):
    if not db_has_token(token):
        raise HTTPException(status_code=404, detail="Подписка не найдена")
    url_flow   = f"http://{DOMAIN_OR_IP}/sub/{token}?noflow=0"
    url_noflow = f"http://{DOMAIN_OR_IP}/sub/{token}?noflow=1"
    html = f"""
    <html><head><title>Подписка Pro100VPN</title></head>
    <body style="font-family:Arial; text-align:center; margin-top:48px;">
      <h2>Подписка Pro100VPN</h2>
      <p>Выберите способ добавления в HappVPN:</p>
      <div style="margin:10px;">
        <a href="happ://add/{url_flow}"><button style="padding:10px 18px;">Добавить (с flow)</button></a>
      </div>
      <div style="margin:10px;">
        <a href="happ://add/{url_noflow}"><button style="padding:10px 18px;">Добавить (без flow)</button></a>
      </div>
    </body></html>
    """
    return HTMLResponse(html)

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def sub_plain(token: str, noflow: int = Query(0)):
    if not db_has_token(token):
        raise HTTPException(status_code=404, detail="Подписка не найдена")
    uuid, port, sni, sid, prv = read_vless()
    pbk = derive_public_key(prv)
    link = make_vless(uuid, DOMAIN_OR_IP, port, sni, pbk, sid, use_flow=(noflow!=1))
    return PlainTextResponse(link + "\n")

@app.get("/", response_class=PlainTextResponse)
async def root():
    return PlainTextResponse("OK\n")
