#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import base64
import asyncio
import secrets
import contextlib
from typing import Optional, Tuple

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse, RedirectResponse
import uvicorn

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode


# ===================== ENV =====================
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")                        # токен бота
DB_PATH     = os.getenv("DB_PATH", "/root/rel/bot_database.db") # путь к sqlite
XRAY_CONFIG = os.getenv("XRAY_CONFIG", "/usr/local/etc/xray/config.json")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "127.0.0.1")             # IP/домен, куда подключаются клиенты
PUBLIC_BASE = os.getenv("PUBLIC_BASE", f"http://{PUBLIC_HOST}") # БЕЗ :8001; nginx опционален
API_HOST    = os.getenv("API_HOST", "0.0.0.0")                  # где слушает FastAPI
API_PORT    = int(os.getenv("API_PORT", "8001"))                # порт FastAPI

PRICE_VPN   = float(os.getenv("PRICE_VPN", "150"))              # цена (для /buy)
DAYS_VPN    = int(os.getenv("DAYS_VPN", "30"))                  # длительность подписки (дней)


# ===================== DB ======================
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  user_id    INTEGER PRIMARY KEY,
  balance    REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subscriptions (
  token      TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS vpn_links (
  token      TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  uuid       TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
"""

async def db_init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()

async def ensure_user(uid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
        if not await cur.fetchone():
            await db.execute("INSERT INTO users(user_id,balance) VALUES(?,0)", (uid,))
            await db.commit()

async def get_balance(uid: int) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        return float(row[0]) if row else 0.0

async def add_balance(uid: int, delta: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (delta, uid))
        await db.commit()


# ================= Reality helpers =============
def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def pbk_from_private_key(pk_str: str) -> str:
    """
    Возвращает публичный ключ Reality (pbk) из приватного (privateKey).
    Поддерживает base64url (основной случай) и hex.
    """
    raw = None
    with contextlib.suppress(Exception):
        raw = base64.urlsafe_b64decode(pk_str + "==")
    if raw is None:
        with contextlib.suppress(Exception):
            raw = bytes.fromhex(pk_str)
    if raw is None or len(raw) != 32:
        raise ValueError("Reality privateKey должен быть 32 байта (base64url). Проверь XRAY_CONFIG.")
    priv = x25519.X25519PrivateKey.from_private_bytes(raw)
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    return _b64u(pub)

def read_xray_reality() -> Tuple[int, str, str, str, str, str]:
    """
    Читает из XRAY_CONFIG параметры Reality inbound.
    Возвращает: (port, network, sni, sid, pbk, first_uuid)
    """
    with open(XRAY_CONFIG, "r", encoding="utf-8") as f:
        data = json.load(f)

    inbound = None
    for ib in data.get("inbounds", []):
        ss = ib.get("streamSettings", {}) or {}
        if ss.get("security") == "reality" or ss.get("realitySettings"):
            inbound = ib
            break
    if not inbound:
        raise RuntimeError("Reality inbound не найден в XRAY_CONFIG")

    port = int(inbound.get("port"))
    network = (inbound.get("streamSettings", {}) or {}).get("network", "tcp")
    rs = (inbound.get("streamSettings", {}) or {}).get("realitySettings", {}) or {}
    sni = (rs.get("serverNames") or [""])[0]
    sid = (rs.get("shortIds") or [""])[0]
    pk  = rs.get("privateKey") or ""
    pbk = pbk_from_private_key(pk) if pk else ""

    first_uuid = ""
    with contextlib.suppress(Exception):
        clients = (inbound.get("settings", {}) or {}).get("clients") or []
        if clients:
            first_uuid = clients[0]["id"]

    return port, network, sni, sid, pbk, first_uuid

def build_vless(host, port, uuid, network, sni, sid, pbk, vision: bool, name: Optional[str]):
    base = f"vless://{uuid}@{host}:{port}?type={network}&security=reality&fp=chrome&alpn=h2,http/1.1"
    if pbk: base += f"&pbk={pbk}"
    if sni: base += f"&sni={sni}"
    if sid: base += f"&sid={sid}"
    if vision:
        base += "&flow=xtls-rprx-vision"
        name = name or "Reality Vision"
    else:
        name = name or "Reality NoFlow"
    return f"{base}#{name}"


# ================ v2RayTun URLs/Keyboard ================
def _urls(token: str, uuid: Optional[str] = None) -> dict:
    sub_txt  = f"{PUBLIC_BASE}/sub_v2raytun/{token}"
    if uuid:
        sub_txt += f"?uuid={uuid}"
    subs_page = f"{PUBLIC_BASE}/subs/{token}" + (f"?uuid={uuid}" if uuid else "")
    deep      = f"v2raytun://import-sub?url={sub_txt}"
    return {"sub_txt": sub_txt, "subs_page": subs_page, "deeplink": deep}

def kb_v2raytun(token: str, uuid: Optional[str] = None) -> InlineKeyboardMarkup:
    u = _urls(token, uuid)
    # В КНОПКАХ — только http/https (телеграм не пропускает v2raytun://)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть страницу подписки", url=u["subs_page"])],
        [InlineKeyboardButton(text="📄 Текст подписки (ручной импорт)", url=u["sub_txt"])],
    ])

def text_v2raytun(token: str, uuid: Optional[str] = None) -> str:
    u = _urls(token, uuid)
    return (
        "Ваш ключ готов! ✨\n\n"
        "1) Нажмите «Открыть страницу подписки» и в браузере жмите «Добавить в v2RayTun».\n"
        "2) Если deep-link не сработал — импортируйте вручную:\n"
        f"{u['sub_txt']}\n\n"
        "Импортируются два профиля: NoFlow и Vision."
    )


# ================== issue subscription ==================
async def create_subscription(uid: int, uuid: str) -> str:
    token = secrets.token_urlsafe(24)
    now   = int(time.time())
    exp   = now + DAYS_VPN * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO subscriptions(token,user_id,expires_at) VALUES(?,?,?)",
            (token, uid, exp)
        )
        await db.execute(
            "INSERT OR REPLACE INTO vpn_links(token,user_id,uuid,created_at) VALUES(?,?,?,?)",
            (token, uid, uuid, now)
        )
        await db.commit()
    return token

async def token_valid(token: str) -> Tuple[Optional[int], Optional[int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, expires_at FROM subscriptions WHERE token=?", (token,)
        )
        row = await cur.fetchone()
        return (int(row[0]), int(row[1])) if row else (None, None)


# ====================== FastAPI =========================
app = FastAPI(title="rel v2raytun")

@app.get("/health")
async def health():
    return {"ok": True, "ts": int(time.time())}

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def sub_plain(token: str, uuid: Optional[str] = None):
    uid, _ = await token_valid(token)
    if not uid:
        raise HTTPException(404, "Token not found")

    port, network, sni, sid, pbk, first_uuid = read_xray_reality()

    real_uuid = uuid
    if not real_uuid:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT uuid FROM vpn_links WHERE token=?", (token,))
            r = await cur.fetchone()
            if r and r[0]:
                real_uuid = r[0]
    if not real_uuid:
        real_uuid = first_uuid
    if not real_uuid:
        raise HTTPException(400, "UUID not found in XRAY_CONFIG or DB")

    v_no   = build_vless(PUBLIC_HOST, port, real_uuid, network, sni, sid, pbk, False, f"user{uid}-NoFlow")
    v_flow = build_vless(PUBLIC_HOST, port, real_uuid, network, sni, sid, pbk, True,  f"user{uid}-Vision")
    return PlainTextResponse(v_no + "\n" + v_flow, media_type="text/plain; charset=utf-8")

@app.get("/sub_v2raytun/{token}", response_class=PlainTextResponse)
async def sub_v2(token: str, uuid: Optional[str] = None):
    return await sub_plain(token, uuid)

@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token: str, uuid: Optional[str] = None):
    uid, _ = await token_valid(token)
    status = "<span style='color:#2ecc71'>Активна</span>" if uid else "<span style='color:#e67e22'>Не найдена</span>"
    sub_url = f"{PUBLIC_BASE}/sub_v2raytun/{token}" + (f"?uuid={uuid}" if uuid else "")
    deep    = f"v2raytun://import-sub?url={sub_url}"
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Информация о подписке</title>
<style>
body{{font-family:system-ui,Segoe UI,Roboto,Ubuntu,sans-serif;background:#0b0f14;color:#fff;margin:0}}
.wrap{{max-width:720px;margin:28px auto;padding:0 16px}}
.card{{background:#0f151d;border:1px solid #1f2a38;border-radius:14px;padding:16px;margin:14px 0}}
.btn{{display:inline-block;background:#1e90ff;color:#fff;padding:12px 16px;border-radius:12px;text-decoration:none}}
.muted{{color:#a9b2be}} code{{background:#0b0f14;border:1px solid #1f2a38;border-radius:8px;padding:4px 6px}}
</style></head><body><div class="wrap">
<h2>Подписка</h2>
<div class="card">Статус: {status}</div>
<div class="card">
  <p><a class="btn" href="{deep}">Добавить подписку в v2RayTun</a></p>
  <p class="muted">Если deep-link не сработал — импортируйте вручную:<br/>
  <code>{sub_url}</code></p>
</div>
</div></body></html>"""
    return HTMLResponse(html)

# (опционально) импорт одного узла из подписки
from urllib.parse import quote
@app.get("/v2raytun_import_one/{token}")
async def v2raytun_import_one(token: str, vision: int = 0, uuid: Optional[str] = None):
    text = await sub_plain(token, uuid)
    links = text.body.decode().splitlines()
    url = links[1] if vision else links[0]
    return RedirectResponse(f"v2raytun://import/{quote(url, safe='')}")


# ===================== Aiogram 3 ========================
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
    await m.answer(
        f"Привет! Баланс: <b>{bal:.2f}</b>\n"
        f"Цена: <b>{PRICE_VPN:.2f}</b> за {DAYS_VPN} дн.",
        reply_markup=kb
    )

@router.callback_query(lambda c: c.data == "balance")
async def cb_balance(c: CallbackQuery):
    bal = await get_balance(c.from_user.id)
    await c.message.answer(f"Баланс: <b>{bal:.2f}</b>")
    await c.answer()

@router.callback_query(lambda c: c.data == "test_sub")
async def cb_test(c: CallbackQuery):
    # выдаём 1 день пробной подписки без списания
    global DAYS_VPN
    old = DAYS_VPN
    DAYS_VPN = 1
    _, _, _, _, _, first_uuid = read_xray_reality()
    if not first_uuid:
        await c.message.answer("В XRAY_CONFIG нет клиента UUID.")
        await c.answer()
        DAYS_VPN = old
        return
    token = await create_subscription(c.from_user.id, first_uuid)
    DAYS_VPN = old
    await c.message.answer(
        text_v2raytun(token, first_uuid),
        reply_markup=kb_v2raytun(token, first_uuid),
        disable_web_page_preview=True
    )
    await c.answer()

@router.callback_query(lambda c: c.data == "buy")
async def cb_buy(c: CallbackQuery):
    bal = await get_balance(c.from_user.id)
    if bal < PRICE_VPN:
        await c.message.answer(f"Недостаточно средств. Баланс {bal:.2f}, нужно {PRICE_VPN:.2f}.")
        await c.answer()
        return
    await add_balance(c.from_user.id, -PRICE_VPN)
    _, _, _, _, _, first_uuid = read_xray_reality()
    if not first_uuid:
        await c.message.answer("В XRAY_CONFIG нет клиента UUID.")
        await c.answer()
        return
    token = await create_subscription(c.from_user.id, first_uuid)
    await c.message.answer(
        text_v2raytun(token, first_uuid),
        reply_markup=kb_v2raytun(token, first_uuid),
        disable_web_page_preview=True
    )
    await c.answer()


# ==================== RUNNERS ===========================
async def run_fastapi():
    # если порт занят — падаем, чтобы ты это увидел сразу
    config = uvicorn.Config(app, host=API_HOST, port=API_PORT, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN (экспортируй переменную окружения).")

    await db_init()

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
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
    asyncio.run(main())
