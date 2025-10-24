#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, time, base64, asyncio, secrets, contextlib
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

# --- Платежи ---
from yoomoney import Client as YooClient, Quickpay
from aiocryptopay import AioCryptoPay, Networks

# ===================== Конфигурация =====================
BOT_TOKEN   = os.getenv("BOT_TOKEN", "8204126907:AAGAuUipqhzEkyfreOFCpBhMdaXtQ5xMN_o")

DB_PATH     = os.getenv("DB_PATH", "/root/rel/bot_database.db")
XRAY_CONFIG = os.getenv("XRAY_CONFIG", "/usr/local/etc/xray/config.json")

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "64.188.64.214")
PUBLIC_BASE = os.getenv("PUBLIC_BASE", f"http://{PUBLIC_HOST}")  # HTTP, как ты просил
API_HOST    = os.getenv("API_HOST", "0.0.0.0")
API_PORT    = int(os.getenv("API_PORT", "8001"))

# Цены/параметры
PRICE_VPN   = float(os.getenv("VPN_SUBSCRIPTION_PRICE", "100"))  # руб
DAYS_VPN    = int(os.getenv("DAYS_VPN", "30"))

# YooMoney
YOOMONEY_WALLET       = os.getenv("YOOMONEY_WALLET", "4100118758572112")
YOOMONEY_TOKEN        = os.getenv("YOOMONEY_TOKEN",  "4100118758572112.13EBE862F9FE5CEF1E565C77A561584DD5651427DF02D3214BA6FCBF9BCD9CCBFFA058B13F34A4DB6BAF7214DAFB06E57B32E3B55ECC159676A6CE6F5B3BC5C8C37C2CE1FDA52E818E2A1B7518FEE6E2FDF2E1CC630F03A8771818CE4D7C576873CFF7D0EC73EFE5E8CA9C95C072B5E64629B35532F6AF1DDE8ADD144B8B5B07")
YOOMONEY_FEE_PERCENT  = float(os.getenv("YOOMONEY_FEE_PERCENT", "0.05"))  # 5%

# CryptoBot (AioCryptoPay)
CRYPTO_TOKEN  = os.getenv("CRYPTO_TOKEN", "47563:AAzvRdC9XPKzyMpvayG5Hdji1HrPx1E4zoL")  # тестовая сеть
CRYPTO_NET    = os.getenv("CRYPTO_NETWORK", "TEST_NET")  # MAIN_NET | TEST_NET

# Рефералка
REFERRAL_PERCENT = float(os.getenv("REFERRAL_PERCENT", "0.2"))  # 20%

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

CREATE TABLE IF NOT EXISTS referrals (
  user_id    INTEGER PRIMARY KEY,   -- кто пришёл
  ref_by     INTEGER                -- кто пригласил
);

