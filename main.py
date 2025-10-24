#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ==========
#  main.py
# ==========
# Один файл = Telegram-бот (aiogram) + FastAPI сервер подписок под v2RayTun.
#
# Что умеет:
# - /start, меню, показать баланс
# - Пополнение: CryptoBot (если CRYPTOBOT_TOKEN), YooMoney (если YOOMONEY_TOKEN/YOOMONEY_WALLET)
# - Покупка VPN (30 дней, цена из PRICE_VPN), выдаёт подписку и deep-link для v2RayTun
# - Тестовая выдача подписки без оплаты (если платежи не настроены)
# - FastAPI эндпоинты:
#       /sub/{token}            -> 2 строки vless (NoFlow и Vision)
#       /sub_v2raytun/{token}   -> то же (алиас)
#       /subs/{token}           -> HTML-страница с кнопкой v2raytun://import-sub?url=...
#       /v2raytun_import_one/{token}?vision=0|1 -> редирект v2raytun://import/{URL}
#
# Требуемые пакеты:
#   pip install aiogram fastapi uvicorn aiosqlite cryptography
#   # (опционально, при использовании платежей)
#   pip install aiocryptopay yoomoney
#
# Запуск:
#   PUBLIC_HOST=64.188.64.214 PUBLIC_BASE=https://64.188.64.214 \
#   BOT_TOKEN=<TG_BOT_TOKEN> \
#   python3 main.py
#
# Бот и веб-сервер поднимаются сразу: бот в фоне, HTTP слушает 0.0.0.0:8001

import os
import asyncio
import base64
import json
import secrets
import time
import threading
from typing import Optional, Tuple

import aiosqlite
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse, RedirectResponse
import uvicorn

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# ---------- Конфиг через ENV ----------
BOT_TOKEN       = os.getenv("BOT_TOKEN", "8204126907:AAGAuUipqhzEkyfreOFCpBhMdaXtQ5xMN_o")               # ОБЯЗАТЕЛЬНО: токен Telegram-бота
DB_PATH         = os.getenv("DB_PATH", "/root/rel/bot_database.db")
XRAY_CONFIG     = os.getenv("XRAY_CONFIG", "/usr/local/etc/xray/config.json")
PUBLIC_HOST     = os.getenv("PUBLIC_HOST", "64.188.64.214")            # твой IP/домен
PUBLIC_BASE     = os.getenv("PUBLIC_BASE", f"https://{PUBLIC_HOST}")   # публичный базовый URL
PRICE_VPN       = float(os.getenv("PRICE_VPN", "0.0"))   # цена в вашей валюте
DAYS_VPN        = int(os.getenv("DAYS_VPN", "30"))

# Опциональные платежи
CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN", "")          # https://t.me/CryptoBot
YOOMONEY_TOKEN  = os.getenv("YOOMONEY_TOKEN", "")
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET", "")

# ---------- Глобалы бота ----------
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher(bot) if bot else None

# ---------- База данных ----------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,
  balance REAL NOT NULL DEFAULT 0,
  referrer_id INTEGER
);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  amount REAL NOT NULL,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  payload TEXT
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
        await db.executescript(SCHEMA_SQL)
        await db.commit()

async def ensure_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        exists = await cur.fetchone()
        if not exists:
            await db.execute("INSERT INTO users(user_id,balance) VALUES(?,0)", (user_id,))
            await db.commit()

async def get_balance(user_id: int) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return float(row[0]) if row else 0.0

async def add_balance(user_id: int, delta: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (delta, user_id))
        await db.commit()

# ---------- Reality утилиты ----------
def _b64u_nopad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def pbk_from_private_key(pk_str: str) -> str:
    try:
        raw = base64.b64decode(pk_str + "==")
    except Exception:
        raw = bytes.fromhex(pk_str)
    priv = x25519.X25519PrivateKey.from_private_bytes(raw)
    pub = priv.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                         format=serialization.PublicFormat.Raw)
    return _b64u_nopad(pub)

