#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI-сервис, выдающий подписку для v2RayTun.
Сохраняет совместимость: обычная /sub остается текстом VLESS, а /sub_v2raytun дублирует,
плюс HTML-страница с deep-link "v2raytun://import-sub?url=...".
"""
import os, base64, json
from typing import Optional, Tuple
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, HTMLResponse, RedirectResponse
import aiosqlite
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

# === Конфиг окружения (переопредели через env при деплое) ===
DB_PATH     = os.getenv("DB_PATH", "/root/rel/bot_database.db")
XRAY_CONFIG = os.getenv("XRAY_CONFIG", "/usr/local/etc/xray/config.json")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "64.188.64.214")   # куда будет указывать vless (твой IP/домен)
PUBLIC_BASE = os.getenv("PUBLIC_BASE", f"https://{PUBLIC_HOST}")  # базовый URL для страницы/подписки

app = FastAPI(title="rel-v2raytun-sub")

# === Утилиты Reality ===
def _b64u_nopad(b: bytes) -> str:
    s = base64.urlsafe_b64encode(b).decode().rstrip("=")
    return s

def pbk_from_private_key(pk_str: str) -> str:
    """
    Reality privateKey обычно хранится base64 (raw 32 bytes).
    Вернём pbk (base64url без паддинга).
    """
    # пробуем base64
    try:
        raw = base64.b64decode(pk_str + "==")
    except Exception:
        # если вдруг пришёл hex — мало ли
        raw = bytes.fromhex(pk_str)
    priv = x25519.X25519PrivateKey.from_private_bytes(raw)
    pub = priv.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                         format=serialization.PublicFormat.Raw)
    return _b64u_nopad(pub)

def read_xray_reality() -> Tuple[int, str, str, str, str]:
    """
    Возвращает (port, network, sni, sid, pbk) из XRAY_CONFIG.
    Берём первый inbound со security=reality.
    """
    with open(XRAY_CONFIG, "r", encoding="utf-8") as f:
        data = json.load(f)
    inbound = None
    for ib in data.get("inbounds", []):
        ss = ib.get("streamSettings", {}) or {}
        if ss.get("security") == "reality" or ss.get("realitySettings"):
            inbound = ib; break
    if not inbound:
        raise RuntimeError("Reality inbound not found in config.json")

    port = int(inbound.get("port"))
    network = (inbound.get("streamSettings", {}) or {}).get("network", "tcp")
    rs = (inbound.get("streamSettings", {}) or {}).get("realitySettings", {}) or {}
    sni = (rs.get("serverNames") or [""])[0]
    sid = (rs.get("shortIds") or [""])[0]
    pk  = rs.get("privateKey") or ""
    pbk = pbk_from_private_key(pk) if pk else ""
    return port, network, sni, sid, pbk

async def token_valid(token: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Проверка токена подписки в БД. Возвращает (user_id, expires_at) или (None, None).
    Мы НЕ ломаем твою схему — ищем в subscriptions (и, на всякий случай, в vpn_links).
    """
    if not os.path.exists(DB_PATH):
        return None, None
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # subscriptions: token, user_id, expires_at
            async with db.execute("SELECT user_id, expires_at FROM subscriptions WHERE token = ?", (token,)) as cur:
                row = await cur.fetchone()
                if row: return row[0], row[1]
            # fallback: vpn_links: token, user_id, expires_at
            async with db.execute("SELECT user_id, expires_at FROM vpn_links WHERE token = ?", (token,)) as cur:
                row = await cur.fetchone()
                if row: return row[0], row[1]
    except Exception:
        pass
    return None, None

def build_vless(host: str, port: int, uuid: str, network: str, sni: str, sid: str, pbk: str,
                flow: bool, name: str) -> str:
    """
    Генерирует VLESS Reality ссылку (Vision flow = xtls-rprx-vision).
    Важно для v2RayTun: добавить понятный #name.
    """
    base = f"vless://{uuid}@{host}:{port}?type={network}&security=reality&fp=chrome&alpn=h2,http/1.1"
    if pbk: base += f"&pbk={pbk}"
    if sni: base += f"&sni={sni}"
    if sid: base += f"&sid={sid}"
    if flow:
        base += "&flow=xtls-rprx-vision"
        name = name or "Reality Vision"
    else:
        name = name or "Reality NoFlow"
    return f"{base}#{name}"