CREATE TABLE IF NOT EXISTS payments (
  payment_id TEXT PRIMARY KEY,      -- label (yoo) или invoice_id (crypto)
  user_id    INTEGER NOT NULL,
  method     TEXT NOT NULL,         -- 'yoomoney' | 'crypto'
  amount     REAL NOT NULL,
  currency   TEXT NOT NULL,
  status     TEXT NOT NULL,         -- 'pending' | 'paid' | 'credited'
  meta       TEXT,                  -- json: label/invoice url и т.п.
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pay_user ON payments(user_id);
"""

async def db_init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL); await db.commit()

async def ensure_user(uid: int, ref_by: Optional[int] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
        exists = await cur.fetchone()
        if not exists:
            await db.execute("INSERT INTO users(user_id,balance) VALUES(?,0)", (uid,))
            # рефералка: запишем, если валидный ref_by и не self
            if ref_by and ref_by != uid:
                cur2 = await db.execute("SELECT 1 FROM referrals WHERE user_id=?", (uid,))
                if not await cur2.fetchone():
                    await db.execute("INSERT INTO referrals(user_id,ref_by) VALUES(?,?)", (uid, ref_by))
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

async def get_referrer(uid: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT ref_by FROM referrals WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None

# ================= Reality helpers =============
def _b64u(b: bytes) -> str: return base64.urlsafe_b64encode(b).decode().rstrip("=")

def pbk_from_private_key(pk_str: str) -> str:
    raw = None
    with contextlib.suppress(Exception):
        raw = base64.urlsafe_b64decode(pk_str + "==")
    if raw is None:
        with contextlib.suppress(Exception):
            raw = bytes.fromhex(pk_str)
    if raw is None or len(raw) != 32:
        raise ValueError("Reality privateKey должен быть 32 байта (base64url). Проверь XRAY_CONFIG.")
    priv = x25519.X25519PrivateKey.from_private_bytes(raw)
    pub  = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    return _b64u(pub)

def read_xray_reality() -> Tuple[int, str, str, str, str, str]:
    with open(XRAY_CONFIG, "r", encoding="utf-8") as f: data = json.load(f)
    inbound = None
    for ib in data.get("inbounds", []):
        ss = ib.get("streamSettings", {}) or {}
        if ss.get("security") == "reality" or ss.get("realitySettings"):
            inbound = ib; break
    if not inbound: raise RuntimeError("Reality inbound не найден в XRAY_CONFIG")
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
        if clients: first_uuid = clients[0]["id"]
    return port, network, sni, sid, pbk, first_uuid

def build_vless(host,port,uuid,network,sni,sid,pbk,vision:bool,name:Optional[str]):
    base=f"vless://{uuid}@{host}:{port}?type={network}&security=reality&fp=chrome&alpn=h2,http/1.1"
    if pbk: base+=f"&pbk={pbk}"
    if sni: base+=f"&sni={sni}"
    if sid: base+=f"&sid={sid}"
    if vision: base+="&flow=xtls-rprx-vision"; name=name or "Reality Vision"
    else: name=name or "Reality NoFlow"
    return f"{base}#{name}"

# ================ v2RayTun URLs/Keyboard ================
def _urls(token: str, uuid: Optional[str]=None)->dict:
    sub_txt=f"{PUBLIC_BASE}/sub_v2raytun/{token}" + (f"?uuid={uuid}" if uuid else "")
    subs_page=f"{PUBLIC_BASE}/subs/{token}" + (f"?uuid={uuid}" if uuid else "")
    deep=f"v2raytun://import-sub?url={sub_txt}"
    return {"sub_txt":sub_txt,"subs_page":subs_page,"deeplink":deep}

def kb_v2raytun(token, uuid=None)->InlineKeyboardMarkup:
    u=_urls(token,uuid)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть страницу подписки", url=u["subs_page"])],
        [InlineKeyboardButton(text="📄 Текст подписки (ручной импорт)", url=u["sub_txt"])],
    ])

def text_v2raytun(token, uuid=None)->str:
    u=_urls(token,uuid)
    return ("Ваш ключ готов! ✨\n\n"
            "1) Откройте страницу подписки и нажмите «Добавить в v2RayTun».\n"
            "2) Если deep-link не сработал — импортируйте вручную:\n"
            f"{u['sub_txt']}\n\n"
            "Импортируются два профиля: NoFlow и Vision.")

# ================== issue subscription ==================
async def create_subscription(uid:int, uuid:str)->str:
    token = secrets.token_urlsafe(24)
    now   = int(time.time())
    exp   = now + DAYS_VPN*86400
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO subscriptions(token,user_id,expires_at) VALUES(?,?,?)",(token,uid,exp))
        await db.execute("INSERT OR REPLACE INTO vpn_links(token,user_id,uuid,created_at) VALUES(?,?,?,?)",(token,uid,uuid,now))
        await db.commit()
    return token

async def token_valid(token:str)->Tuple[Optional[int],Optional[int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT user_id,expires_at FROM subscriptions WHERE token=?", (token,))
        row=await cur.fetchone()
        return (int(row[0]), int(row[1])) if row else (None, None)

# ====================== FastAPI =========================
app = FastAPI(title="rel v2raytun")

@app.get("/health")
async def health(): return {"ok":True,"ts":int(time.time())}

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def sub_plain(token:str, uuid:Optional[str]=None):
    uid,_=await token_valid(token)
    if not uid: raise HTTPException(404,"Token not found")
    port,network,sni,sid,pbk,first_uuid=read_xray_reality()
    real_uuid=uuid
    if not real_uuid:
        async with aiosqlite.connect(DB_PATH) as db:
            cur=await db.execute("SELECT uuid FROM vpn_links WHERE token=?", (token,))
            r=await cur.fetchone()
            if r and r[0]: real_uuid=r[0]
    if not real_uuid: real_uuid=first_uuid
    if not real_uuid: raise HTTPException(400,"UUID not found")
    v_no   = build_vless(PUBLIC_HOST,port,real_uuid,network,sni,sid,pbk,False,f"user{uid}-NoFlow")
    v_flow = build_vless(PUBLIC_HOST,port,real_uuid,network,sni,sid,pbk,True ,f"user{uid}-Vision")
    return PlainTextResponse(v_no+"\n"+v_flow, media_type="text/plain; charset=utf-8")

@app.get("/sub_v2raytun/{token}", response_class=PlainTextResponse)
async def sub_v2(token:str, uuid:Optional[str]=None):
    return await sub_plain(token, uuid)

@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token:str, uuid:Optional[str]=None):
    uid,_=await token_valid(token)
    status="<span style='color:#2ecc71'>Активна</span>" if uid else "<span style='color:#e67e22'>Не найдена</span>"
    sub_url=f"{PUBLIC_BASE}/sub_v2raytun/{token}" + (f"?uuid={uuid}" if uuid else "")
    deep=f"v2raytun://import-sub?url={sub_url}"
    html=f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/><title>Информация о подписке</title>
<style>body{{font-family:system-ui,Segoe UI,Roboto,Ubuntu,sans-serif;background:#0b0f14;color:#fff;margin:0}}
.wrap{{max-width:720px;margin:28px auto;padding:0 16px}}.card{{background:#0f151d;border:1px solid #1f2a38;border-radius:14px;padding:16px;margin:14px 0}}
.btn{{display:inline-block;background:#1e90ff;color:#fff;padding:12px 16px;border-radius:12px;text-decoration:none}}</style>
</head><body><div class="wrap"><h2>Подписка</h2>
<div class="card">Статус: {status}</div>
<div class="card">
  <p><a class="btn" href="{deep}">Добавить подписку в v2RayTun</a></p>
  <p style="opacity:.7">Если deep-link не сработал — импортируйте вручную:<br/><code>{sub_url}</code></p>
</div></div></body></html>"""
    return HTMLResponse(html)

from urllib.parse import quote
@app.get("/v2raytun_import_one/{token}")
async def v2raytun_import_one(token:str, vision:int=0, uuid:Optional[str]=None):
    text=await sub_plain(token, uuid); links=text.body.decode().splitlines()
    url=links[1] if vision else links[0]
    return RedirectResponse(f"v2raytun://import/{quote(url, safe='')}")

# ===================== Payments =========================
def _yoo_make_link(user_id:int, amount:float)->tuple[str,str]:
    """
    Создаём YooMoney ссылку (QuickPay shop). Возвращаем (url, label)
    """
    label = f"ym_{user_id}_{secrets.token_hex(8)}"
    qp = Quickpay(
        receiver=YOOMONEY_WALLET,
        quickpay_form="shop",
        targets="Пополнение VPN",
        paymentType="SB",    # Сбер/ЮMoney; можно оставить пустым чтобы выбрать на стороне ЮMoney
        sum=amount,
        label=label
    )
    return qp.redirected_url, label

async def _yoo_check_paid(label:str)->Optional[float]:
    """
    Проверяем историю по label. Возвращаем сумму, если оплата найдена.
    Важно: клиент синхронный – запускаем в тред-пуле.
    """
    loop = asyncio.get_running_loop()
    def _check():
        client = YooClient(YOOMONEY_TOKEN)
        ops = client.operation_history(label=label)
        for op in ops.operations or []:
            if getattr(op, "label", None) == label and op.status == "success" and op.direction == "in":
                return float(op.amount)
        return None
    return await loop.run_in_executor(None, _check)

async def _crypto_client()->AioCryptoPay:
    net = Networks.MAIN_NET if CRYPTO_NET.upper() == "MAIN_NET" else Networks.TEST_NET
    return AioCryptoPay(token=CRYPTO_TOKEN, network=net)

async def _crypto_create_invoice(user_id:int, amount_rub:float)->tuple[str,str,float]:
    """
    Создаём инвойс в USDT (к примеру). Для простоты считаем эквивалент как amount_rub / 100 (условный курс 1 USDT=100 RUB).
    Хочешь — подменишь на свой курс.
    """
    usdt = round(amount_rub / 100.0, 2) or 1.0
    cp = await _crypto_client()
    inv = await cp.create_invoice(asset="USDT", amount=usdt, description=f"TopUp {user_id}")
    return inv.pay_url, str(inv.invoice_id), float(inv.amount)

async def _crypto_check_paid(invoice_id:str)->Optional[float]:
    cp = await _crypto_client()
    res = await cp.get_invoices(invoice_ids=[int(invoice_id)])
    if res.items and res.items[0].status == "paid":
        return float(res.items[0].amount)
    return None

async def _record_payment(payment_id:str, user_id:int, method:str, amount:float, currency:str, status:str, meta:str=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO payments(payment_id,user_id,method,amount,currency,status,meta,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (payment_id, user_id, method, amount, currency, status, meta, int(time.time()))
        )
        await db.commit()

async def _credit_balance(user_id:int, amount:float, method:str):
    """
    Зачисление пользователю и отчисление рефереру.
    Для YooMoney учитываем комиссию YOOMONEY_FEE_PERCENT.
    """
    net = amount
    if method == "yoomoney":
        net = round(amount * (1.0 - YOOMONEY_FEE_PERCENT), 2)
    await add_balance(user_id, net)

    ref = await get_referrer(user_id)
    if ref:
        bonus = round(net * REFERRAL_PERCENT, 2)
        if bonus > 0:
            await add_balance(ref, bonus)

# ===================== Aiogram 3 ========================
router = Router()

def main_menu(bal:float)->InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 Тестовая подписка", callback_data="test_sub")],
        [InlineKeyboardButton(text="🛒 Купить VPN", callback_data="buy")],
        [InlineKeyboardButton(text="➕ Пополнить баланс", callback_data="topup")],
        [InlineKeyboardButton(text="💼 Баланс", callback_data="balance")],
    ])