def read_xray_reality() -> Tuple[int, str, str, str, str, str]:
    """
    Возвращает (port, network, sni, sid, pbk, first_uuid)
    """
    with open(XRAY_CONFIG, "r", encoding="utf-8") as f:
        data = json.load(f)
    inbound = None
    for ib in data.get("inbounds", []):
        ss = ib.get("streamSettings", {}) or {}
        if ss.get("security") == "reality" or ss.get("realitySettings"):
            inbound = ib; break
    if not inbound:
        raise RuntimeError("Reality inbound not found in XRAY_CONFIG")

    port = int(inbound.get("port"))
    network = (inbound.get("streamSettings", {}) or {}).get("network", "tcp")
    rs = (inbound.get("streamSettings", {}) or {}).get("realitySettings", {}) or {}
    sni = (rs.get("serverNames") or [""])[0]
    sid = (rs.get("shortIds") or [""])[0]
    pk  = rs.get("privateKey") or ""
    pbk = pbk_from_private_key(pk) if pk else ""

    # первый UUID клиента
    first_uuid = ""
    try:
        clients = (inbound.get("settings", {}) or {}).get("clients") or []
        if clients:
            first_uuid = clients[0]["id"]
    except Exception:
        pass

    return port, network, sni, sid, pbk, first_uuid

def build_vless(host: str, port: int, uuid: str, network: str, sni: str, sid: str, pbk: str, flow: bool, name: str) -> str:
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

# ---------- v2RayTun генераторы ----------
def _urls_for_token(token: str, uuid: Optional[str] = None) -> dict:
    sub_txt = f"{PUBLIC_BASE}/sub_v2raytun/{token}"
    if uuid:
        sub_txt += f"?uuid={uuid}"
    subs_page = f"{PUBLIC_BASE}/subs/{token}" + (f"?uuid={uuid}" if uuid else "")
    deeplink = f"v2raytun://import-sub?url={sub_txt}"
    return {"sub_txt": sub_txt, "subs_page": subs_page, "deeplink": deeplink}

def kb_v2raytun(token: str, uuid: Optional[str] = None) -> types.InlineKeyboardMarkup:
    u = _urls_for_token(token, uuid)
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton("➕ Добавить в v2RayTun", url=u["deeplink"])],
        [types.InlineKeyboardButton("ℹ️ Информация о подписке", url=u["subs_page"])],
    ])
    return kb

def text_v2raytun(token: str, uuid: Optional[str] = None) -> str:
    u = _urls_for_token(token, uuid)
    return (
        "Ваш ключ готов! ✨\n\n"
        "Нажмите кнопку ниже, чтобы добавить подписку в приложение v2RayTun.\n"
        "Если deep-link не открывается — импортируйте вручную по ссылке:\n"
        f"{u['sub_txt']}\n\n"
        "⚙️ Клиент автоматически подхватит два сервера: NoFlow и Vision."
    )

async def send_v2raytun(bot: Bot, user_id: int, token: str, uuid: Optional[str]):
    await bot.send_message(user_id, text_v2raytun(token, uuid), reply_markup=kb_v2raytun(token, uuid), disable_web_page_preview=True)

# ---------- “Покупка” ----------
async def create_subscription(user_id: int, uuid: str) -> str:
    """
    Создаёт/продлевает подписку на DAYS_VPN дней. Возвращает token.
    """
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    expires = now + DAYS_VPN * 86400

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO subscriptions(token,user_id,expires_at) VALUES(?,?,?)",
                         (token, user_id, expires))
        await db.execute("INSERT OR REPLACE INTO vpn_links(token,user_id,uuid,created_at) VALUES(?,?,?,?)",
                         (token, user_id, uuid, now))
        await db.commit()
    return token

# ---------- Платежи (опционально) ----------
async def create_crypto_invoice(user_id: int, amount: float) -> str:
    """
    Возвращает URL на оплату в CryptoBot или пустую строку, если токен не задан.
    """
    if not CRYPTOBOT_TOKEN:
        return ""
    try:
        from aiocryptopay import AioCryptoPay, Networks
        cp = AioCryptoPay(token=CRYPTOBOT_TOKEN, network=Networks.MAIN_NET)
        invoice = await cp.create_invoice(asset="USDT", amount=amount)
        await cp.close()
        pay_url = invoice.pay_url
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO transactions(user_id,provider,amount,status,created_at,payload) VALUES(?,?,?,?,?,?)",
                             (user_id, "cryptobot", amount, "pending", int(time.time()), pay_url))
            await db.commit()
        return pay_url
    except Exception:
        return ""

