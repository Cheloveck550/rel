#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, asyncio, time, json, base64
from typing import Optional, Tuple

import aiosqlite
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse, RedirectResponse
import uvicorn

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

# ====== ENV ======
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
DB_PATH     = os.getenv("DB_PATH", "/root/rel/bot_database.db")
XRAY_CONFIG = os.getenv("XRAY_CONFIG", "/usr/local/etc/xray/config.json")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "64.188.64.214")
PUBLIC_BASE = os.getenv("PUBLIC_BASE", f"http://{PUBLIC_HOST}")
PRICE_VPN   = float(os.getenv("PRICE_VPN", "150"))
DAYS_VPN    = int(os.getenv("DAYS_VPN", "30"))

# ====== DB ======
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,
  balance REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subscriptions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS vpn_links (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  uuid  TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
"""

async def db_init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL); await db.commit()

async def ensure_user(uid:int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
        if not await cur.fetchone():
            await db.execute("INSERT INTO users(user_id,balance) VALUES(?,0)", (uid,))
            await db.commit()

async def get_balance(uid:int)->float:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        return float(row[0]) if row else 0.0

async def add_balance(uid:int, delta:float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (delta, uid))
        await db.commit()

# ====== Reality utils ======
def _b64u(b:bytes)->str: return base64.urlsafe_b64encode(b).decode().rstrip("=")

def pbk_from_private_key(pk_str:str)->str:
    try: raw = base64.b64decode(pk_str + "==")
    except Exception: raw = bytes.fromhex(pk_str)
    priv = x25519.X25519PrivateKey.from_private_bytes(raw)
    pub  = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    return _b64u(pub)

def read_xray_reality()->Tuple[int,str,str,str,str,str]:
    with open(XRAY_CONFIG, "r", encoding="utf-8") as f: data=json.load(f)
    inbound=None
    for ib in data.get("inbounds",[]):
        ss=ib.get("streamSettings",{}) or {}
        if ss.get("security")=="reality" or ss.get("realitySettings"): inbound=ib; break
    if not inbound: raise RuntimeError("Reality inbound not found in XRAY_CONFIG")

    port=int(inbound.get("port"))
    network=(inbound.get("streamSettings",{}) or {}).get("network","tcp")
    rs=(inbound.get("streamSettings",{}) or {}).get("realitySettings",{}) or {}
    sni=(rs.get("serverNames") or [""])[0]
    sid=(rs.get("shortIds") or [""])[0]
    pk=rs.get("privateKey") or ""
    pbk=pbk_from_private_key(pk) if pk else ""
    first_uuid=""
    try:
        clients=(inbound.get("settings",{}) or {}).get("clients") or []
        if clients: first_uuid=clients[0]["id"]
    except Exception: pass
    return port, network, sni, sid, pbk, first_uuid

def build_vless(host,port,uuid,network,sni,sid,pbk,flow,name):
    base=f"vless://{uuid}@{host}:{port}?type={network}&security=reality&fp=chrome&alpn=h2,http/1.1"
    if pbk: base+=f"&pbk={pbk}"
    if sni: base+=f"&sni={sni}"
    if sid: base+=f"&sid={sid}"
    if flow: base+="&flow=xtls-rprx-vision"; name=name or "Reality Vision"
    else:   name=name or "Reality NoFlow"
    return f"{base}#{name}"

# ====== v2RayTun helpers ======
def _urls(token:str, uuid:Optional[str]=None)->dict:
    sub_txt=f"{PUBLIC_BASE}/sub_v2raytun/{token}"
    if uuid: sub_txt+=f"?uuid={uuid}"
    subs_page=f"{PUBLIC_BASE}/subs/{token}" + (f"?uuid={uuid}" if uuid else "")
    deeplink=f"v2raytun://import-sub?url={sub_txt}"
    return {"sub_txt":sub_txt,"subs_page":subs_page,"deeplink":deeplink}

def kb_v2raytun(token, uuid=None)->InlineKeyboardMarkup:
    u=_urls(token,uuid)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в v2RayTun", url=u["deeplink"])],
        [InlineKeyboardButton(text="ℹ️ Информация о подписке", url=u["subs_page"])]
    ])

def text_v2raytun(token, uuid=None)->str:
    u=_urls(token,uuid)
    return ("Ваш ключ готов! ✨\n\n"
            "Нажмите кнопку ниже, чтобы добавить подписку в v2RayTun.\n"
            "Если deep-link не открывается — импортируйте вручную:\n"
            f"{u['sub_txt']}\n\n"
            "⚙️ Будут импортированы два профиля: NoFlow и Vision.")

async def create_subscription(uid:int, uuid:str)->str:
    import secrets
    token = secrets.token_urlsafe(24)
    now   = int(time.time())
    exp   = now + DAYS_VPN*86400
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO subscriptions(token,user_id,expires_at) VALUES(?,?,?)",
                         (token, uid, exp))
        await db.execute("INSERT OR REPLACE INTO vpn_links(token,user_id,uuid,created_at) VALUES(?,?,?,?)",
                         (token, uid, uuid, now))
        await db.commit()
    return token

# ====== FastAPI ======
app = FastAPI(title="rel v2raytun")

async def token_valid(token:str)->Tuple[Optional[int],Optional[int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT user_id,expires_at FROM subscriptions WHERE token=?", (token,))
        row=await cur.fetchone()
        return (int(row[0]), int(row[1])) if row else (None, None)

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def sub_plain(token:str, uuid:Optional[str]=None):
    uid, _ = await token_valid(token)
    if not uid: raise HTTPException(404, "Token not found")
    port, network, sni, sid, pbk, first_uuid = read_xray_reality()

    real_uuid = uuid
    if not real_uuid:
        async with aiosqlite.connect(DB_PATH) as db:
            cur=await db.execute("SELECT uuid FROM vpn_links WHERE token=?", (token,))
            r=await cur.fetchone()
            if r and r[0]: real_uuid=r[0]
    if not real_uuid: real_uuid=first_uuid
    if not real_uuid: raise HTTPException(400,"UUID not found")

    v_no   = build_vless(PUBLIC_HOST, port, real_uuid, network, sni, sid, pbk, False, f"user{uid}-NoFlow")
    v_flow = build_vless(PUBLIC_HOST, port, real_uuid, network, sni, sid, pbk, True,  f"user{uid}-Vision")
    return PlainTextResponse(v_no+"\n"+v_flow, media_type="text/plain; charset=utf-8")

@app.get("/sub_v2raytun/{token}", response_class=PlainTextResponse)
async def sub_v2(token:str, uuid:Optional[str]=None):
    return await sub_plain(token, uuid)

@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token:str, uuid:Optional[str]=None):
    uid, _ = await token_valid(token)
    badge = "<span style='color:#2ecc71'>Активна</span>" if uid else "<span style='color:#e67e22'>Не найдена</span>"
    sub_url=f"{PUBLIC_BASE}/sub_v2raytun/{token}" + (f"?uuid={uuid}" if uuid else "")
    deep=f"v2raytun://import-sub?url={sub_url}"
    html=f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Информация о подписке</title>
<style>body{{font-family:system-ui,Segoe UI,Roboto,Ubuntu,sans-serif;background:#0b0f14;color:#fff;margin:0}}
.wrap{{max-width:640px;margin:24px auto;padding:16px}}
.card{{background:#0f151d;border-radius:14px;padding:16px;margin-bottom:16px;border:1px solid #1f2a38}}
.btn{{display:inline-block;background:#1e90ff;color:#fff;padding:12px 16px;border-radius:12px;text-decoration:none;margin-right:8px}}
.muted{{color:#a9b2be}} code{{background:#0b0f14;border:1px solid #1f2a38;border-radius:8px;padding:4px 6px}}</style>
</head><body><div class="wrap">
<h2>Подписка</h2><div class="card">Статус: {badge}</div>
<div class="card">
  <h3>v2RayTun</h3>
  <p><a class="btn" href="{deep}">Добавить подписку в v2RayTun</a>
     <a class="btn" href="https://play.google.com/store/apps/details?id=com.v2raytun">Скачать в Google Play</a></p>
  <p class="muted">Если deep-link не открывается — импортируйте вручную:<br/><code>{sub_url}</code></p>
</div></div></body></html>"""
    return HTMLResponse(html)

from urllib.parse import quote
@app.get("/v2raytun_import_one/{token}")
async def v2raytun_import_one(token:str, vision:int=0, uuid:Optional[str]=None):
    text=await sub_plain(token, uuid)
    links=text.body.decode().splitlines()
    url=links[1] if vision else links[0]
    return RedirectResponse(f"v2raytun://import/{quote(url, safe='')}")

# ====== Aiogram 3 ======
router = Router()

@router.message(CommandStart())
async def cmd_start(m: Message):
    await ensure_user(m.from_user.id)
    bal = await get_balance(m.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 Тестовая подписка", callback_data="test_sub")],
        [InlineKeyboardButton(text="💼 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="🛒 Купить VPN", callback_data="buy")],
    ])
    await m.answer(f"Привет! Баланс: <b>{bal:.2f}</b>\nЦена: <b>{PRICE_VPN:.2f}</b> за {DAYS_VPN} дн.",
                   reply_markup=kb)

@router.callback_query(lambda c: c.data=="balance")
async def cb_balance(c):
    bal = await get_balance(c.from_user.id)
    await c.message.answer(f"Баланс: <b>{bal:.2f}</b>")
    await c.answer()

@router.callback_query(lambda c: c.data=="test_sub")
async def cb_test(c):
    # выдаём 1-дневную подписку без оплаты
    global DAYS_VPN
    old = DAYS_VPN;  DAYS_VPN = 1
    _, _, _, _, _, first_uuid = read_xray_reality()
    if not first_uuid:
        await c.message.answer("В XRAY_CONFIG нет клиента UUID."); await c.answer(); DAYS_VPN=old; return
    token = await create_subscription(c.from_user.id, first_uuid)
    DAYS_VPN = old
    u = _urls(token, first_uuid)
    await c.message.answer(text_v2raytun(token, first_uuid), reply_markup=kb_v2raytun(token, first_uuid), disable_web_page_preview=True)
    await c.answer()

@router.callback_query(lambda c: c.data=="buy")
async def cb_buy(c):
    bal = await get_balance(c.from_user.id)
    if bal < PRICE_VPN:
        await c.message.answer(f"Недостаточно средств. Баланс {bal:.2f}, нужно {PRICE_VPN:.2f}.")
        await c.answer(); return
    await add_balance(c.from_user.id, -PRICE_VPN)
    _, _, _, _, _, first_uuid = read_xray_reality()
    if not first_uuid:
        await c.message.answer("В XRAY_CONFIG нет клиента UUID."); await c.answer(); return
    token = await create_subscription(c.from_user.id, first_uuid)
    await c.message.answer(text_v2raytun(token, first_uuid), reply_markup=kb_v2raytun(token, first_uuid), disable_web_page_preview=True)
    await c.answer()

# ====== Runner ======
async def run_fastapi():
    config = uvicorn.Config(app, host="0.0.0.0", port=8001, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN в окружении.")
    await db_init()
    bot = Bot(BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher()
    dp.include_router(router)

    api_task = asyncio.create_task(run_fastapi())
    try:
        await dp.start_polling(bot)
    finally:
        api_task.cancel()
        with contextlib.suppress(Exception):
            await api_task

if __name__ == "__main__":
    import contextlib
    asyncio.run(main())