def topup_menu()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="YooMoney (карта/ЮMoney)", callback_data="topup_yoo")],
        [InlineKeyboardButton(text="CryptoBot (USDT)", callback_data="topup_crypto")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]
    ])

@router.message(CommandStart())
async def cmd_start(m: Message):
    # рефералка: /start ref_123456789
    ref_by = None
    if m.text and " " in m.text:
        payload = m.text.split(" ", 1)[1].strip()
        if payload.startswith("ref_"):
            with contextlib.suppress(Exception):
                ref_by = int(payload[4:])
    await ensure_user(m.from_user.id, ref_by=ref_by)
    bal = await get_balance(m.from_user.id)
    await m.answer(f"Привет! Баланс: <b>{bal:.2f}</b>\nЦена подписки: <b>{PRICE_VPN:.2f} ₽</b> за {DAYS_VPN} дней.",
                   reply_markup=main_menu(bal))

@router.callback_query(lambda c: c.data=="menu")
async def cb_menu(c: CallbackQuery):
    bal = await get_balance(c.from_user.id)
    await c.message.edit_text(f"Главное меню. Баланс: <b>{bal:.2f}</b> ₽", reply_markup=main_menu(bal))
    await c.answer()

@router.callback_query(lambda c: c.data=="balance")
async def cb_balance(c: CallbackQuery):
    bal = await get_balance(c.from_user.id)
    await c.message.answer(f"Баланс: <b>{bal:.2f}</b> ₽")
    await c.answer()