async def create_yoomoney_link(user_id: int, amount: float) -> str:
    """
    Возвращает ссылку YooMoney QuickPay (если токен/кошелёк заданы), иначе пусто.
    """
    if not (YOOMONEY_TOKEN and YOOMONEY_WALLET):
        return ""
    try:
        from yoomoney import Quickpay
        q = Quickpay(receiver=YOOMONEY_WALLET, quickpay_form="shop",
                     targets=f"Пополнение {user_id}", paymentType="SB", sum=amount)
        pay_url = q.base_url
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO transactions(user_id,provider,amount,status,created_at,payload) VALUES(?,?,?,?,?,?)",
                             (user_id, "yoomoney", amount, "pending", int(time.time()), pay_url))
            await db.commit()
        return pay_url
    except Exception:
        return ""

# ---------- Aiogram: хэндлеры ----------
@dp.message_handler(commands=["start"])
async def start_cmd(m: types.Message):
    await ensure_user(m.from_user.id)
    bal = await get_balance(m.from_user.id)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("💳 Пополнить", "🛒 Купить VPN", "💼 Баланс", "🧪 Тестовая подписка")
    await m.answer(f"Привет! Баланс: <b>{bal:.2f}</b>\n"
                   f"Цена VPN: <b>{PRICE_VPN:.2f}</b> за {DAYS_VPN} дней.",
                   reply_markup=kb)

@dp.message_handler(lambda m: m.text == "💼 Баланс")
async def show_balance(m: types.Message):
    bal = await get_balance(m.from_user.id)
    await m.answer(f"Текущий баланс: <b>{bal:.2f}</b>")

@dp.message_handler(lambda m: m.text == "💳 Пополнить")
async def topup(m: types.Message):
    # сделаем 2 кнопки — опциональные
    amount = PRICE_VPN
    links = []
    url_c = await create_crypto_invoice(m.from_user.id, amount)
    if url_c:
        links.append(("CryptoBot (USDT)", url_c))
    url_y = await create_yoomoney_link(m.from_user.id, amount)
    if url_y:
        links.append(("YooMoney (Сбер)", url_y))

    if not links:
        await m.answer("Платёжные провайдеры не настроены. "
                       "Задайте переменные окружения CRYPTOBOT_TOKEN или YOOMONEY_TOKEN/YOOMONEY_WALLET.\n"
                       "Пока можете воспользоваться пунктом «🧪 Тестовая подписка».")
        return

    kb = types.InlineKeyboardMarkup()
    for title, url in links:
        kb.add(types.InlineKeyboardButton(title, url=url))
    await m.answer(f"Выберите способ пополнения на <b>{amount:.2f}</b>:", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "🛒 Купить VPN")
async def buy_vpn(m: types.Message):
    bal = await get_balance(m.from_user.id)
    if bal < PRICE_VPN:
        await m.answer(f"Недостаточно средств. Баланс <b>{bal:.2f}</b>, нужно <b>{PRICE_VPN:.2f}</b>.\n"
                       f"Нажмите «💳 Пополнить».")
        return

    # списываем и выдаём ключ
    await add_balance(m.from_user.id, -PRICE_VPN)

    # UUID — из XRAY_CONFIG (первый клиент) или из вашей БД/логики
    _, _, _, _, _, first_uuid = read_xray_reality()
    if not first_uuid:
        await m.answer("В XRAY_CONFIG не найден UUID клиента. Добавьте клиента в inbound.settings.clients[].id")
        return

    token = await create_subscription(m.from_user.id, first_uuid)
    await send_v2raytun(bot, m.from_user.id, token, first_uuid)

@dp.message_handler(lambda m: m.text == "🧪 Тестовая подписка")
async def test_sub(m: types.Message):
    # никаких оплат — сразу выдаём на 1 день
    _, _, _, _, _, first_uuid = read_xray_reality()
    if not first_uuid:
        await m.answer("В XRAY_CONFIG не найден UUID клиента. Добавьте клиента в inbound.settings.clients[].id")
        return
    global DAYS_VPN
    old_days = DAYS_VPN
    DAYS_VPN = 1
    token = await create_subscription(m.from_user.id, first_uuid)
    DAYS_VPN = old_days
    await send_v2raytun(bot, m.from_user.id, token, first_uuid)