# ====== ENDPOINTS ======

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def classic_sub(token: str, uuid: Optional[str] = None):
    """
    Классический текст подписки: 2 строки (NoFlow и Vision).
    Подходит для v2RayTun и любых клиентов.
    """
    user_id, _ = await token_valid(token)
    if not user_id:
        raise HTTPException(404, "Token not found")
    port, network, sni, sid, pbk = read_xray_reality()

    # UUID берём из таблицы vpn_links, если есть; иначе принимаем из query ?uuid=
    real_uuid = uuid
    if not real_uuid and os.path.exists(DB_PATH):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT uuid FROM vpn_links WHERE token = ?", (token,)) as cur:
                    row = await cur.fetchone()
                    if row and row[0]:
                        real_uuid = row[0]
        except Exception:
            pass
    if not real_uuid:
        # в крайнем случае — первый клиент из конфига (не лучший вариант, но работает)
        with open(XRAY_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
        inb = [ib for ib in data.get("inbounds", []) if ib.get("protocol") == "vless"]
        if inb and inb[0].get("settings", {}).get("clients"):
            real_uuid = inb[0]["settings"]["clients"][0]["id"]

    if not real_uuid:
        raise HTTPException(400, "UUID is required, but not found. Pass ?uuid=... or store in vpn_links.")

    v_no   = build_vless(PUBLIC_HOST, port, real_uuid, network, sni, sid, pbk, False, f"user{user_id}-NoFlow")
    v_flow = build_vless(PUBLIC_HOST, port, real_uuid, network, sni, sid, pbk, True,  f"user{user_id}-Vision")
    return PlainTextResponse(v_no + "\n" + v_flow, media_type="text/plain; charset=utf-8")

@app.get("/sub_v2raytun/{token}", response_class=PlainTextResponse)
async def sub_v2raytun(token: str, uuid: Optional[str] = None):
    """
    То же самое, просто отдельный путь (удобно для ссылок/маркетинга).
    """
    return await classic_sub(token, uuid)

@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token: str, request: Request, uuid: Optional[str] = None):
    """
    Проста страница с кнопками: "Добавить в v2RayTun", "Скопировать подписку".
    """
    # проверим токен, дадим короткий фидбэк на странице, даже если нет БД
    uid, expire = await token_valid(token)
    status_badge = f"<span style='color:#2ecc71'>Активна</span>" if uid else "<span style='color:#e67e22'>Проверка токена пропущена</span>"
    sub_url  = f"{PUBLIC_BASE}/sub_v2raytun/{token}" + (f"?uuid={uuid}" if uuid else "")
    deep     = f"v2raytun://import-sub?url={sub_url}"

    html = f"""
<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Информация о подписке</title>
<style>
 body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,sans-serif;background:#0b0f14;color:#fff;margin:0}}
 .wrap{{max-width:640px;margin:24px auto;padding:16px}}
 .card{{background:#0f151d;border-radius:14px;padding:16px;margin-bottom:16px;border:1px solid #1f2a38}}
 .btn{{display:inline-block;background:#1e90ff;color:#fff;padding:12px 16px;border-radius:12px;text-decoration:none;margin-right:8px}}
 .muted{{color:#a9b2be}}
 code{{background:#0b0f14;border:1px solid #1f2a38;border-radius:8px;padding:4px 6px}}
</style>
</head><body><div class="wrap">
  <h2>Подписка</h2>
  <div class="card">
    <div>Статус: {status_badge}</div>
    <div class="muted">Ссылка на подписку для клиентов: <code>/sub_v2raytun/{token}</code></div>
  </div>

  <div class="card">
    <h3>Приложение v2RayTun</h3>
    <p><a class="btn" href="{deep}">Добавить подписку в v2RayTun</a>
       <a class="btn" href="https://play.google.com/store/apps/details?id=com.v2raytun">Скачать в Google Play</a></p>
    <p class="muted">Если не открывается deep-link — скопируйте URL подписки и импортируйте вручную:<br/>
      <code>{sub_url}</code></p>
  </div>
</div></body></html>
"""
    return HTMLResponse(html)

# Удобный редирект: импорт ОДНОГО узла в v2RayTun
@app.get("/v2raytun_import_one/{token}")
async def v2raytun_import_one(token: str, vision: int = 0, uuid: Optional[str] = None):
    """
    Генерит один vless и редиректит на v2raytun://import/{URL}
    """
    text = await classic_sub(token, uuid)
    links = text.body.decode().splitlines()
    url = links[1] if vision else links[0]
    # для import/{URL} URL должен быть URL-encoded
    from urllib.parse import quote
    return RedirectResponse(f"v2raytun://import/{quote(url, safe='')}")