@router.callback_query(lambda c: c.data=="test_sub")
async def cb_test(c: CallbackQuery):
    global DAYS_VPN
    old = DAYS_VPN; DAYS_VPN = 1
    _, _, _, _, _, first_uuid = read_xray_reality()
    if not first_uuid:
        await c.message.answer("В XRAY_CONFIG нет клиента UUID."); await c.answer(); DAYS_VPN=old; return
    token = await create_subscription(c.from_user.id, first_uuid)
    DAYS_VPN = old
    await c.message.answer(text_v2raytun(token, first_uuid), reply_markup=kb_v2raytun(token, first_uuid), disable_web_page_preview=True)
    await c.answer()

@router.callback_query(lambda c: c.data=="buy")
async def cb_buy(c: CallbackQuery):
    bal = await get_balance(c.from_user.id)
    if bal < PRICE_VPN:
        await c.message.answer(f"Недостаточно средств. Баланс {bal:.2f} ₽, нужно {PRICE_VPN:.2f} ₽.\nПополнить баланс: кнопка ниже.")
        await c.answer(); return
    await add_balance(c.from_user.id, -PRICE_VPN)
    _, _, _, _, _, first_uuid = read_xray_reality()
    if not first_uuid:
        await c.message.answer("В XRAY_CONFIG нет клиента UUID."); await c.answer(); return
    token = await create_subscription(c.from_user.id, first_uuid)
    await c.message.answer(text_v2raytun(token, first_uuid), reply_markup=kb_v2raytun(token, first_uuid), disable_web_page_preview=True)
    await c.answer()