# ---------- FastAPI сервер подписок ----------
app = FastAPI(title="rel-v2raytun-allinone")

async def token_valid(token: str) -> Tuple[Optional[int], Optional[int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        # subscriptions: token, user_id, expires_at
        cur = await db.execute("SELECT user_id, expires_at FROM subscriptions WHERE token=?", (token,))
        row = await cur.fetchone()
        if row:
            return int(row[0]), int(row[1])
    return None, None

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def sub_plain(token: str, uuid: Optional[str] = None):
    user_id, exp = await token_valid(token)
    if not user_id:
        raise HTTPException(404, "Token not found")
    port, network, sni, sid, pbk, _first_uuid = read_xray_reality()

    # uuid — из vpn_links, если есть
    real_uuid = uuid
    if not real_uuid:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT uuid FROM vpn_links WHERE token=?", (token,))
            r = await cur.fetchone()
            if r and r[0]:
                real_uuid = r[0]
    if not real_uuid:
        real_uuid = _first_uuid
    if not real_uuid:
        raise HTTPException(400, "UUID not found")

    v_no   = build_vless(PUBLIC_HOST, port, real_uuid, network, sni, sid, pbk, False, f"user{user_id}-NoFlow")
    v_flow = build_vless(PUBLIC_HOST, port, real_uuid, network, sni, sid, pbk, True,  f"user{user_id}-Vision")
    return PlainTextResponse(v_no + "\n" + v_flow, media_type="text/plain; charset=utf-8")

@app.get("/sub_v2raytun/{token}", response_class=PlainTextResponse)
async def sub_v2(token: str, uuid: Optional[str] = None):
    return await sub_plain(token, uuid)

@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token: str, uuid: Optional[str] = None):
    uid, exp = await token_valid(token)
    status_badge = "<span style='color:#2ecc71'>Активна</span>" if uid else "<span style='color:#e67e22'>Не найдена</span>"
    sub_url  = f"{PUBLIC_BASE}/sub_v2raytun/{token}" + (f"?uuid={uuid}" if uuid else "")
    deep     = f"v2raytun://import-sub?url={sub_url}"
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Информация о подписке</title>
<style>body{{font-family:system-ui,Segoe UI,Roboto,Ubuntu,sans-serif;background:#0b0f14;color:#fff;margin:0}}
.wrap{{max-width:640px;margin:24px auto;padding:16px}}
.card{{background:#0f151d;border-radius:14px;padding:16px;margin-bottom:16px;border:1px solid #1f2a38}}
.btn{{display:inline-block;background:#1e90ff;color:#fff;padding:12px 16px;border-radius:12px;text-decoration:none;margin-right:8px}}
.muted{{color:#a9b2be}} code{{background:#0b0f14;border:1px solid #1f2a38;border-radius:8px;padding:4px 6px}}</style>
</head><body><div class="wrap">
<h2>Подписка</h2><div class="card"><div>Статус: {status_badge}</div></div>
<div class="card">
  <h3>v2RayTun</h3>
  <p><a class="btn" href="{deep}">Добавить подписку в v2RayTun</a>
     <a class="btn" href="https://play.google.com/store/apps/details?id=com.v2raytun">Скачать в Google Play</a></p>
  <p class="muted">Если deep-link не открывается — импортируйте вручную:<br/><code>{sub_url}</code></p>
</div></div></body></html>"""
    return HTMLResponse(html)

from urllib.parse import quote
@app.get("/v2raytun_import_one/{token}")
async def v2raytun_import_one(token: str, vision: int = 0, uuid: Optional[str] = None):
    text = await sub_plain(token, uuid)
    links = text.body.decode().splitlines()
    url = links[1] if vision else links[0]
    return RedirectResponse(f"v2raytun://import/{quote(url, safe='')}")

# ---------- запуск обоих подсистем ----------
def run_uvicorn_background():
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")

async def async_main():
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN")
    await db_init()
    # fastapi в отдельном потоке
    t = threading.Thread(target=run_uvicorn_background, daemon=True)
    t.start()
    # бот
    executor.start_polling(dp, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(async_main())
