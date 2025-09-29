import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

app = FastAPI()

# ===== настройки путей =====
DB_FILE = "bot_database.db"
XRAY_CONFIG = Path("/usr/local/etc/xray/config.json")

# Если вдруг derivation publicKey не сработает, подставим вручную:
PUBLIC_KEY_OVERRIDE: Optional[str] = None
# Пример (ваш реальный pbk):
# PUBLIC_KEY_OVERRIDE = "m7n-24tMvfTdp2-2sr-vAaM3t9NzGDpTNrva6xM6-ls"

# ===== утилиты =====
def db_has_token(token: str) -> bool:
    con = sqlite3.connect(DB_FILE)
    try:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM subscriptions WHERE token = ?", (token,))
        return cur.fetchone() is not None
    finally:
        con.close()

def read_vless_from_config() -> Tuple[str, int, str, str, str]:
    """
    Возвращает (uuid, port, sni, short_id, private_key) из Xray config.json.
    Поддерживает и множественное/единственное написание полей.
    """
    if not XRAY_CONFIG.exists():
        raise RuntimeError(f"Xray config not found: {XRAY_CONFIG}")

    data = json.loads(XRAY_CONFIG.read_text(encoding="utf-8"))

    # ищем inbound VLESS
    inbounds = data.get("inbounds") or []
    vless_in = None
    for ib in inbounds:
        if ib.get("protocol") == "vless":
            vless_in = ib
            break
    if not vless_in:
        raise RuntimeError("No VLESS inbound found in Xray config")

    settings = vless_in.get("settings") or {}
    clients = settings.get("clients") or []
    if not clients:
        raise RuntimeError("No clients in VLESS inbound")

    uuid = clients[0].get("id")
    if not uuid:
        raise RuntimeError("Client UUID (id) not found in config")

    port = int(vless_in.get("port", 443))

    stream = vless_in.get("streamSettings") or {}
    reality = stream.get("realitySettings") or {}
    # sni (server name) может храниться в serverNames/0 или serverName
    server_names = reality.get("serverNames") or []
    sni = server_names[0] if server_names else reality.get("serverName")

    if not sni:
        raise RuntimeError("serverName/serverNames missing in realitySettings")

    # shortId/shortIds
    short_ids = reality.get("shortIds")
    short_id = None
    if isinstance(short_ids, list) and short_ids:
        short_id = short_ids[0]
    if not short_id:
        short_id = reality.get("shortId")
    if not short_id:
        raise RuntimeError("shortId/shortIds missing in realitySettings")

    private_key = reality.get("privateKey")
    if not private_key:
        raise RuntimeError("privateKey missing in realitySettings")

    return uuid, port, sni, short_id, private_key

def derive_public_key(private_key: str) -> Optional[str]:
    """
    Получаем pbk через Xray: `xray x25519 -i <private_key>`.
    Возвращаем строку publicKey (base64url), либо None.
    """
    if PUBLIC_KEY_OVERRIDE:
        return PUBLIC_KEY_OVERRIDE
    try:
        out = subprocess.check_output(
            ["xray", "x25519", "-i", private_key],
            text=True,
            stderr=subprocess.STDOUT,
        )
        for line in out.splitlines():
            if "PublicKey" in line:
                # формат: PublicKey: <pbk>
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None

def make_vless_link(
    uuid: str,
    host_or_ip: str,
    port: int,
    sni: str,
    pbk: str,
    short_id: str,
    use_flow: bool,
    fp: str = "chrome",
    tag: str = "Pro100VPN",
) -> str:
    base = (
        f"vless://{uuid}@{host_or_ip}:{port}"
        f"?type=tcp&security=reality&fp={fp}"
        f"&sni={sni}&pbk={pbk}&sid={short_id}"
    )
    if use_flow:
        base += "&flow=xtls-rprx-vision"
    return base + f"#{tag}"

# ===== ручки =====
@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token: str):
    """
    HTML-страница с двумя кнопками: с flow и без flow.
    Все параметры читаются из реального /usr/local/etc/xray/config.json.
    """
    if not db_has_token(token):
        raise HTTPException(status_code=404, detail="Подписка не найдена")

    try:
        uuid, port, sni, short_id, private_key = read_vless_from_config()
        pbk = derive_public_key(private_key)
        if not pbk:
            raise RuntimeError("Не удалось получить publicKey (pbk). "
                               "Задайте PUBLIC_KEY_OVERRIDE в server.py")

        # используем тот же адрес, что у клиента: внешний IP/домен
        host_or_ip = sni  # часто используют тот же домен; если нужен IP — поменяйте ниже
        # Если хотите принудительно IP сервера:
        # host_or_ip = "64.188.64.214"

        vless_flow = make_vless_link(uuid, host_or_ip, port, sni, pbk, short_id, use_flow=True)
        vless_noflow = make_vless_link(uuid, host_or_ip, port, sni, pbk, short_id, use_flow=False)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"config read/derive error: {e}")

    html = f"""
    <html>
      <head><title>Подписка Pro100VPN</title></head>
      <body style="font-family:Arial; text-align:center; margin-top:48px;">
        <h2>Подписка Pro100VPN</h2>
        <p>Выберите способ добавления в HappVPN:</p>
        <div style="margin:10px;">
            <a href="happ://add/{vless_flow}">
                <button style="padding:10px 18px;">Добавить (с flow)</button>
            </a>
        </div>
        <div style="margin:10px;">
            <a href="happ://add/{vless_noflow}">
                <button style="padding:10px 18px;">Добавить (без flow)</button>
            </a>
        </div>
        <p style="color:#777;max-width:680px;margin:24px auto 0;">
          Если кнопки не срабатывают — скопируйте ссылку вручную и откройте в HappVPN:
          <br><code>{vless_flow}</code><br>
          <code>{vless_noflow}</code>
        </p>
      </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def subscription_plain(token: str, noflow: int = Query(0, description="1 — вернуть ссылку без flow")):
    """
    Отдаёт САМУ vless:// ссылку (plain text).
    ?noflow=1 — без flow; по умолчанию — с flow.
    """
    if not db_has_token(token):
        raise HTTPException(status_code=404, detail="Подписка не найдена")
    try:
        uuid, port, sni, short_id, private_key = read_vless_from_config()
        pbk = derive_public_key(private_key)
        if not pbk:
            raise RuntimeError("Не удалось получить publicKey (pbk). "
                               "Задайте PUBLIC_KEY_OVERRIDE в server.py")
        host_or_ip = sni  # или "64.188.64.214"
        link = make_vless_link(uuid, host_or_ip, port, sni, pbk, short_id, use_flow=(noflow != 1))
        return PlainTextResponse(link + "\n")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"config read/derive error: {e}")

@app.get("/", response_class=PlainTextResponse)
async def root():
    return PlainTextResponse("OK")