# ----------- Пополнение -----------
@router.callback_query(lambda c: c.data=="topup")
async def cb_topup(c: CallbackQuery):
    await c.message.answer("Выберите способ пополнения:", reply_markup=topup_menu())
    await c.answer()

@router.callback_query(lambda c: c.data=="topup_yoo")
async def cb_topup_yoo(c: CallbackQuery):
    amount = PRICE_VPN  # можно сделать выбор суммы
    url, label = _yoo_make_link(c.from_user.id, amount)
    # запишем pending
    await _record_payment(payment_id=label, user_id=c.from_user.id, method="yoomoney", amount=amount, currency="RUB", status="pending", meta=url)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить YooMoney", url=url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_yoo:{label}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]
    ])
    await c.message.answer(f"Счёт на <b>{amount:.2f} ₽</b> создан.\nПосле оплаты нажми «Проверить оплату».", reply_markup=kb)
    await c.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("check_yoo:"))
async def cb_check_yoo(c: CallbackQuery):
    label = c.data.split(":",1)[1]
    paid = await _yoo_check_paid(label)
    if not paid:
        await c.message.answer("Платёж пока не найден. Подожди минутку и нажми «Проверить оплату» ещё раз.")
        await c.answer(); return
    # Кредитуем и отмечаем
    await _credit_balance(c.from_user.id, paid, method="yoomoney")
    await _record_payment(payment_id=label, user_id=c.from_user.id, method="yoomoney", amount=paid, currency="RUB", status="credited", meta="")
    bal = await get_balance(c.from_user.id)
    await c.message.answer(f"Платёж YooMoney получен: <b>{paid:.2f} ₽</b>\nЗачислено с учётом комиссии: <b>{paid*(1-YOOMONEY_FEE_PERCENT):.2f} ₽</b>\nТекущий баланс: <b>{bal:.2f} ₽</b>")
    await c.answer()

@router.callback_query(lambda c: c.data=="topup_crypto")
async def cb_topup_crypto(c: CallbackQuery):
    amount = PRICE_VPN
    pay_url, invoice_id, usdt = await _crypto_create_invoice(c.from_user.id, amount)
    await _record_payment(payment_id=invoice_id, user_id=c.from_user.id, method="crypto", amount=usdt, currency="USDT", status="pending", meta=pay_url)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💠 Оплатить в CryptoBot", url=pay_url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_crypto:{invoice_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]
    ])
    await c.message.answer(f"Инвойс создан: <b>{usdt:.2f} USDT</b> (≈ {amount:.2f}₽). После оплаты проверь статус.", reply_markup=kb)
    await c.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("check_crypto:"))
async def cb_check_crypto(c: CallbackQuery):
    invoice_id = c.data.split(":",1)[1]
    paid = await _crypto_check_paid(invoice_id)
    if not paid:
        await c.message.answer("Инвойс ещё не оплачен. Нажми «Проверить оплату» чуть позже.")
        await c.answer(); return
    # Для простоты считаем 1 USDT = 100₽ (как при создании инвойса)
    rub = float(paid) * 100.0
    await _credit_balance(c.from_user.id, rub, method="crypto")
    await _record_payment(payment_id=invoice_id, user_id=c.from_user.id, method="crypto", amount=paid, currency="USDT", status="credited", meta="")
    bal = await get_balance(c.from_user.id)
    await c.message.answer(f"Платёж CryptoBot получен: <b>{paid:.2f} USDT</b> (≈ {rub:.2f}₽)\nЗачислено: <b>{rub:.2f}₽</b>\nБаланс: <b>{bal:.2f}₽</b>")
    await c.answer()

# ==================== RUNNERS ===========================
async def run_fastapi():
    config = uvicorn.Config(app, host=API_HOST, port=API_PORT, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN.")
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
