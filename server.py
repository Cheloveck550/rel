import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

app = FastAPI()

# ===== пути/файлы =====
DB_FILE = "bot_database.db"
XRAY_CONFIG = Path("/usr/local/etc/xray/config.json")

# ===== сетевые параметры =====
DOMAIN_OR_IP = "64.188.64.214"   # ХОСТ в vless:// — твой сервер! (не sni)
# если позже перейдёшь на домен — подставь его сюда

# ===== override public key (pbk) =====
# У тебя derive не сработал — включаем ручной pbk:
PUBLIC_KEY_OVERRIDE: Optional[str] = "m7n-24tMvfTdp2-2sr-vAaM3t9NzGDpTNrva6xM6-ls"

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
    """
    if not XRAY_CONFIG.exists():
        raise RuntimeError(f"Xray config not found: {XRAY_CONFIG}")

    data = json.loads(XRAY_CONFIG.read_text(encoding="utf-8"))

    # ищем inbound VLESS
    inbounds = data.get("inbounds") or []
    vless_in = next((ib for ib in inbounds if ib.get("protocol") == "vless"), None)
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

    # SNI
    server_names = reality.get("serverNames") or []
    sni = server_names[0] if server_names else reality.get("serverName")
    if not sni:
        raise RuntimeError("serverName/serverNames missing in realitySettings")

    # shortId
    short_ids = reality.get("shortIds")
    short_id = (short_ids[0] if isinstance(short_ids, list) and short_ids else reality.get("shortId"))
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
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None

def make_vless_link(
    uuid: str,
    host: str,
    port: int,
    sni: str,
    pbk: str,
    short_id: str,
    use_flow: bool,
    fp: str = "chrome",
    tag: str = "Pro100VPN",
) -> str:
    """
    Формирует vless:// ссылку. Хост = твой сервер; SNI = реальный домен назначения.
    """
    base = (
        f"vless://{uuid}@{host}:{port}"
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
    HTML с двумя кнопками: с flow и без flow. HappVPN открывает deeplink.
    """
    if not db_has_token(token):
        raise HTTPException(status_code=404, detail="Подписка не найдена")

    try:
        uuid, port, sni, short_id, private_key = read_vless_from_config()
        pbk = derive_public_key(private_key)
        if not pbk:
            raise RuntimeError("Не удалось получить publicKey (pbk). "
                               "Проверь PUBLIC_KEY_OVERRIDE в server.py")

        # Хост ДОЛЖЕН быть адресом твоего сервера:
        host = DOMAIN_OR_IP

        # deeplink открывает URL, а URL отдаёт plain-text vless://
        sub_url_flow   = f"http://{DOMAIN_OR_IP}/sub/{token}?noflow=0"
        sub_url_noflow = f"http://{DOMAIN_OR_IP}/sub/{token}?noflow=1"

        html = f"""
        <html>
          <head><title>Подписка Pro100VPN</title></head>
          <body style="font-family:Arial; text-align:center; margin-top:48px;">
            <h2>Подписка Pro100VPN</h2>
            <p>Выберите способ добавления в HappVPN:</p>
            <div style="margin:10px;">
                <a href="happ://add/{sub_url_flow}">
                    <button style="padding:10px 18px;">Добавить (с flow)</button>
                </a>
            </div>
            <div style="margin:10px;">
                <a href="happ://add/{sub_url_noflow}">
                    <button style="padding:10px 18px;">Добавить (без flow)</button>
                </a>
            </div>
            <p style="color:#777;max-width:680px;margin:24px auto 0;">
              Если кнопки не срабатывают — скопируйте ссылку вручную и откройте в HappVPN:
              <br><code>happ://add/{sub_url_flow}</code><br>
              <code>happ://add/{sub_url_noflow}</code>
            </p>
          </body>
        </html>
        """
        return HTMLResponse(html)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"config read/derive error: {e}")

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def subscription_plain(token: str, noflow: int = Query(0, description="1 — вернуть ссылку без flow")):
    """
    Возвращает САМУ vless:// ссылку (plain text), чтобы HappVPN импортировал как подписку.
    ?noflow=1 — без flow; ?noflow=0 — с flow.
    """
    if not db_has_token(token):
        raise HTTPException(status_code=404, detail="Подписка не найдена")

    try:
        uuid, port, sni, short_id, private_key = read_vless_from_config()
        pbk = derive_public_key(private_key)
        if not pbk:
            raise RuntimeError("Не удалось получить publicKey (pbk). "
                               "Проверь PUBLIC_KEY_OVERRIDE в server.py")

        host = DOMAIN_OR_IP
        link = make_vless_link(uuid, host, port, sni, pbk, short_id, use_flow=(noflow != 1))
        return PlainTextResponse(link + "\n")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"config read/derive error: {e}")

@app.get("/", response_class=PlainTextResponse)
async def root():
    return PlainTextResponse("OK")
