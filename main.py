#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, time, base64, asyncio, secrets, contextlib, uuid, subprocess
from typing import Optional, Tuple, List
from urllib.parse import quote

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

# Платежи
from yoomoney import Client as YooClient, Quickpay
from aiocryptopay import AioCryptoPay, Networks

# ===================== Конфигурация =====================
BOT_TOKEN   = os.getenv("BOT_TOKEN", "CHANGE_ME")

DB_PATH     = os.getenv("DB_PATH", "/root/rel/bot_database.db")
XRAY_CONFIG = os.getenv("XRAY_CONFIG", "/usr/local/etc/xray/config.json")
XRAY_SERVICE= os.getenv("XRAY_SERVICE", "xray")

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "127.0.0.1")
PUBLIC_BASE = os.getenv("PUBLIC_BASE", f"http://{PUBLIC_HOST}:8001")  # все ссылки с :8001, пока нет nginx
API_HOST    = os.getenv("API_HOST", "0.0.0.0")
API_PORT    = int(os.getenv("API_PORT", "8001"))

# Цены (руб.)
PRICE_7D  = float(os.getenv("PRICE_7D",  "40"))
PRICE_1M  = float(os.getenv("PRICE_1M",  "100"))
PRICE_3M  = float(os.getenv("PRICE_3M",  "270"))
PRICE_6M  = float(os.getenv("PRICE_6M",  "500"))
PRICE_12M = float(os.getenv("PRICE_12M", "900"))

# Рефералка
REFERRAL_PERCENT      = float(os.getenv("REFERRAL_PERCENT", "0.2"))   # 20%
YOOMONEY_FEE_PERCENT  = float(os.getenv("YOOMONEY_FEE_PERCENT", "0.05"))

# YooMoney
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET", "4100118758572112")
YOOMONEY_TOKEN  = os.getenv("YOOMONEY_TOKEN",  "CHANGE_ME")

# CryptoBot (инвойсы в фиате RUB)
CRYPTO_TOKEN   = os.getenv("CRYPTO_TOKEN", "CHANGE_ME")
CRYPTO_NETWORK = os.getenv("CRYPTO_NETWORK", "TEST_NET")  # TEST_NET | MAIN_NET
CRYPTO_ACCEPTED = os.getenv("CRYPTO_ACCEPTED", "USDT,TON,BTC,ETH,LTC")  # список активов для выбора

PLANS = {
    "7d":  {"title": "7 дней",    "days": 7,   "price": PRICE_7D},
    "1m":  {"title": "1 месяц",   "days": 30,  "price": PRICE_1M},
    "3m":  {"title": "3 месяца",  "days": 90,  "price": PRICE_3M},
    "6m":  {"title": "6 месяцев", "days": 180, "price": PRICE_6M},
    "12m": {"title": "12 месяцев","days": 365, "price": PRICE_12M},
}

# ===================== База =====================
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  user_id    INTEGER PRIMARY KEY,
  balance    REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subscriptions (
  token      TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  uuid       TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS referrals (
  user_id    INTEGER PRIMARY KEY,
  ref_by     INTEGER
);
CREATE TABLE IF NOT EXISTS payments (
  payment_id TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL,
  method     TEXT NOT NULL,   -- 'yoomoney' | 'crypto'
  plan_id    TEXT,
  amount     REAL NOT NULL,
  currency   TEXT NOT NULL,   -- 'RUB' | 'FIAT/CRYPTO'
  status     TEXT NOT NULL,   -- 'pending' | 'credited'
  meta       TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pay_user ON payments(user_id);
"""

async def db_init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()

async def ensure_user(uid:int, ref_by:Optional[int]=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
        if not await cur.fetchone():
            await db.execute("INSERT INTO users(user_id,balance) VALUES(?,0)", (uid,))
        if ref_by and ref_by!=uid:
            cur2=await db.execute("SELECT 1 FROM referrals WHERE user_id=?", (uid,))
            if not await cur2.fetchone():
                await db.execute("INSERT INTO referrals(user_id,ref_by) VALUES(?,?)", (uid, ref_by))
        await db.commit()

async def add_balance(uid:int, delta:float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (delta, uid))
        await db.commit()

async def get_referrer(uid:int)->Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT ref_by FROM referrals WHERE user_id=?", (uid,))
        row=await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None

# ================= Reality / XRAY =================
def _b64u(b:bytes)->str: return base64.urlsafe_b64encode(b).decode().rstrip("=")

def pbk_from_private_key(pk_str:str)->str:
    raw=None
    with contextlib.suppress(Exception): raw=base64.urlsafe_b64decode(pk_str+"==")
    if raw is None:
        with contextlib.suppress(Exception): raw=bytes.fromhex(pk_str)
    if raw is None or len(raw)!=32:
        raise ValueError("Reality privateKey должен быть 32 байта (base64url/hex).")
    priv=x25519.X25519PrivateKey.from_private_bytes(raw)
    pub=priv.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return _b64u(pub)

def _load_xray()->dict:
    with open(XRAY_CONFIG,"r",encoding="utf-8") as f: return json.load(f)

def _save_xray(data:dict):
    tmp="/tmp/xray_cfg_tmp.json"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    os.replace(tmp, XRAY_CONFIG)

def _reload_xray():
    try:
        subprocess.run(["systemctl","reload",XRAY_SERVICE], check=True)
    except Exception:
        subprocess.run(["systemctl","restart",XRAY_SERVICE], check=False)

def _get_reality_inbound(data:dict):
    for ib in data.get("inbounds",[]):
        ss=ib.get("streamSettings",{}) or {}
        if ss.get("security")=="reality" or ss.get("realitySettings"):
            return ib
    return None

def read_xray_reality()->Tuple[int,str,str,str,str]:
    data=_load_xray()
    inbound=_get_reality_inbound(data)
    if not inbound: raise RuntimeError("Reality inbound не найден")
    port=int(inbound.get("port"))
    network=(inbound.get("streamSettings",{}) or {}).get("network","tcp")
    rs=(inbound.get("streamSettings",{}) or {}).get("realitySettings",{}) or {}
    sni=(rs.get("serverNames") or [""])[0]
    sid=(rs.get("shortIds") or [""])[0]
    pk=rs.get("privateKey") or ""
    pbk=pbk_from_private_key(pk) if pk else ""
    return port, network, sni, sid, pbk

def xray_add_client(new_uuid:str):
    data=_load_xray()
    inbound=_get_reality_inbound(data)
    if not inbound: raise RuntimeError("Reality inbound не найден")
    settings=inbound.setdefault("settings",{})
    clients=settings.setdefault("clients",[])
    if any(c.get("id")==new_uuid for c in clients): return
    clients.append({"id": new_uuid, "flow": "xtls-rprx-vision"})
    _save_xray(data); _reload_xray()

def xray_remove_client(rm_uuid:str):
    data=_load_xray()
    inbound=_get_reality_inbound(data)
    if not inbound: return
    settings=inbound.setdefault("settings",{})
    clients=settings.setdefault("clients",[])
    new_clients=[c for c in clients if c.get("id")!=rm_uuid]
    if len(new_clients)!=len(clients):
        settings["clients"]=new_clients
        _save_xray(data); _reload_xray()

def build_vless(host,port,uuid,network,sni,sid,pbk,vision:bool,name:Optional[str]):
    base=f"vless://{uuid}@{host}:{port}?type={network}&security=reality&fp=chrome&alpn=h2,http/1.1"
    if pbk: base+=f"&pbk={pbk}"
    if sni: base+=f"&sni={sni}"
    if sid: base+=f"&sid={sid}"
    if vision: base+="&flow=xtls-rprx-vision"; name=name or "Reality Vision"
    else: name=name or "Reality NoFlow"
    return f"{base}#{name}"

# ================ v2RayTun URLs/Keyboard ================
def _urls(token:str)->dict:
    sub_txt =f"{PUBLIC_BASE}/sub_v2raytun/{token}"
    subs_pg =f"{PUBLIC_BASE}/subs/{token}"
    deep    =f"v2raytun://import-sub?url={sub_txt}"
    return {"sub_txt":sub_txt,"subs_page":subs_pg,"deeplink":deep}

def kb_v2raytun(token)->InlineKeyboardMarkup:
    u=_urls(token)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть страницу подписки", url=u["subs_page"])],
        [InlineKeyboardButton(text="📄 Текст подписки (ручной импорт)", url=u["sub_txt"])],
    ])

def text_v2raytun(token)->str:
    u=_urls(token)
    return ("Ключ готов! ✨\n\n"
            "1) Откройте страницу и нажмите «Добавить в v2RayTun».\n"
            "2) Если deep-link не сработал — импортируйте вручную:\n"
            f"{u['sub_txt']}\n\n"
            "Импортируются 2 профиля: NoFlow и Vision.")

# ================== выдача/истечение ==================
async def create_subscription(uid:int, days:int)->str:
    new_uuid=str(uuid.uuid4())
    xray_add_client(new_uuid)
    token=secrets.token_urlsafe(24)
    now=int(time.time()); exp=now + days*86400
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO subscriptions(token,user_id,uuid,expires_at) VALUES(?,?,?,?)",
            (token, uid, new_uuid, exp)
        )
        await db.commit()
    return token

async def get_sub(token:str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT user_id, uuid, expires_at FROM subscriptions WHERE token=?", (token,))
        return await cur.fetchone()

async def expire_gc_loop():
    while True:
        try:
            now=int(time.time())
            async with aiosqlite.connect(DB_PATH) as db:
                cur=await db.execute("SELECT token, uuid FROM subscriptions WHERE expires_at<=?", (now,))
                rows=await cur.fetchall()
                if rows:
                    for tkn, u in rows:
                        xray_remove_client(u)
                    await db.execute("DELETE FROM subscriptions WHERE expires_at<=?", (now,))
                    await db.commit()
        except Exception:
            pass
        await asyncio.sleep(60)

# ====================== FastAPI =========================
app=FastAPI(title="rel v2raytun")

@app.get("/health")
async def health(): return {"ok":True,"ts":int(time.time())}

@app.get("/sub/{token}", response_class=PlainTextResponse)
async def sub_plain(token:str):
    row=await get_sub(token)
    if not row: raise HTTPException(404,"Token not found")
    uid, user_uuid, exp = int(row[0]), row[1], int(row[2])
    if exp <= int(time.time()):
        raise HTTPException(410, "Subscription expired")
    port,network,sni,sid,pbk=read_xray_reality()
    v_no  = build_vless(PUBLIC_HOST,port,user_uuid,network,sni,sid,pbk,False,f"user{uid}-NoFlow")
    v_vis = build_vless(PUBLIC_HOST,port,user_uuid,network,sni,sid,pbk,True ,f"user{uid}-Vision")
    return PlainTextResponse(v_no+"\n"+v_vis, media_type="text/plain; charset=utf-8")

@app.get("/sub_v2raytun/{token}", response_class=PlainTextResponse)
async def sub_v2(token:str): return await sub_plain(token)

@app.get("/subs/{token}", response_class=HTMLResponse)
async def subs_page(token:str):
    row=await get_sub(token)
    uid, exp = (int(row[0]), int(row[2])) if row else (None, None)
    now=int(time.time())
    if not uid: status="<span style='color:#e67e22'>Не найдена</span>"
    elif exp and exp<=now: status="<span style='color:#e74c3c'>Истекла</span>"
    else: status="<span style='color:#2ecc71'>Активна</span>"

    sub_url=f"{PUBLIC_BASE}/sub_v2raytun/{token}"
    deep=f"v2raytun://import-sub?url={sub_url}"
    html=f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/><title>Подписка</title>
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

@app.get("/v2raytun_import_one/{token}")
async def v2raytun_import_one(token:str, vision:int=0):
    text=await sub_plain(token); links=text.body.decode().splitlines()
    url=links[1] if vision else links[0]
    return RedirectResponse(f"v2raytun://import/{quote(url, safe='')}")

# ====================== Payments =========================
async def _record_payment(payment_id:str, user_id:int, method:str, plan_id:str, amount:float, currency:str, status:str, meta:str=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO payments(payment_id,user_id,method,plan_id,amount,currency,status,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (payment_id, user_id, method, plan_id, amount, currency, status, meta, int(time.time()))
        )
        await db.commit()

async def _credit_referral(user_id:int, net_rub:float):
    ref = await get_referrer(user_id)
    if ref:
        bonus = max(0.0, round(net_rub * REFERRAL_PERCENT, 2))
        if bonus > 0:
            await add_balance(ref, bonus)

# --- YooMoney ---
def _yoo_make_link(user_id:int, plan_id:str, amount_rub:float)->tuple[str,str]:
    label=f"ym_{user_id}_{plan_id}_{secrets.token_hex(6)}"
    qp=Quickpay(
        receiver=YOOMONEY_WALLET, quickpay_form="shop",
        targets=f"VPN {plan_id}", paymentType="SB", sum=amount_rub, label=label
    )
    return qp.redirected_url, label

async def _yoo_check_paid(label:str)->Optional[float]:
    loop=asyncio.get_running_loop()
    def _check():
        client=YooClient(YOOMONEY_TOKEN)
        ops=client.operation_history(label=label)
        for op in ops.operations or []:
            if getattr(op,"label",None)==label and op.status=="success" and op.direction=="in":
                return float(op.amount)
        return None
    return await loop.run_in_executor(None, _check)

# --- CryptoBot (инвойс в RUB, выбор любой валюты в @CryptoBot) ---
def _cp_net():
    return Networks.MAIN_NET if CRYPTO_NETWORK.upper()=="MAIN_NET" else Networks.TEST_NET

async def _crypto_create_invoice(user_id: int, plan_id: str, amount_rub: float) -> tuple[str, str]:
    """
    Создаём инвойс в RUB (fiat). Пользователь в @CryptoBot сам выберет актив (USDT/TON/BTC/ETH/LTC и т.д.)
    и оплатит точную сумму в рублях. Возвращаем bot_invoice_url — ссылка откроет именно @CryptoBot.
    """
    assets = [a.strip().upper() for a in CRYPTO_ACCEPTED.split(",") if a.strip()]
    async with AioCryptoPay(token=CRYPTO_TOKEN, network=_cp_net()) as cp:
        inv = await cp.create_invoice(
            amount=float(amount_rub),
            fiat="RUB",
            accepted_assets=assets or "all",
            description=f"VPN {plan_id} for {user_id}",
            allow_anonymous=True,
            allow_comments=True,
        )
        url = getattr(inv, "bot_invoice_url", None) or getattr(inv, "pay_url", None)
        if not url:
            raise RuntimeError("CryptoBot API не вернул ссылку на инвойс.")
        return url, str(inv.invoice_id)

async def _crypto_check_paid(invoice_id: str) -> bool:
    async with AioCryptoPay(token=CRYPTO_TOKEN, network=_cp_net()) as cp:
        res = await cp.get_invoices(invoice_ids=[int(invoice_id)])
        # В твоей версии это список:
        if isinstance(res, list):
            inv = res[0] if res else None
        else:
            inv = res.items[0] if getattr(res, "items", None) else None
        return bool(inv and getattr(inv, "status", None) == "paid")

# ===================== Aiogram 3 ========================
router=Router()

def main_menu()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 Тест 1 день", callback_data="test_sub")],
        [InlineKeyboardButton(text="⏱ Тест 2 минуты", callback_data="test_2m")],
        [InlineKeyboardButton(text="🛒 Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="💼 Баланс", callback_data="balance")],
    ])

@router.message(CommandStart())
async def cmd_start(m:Message):
    ref_by=None
    if m.text and " " in m.text:
        p=m.text.split(" ",1)[1].strip()
        if p.startswith("ref_"):
            with contextlib.suppress(Exception): ref_by=int(p[4:])
    await ensure_user(m.from_user.id, ref_by=ref_by)
    await m.answer("Привет! Выберите действие:", reply_markup=main_menu())

@router.callback_query(lambda c: c.data=="balance")
async def cb_balance(c:CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT balance FROM users WHERE user_id=?", (c.from_user.id,))
        row=await cur.fetchone()
    bal=float(row[0]) if row else 0.0
    await c.message.answer(f"Баланс: <b>{bal:.2f}₽</b>"); await c.answer()

@router.callback_query(lambda c: c.data=="test_sub")
async def cb_test1d(c:CallbackQuery):
    token=await create_subscription(c.from_user.id, days=1)
    await c.message.answer(text_v2raytun(token), reply_markup=kb_v2raytun(token), disable_web_page_preview=True)
    await c.answer()

@router.callback_query(lambda c: c.data=="test_2m")
async def cb_test2m(c:CallbackQuery):
    new_uuid=str(uuid.uuid4()); xray_add_client(new_uuid)
    token=secrets.token_urlsafe(24); now=int(time.time()); exp=now+120
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO subscriptions(token,user_id,uuid,expires_at) VALUES(?,?,?,?)",
                         (token,c.from_user.id,new_uuid,exp)); await db.commit()
    await c.message.answer("Выдал подписку на 2 минуты для проверки истечения.")
    await c.message.answer(text_v2raytun(token), reply_markup=kb_v2raytun(token), disable_web_page_preview=True)
    await c.answer()

def plan_keyboard()->InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"7 дней — {PLANS['7d']['price']}₽",   callback_data="buy_plan:7d")],
        [InlineKeyboardButton(text=f"1 месяц — {PLANS['1m']['price']}₽", callback_data="buy_plan:1m")],
        [InlineKeyboardButton(text=f"3 месяца — {PLANS['3m']['price']}₽",callback_data="buy_plan:3m")],
        [InlineKeyboardButton(text=f"6 месяцев — {PLANS['6m']['price']}₽",callback_data="buy_plan:6m")],
        [InlineKeyboardButton(text=f"12 месяцев — {PLANS['12m']['price']}₽",callback_data="buy_plan:12m")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")],
    ])

def pay_method_keyboard(plan_id:str)->InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="YooMoney (карта/ЮMoney)", callback_data=f"pay_yoo:{plan_id}")],
        [InlineKeyboardButton(text="CryptoBot (оплата в @CryptoBot)", callback_data=f"pay_crypto:{plan_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy")],
    ])

@router.callback_query(lambda c: c.data=="buy")
async def cb_buy(c:CallbackQuery):
    await c.message.answer("Выберите тариф:", reply_markup=plan_keyboard()); await c.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("buy_plan:"))
async def cb_buy_plan(c:CallbackQuery):
    plan_id=c.data.split(":",1)[1]; plan=PLANS.get(plan_id)
    if not plan: await c.answer("Неизвестный тариф"); return
    await c.message.answer(f"Тариф <b>{plan['title']}</b> — <b>{plan['price']}₽</b>\nВыберите способ оплаты:",
                           reply_markup=pay_method_keyboard(plan_id)); await c.answer()

# ---- YooMoney ----
@router.callback_query(lambda c: c.data and c.data.startswith("pay_yoo:"))
async def cb_pay_yoo(c:CallbackQuery):
    plan_id=c.data.split(":",1)[1]; plan=PLANS.get(plan_id)
    if not plan: await c.answer("Неизвестный тариф"); return
    url,label=_yoo_make_link(c.from_user.id, plan_id, plan["price"])
    await _record_payment(label, c.from_user.id, "yoomoney", plan_id, plan["price"], "RUB", "pending", url)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить YooMoney", url=url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"chk_yoo:{label}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy")],
    ])
    await c.message.answer("Счёт создан. После оплаты нажмите «Проверить оплату».", reply_markup=kb); await c.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("chk_yoo:"))
async def cb_chk_yoo(c:CallbackQuery):
    label=c.data.split(":",1)[1]
    paid=await _yoo_check_paid(label)
    if not paid:
        await c.message.answer("Оплата не найдена. Подождите и проверьте ещё раз."); await c.answer(); return
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT plan_id FROM payments WHERE payment_id=?", (label,))
        row=await cur.fetchone()
    plan_id=row[0] if row else "1m"
    days=PLANS.get(plan_id, {"days":30})["days"]
    net=round(float(paid)*(1.0-YOOMONEY_FEE_PERCENT),2)
    await _record_payment(label, c.from_user.id, "yoomoney", plan_id, float(paid), "RUB", "credited", "")
    await _credit_referral(c.from_user.id, net_rub=net)
    token=await create_subscription(c.from_user.id, days=days)
    await c.message.answer(f"Оплата YooMoney: {paid:.2f}₽ (зачислено {net:.2f}₽).\nВыдана подписка на {days} дней.")
    await c.message.answer(text_v2raytun(token), reply_markup=kb_v2raytun(token), disable_web_page_preview=True)
    await c.answer()

# ---- CryptoBot (fiat RUB + выбор актива в боте) ----
@router.callback_query(lambda c: c.data and c.data.startswith("pay_crypto:"))
async def cb_pay_crypto(c:CallbackQuery):
    plan_id=c.data.split(":",1)[1]; plan=PLANS.get(plan_id)
    if not plan: await c.answer("Неизвестный тариф"); return
    pay_url, invoice_id = await _crypto_create_invoice(c.from_user.id, plan_id, plan["price"])
    await _record_payment(invoice_id, c.from_user.id, "crypto", plan_id, plan["price"], "FIAT/CRYPTO", "pending", pay_url)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💠 Оплатить в @CryptoBot", url=pay_url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"chk_crypto:{invoice_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy")],
    ])
    await c.message.answer("Инвойс создан в RUB. В @CryptoBot выберите удобную валюту/способ и оплатите, затем нажмите «Проверить оплату».", reply_markup=kb); await c.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("chk_crypto:"))
async def cb_chk_crypto(c:CallbackQuery):
    invoice_id=c.data.split(":",1)[1]
    ok=await _crypto_check_paid(invoice_id)
    if not ok:
        await c.message.answer("Инвойс ещё не оплачен. Проверь позже."); await c.answer(); return
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT plan_id, user_id FROM payments WHERE payment_id=?", (invoice_id,))
        row=await cur.fetchone()
    plan_id=row[0]; uid=row[1]
    days=PLANS.get(plan_id, {"days":30})["days"]
    await _record_payment(invoice_id, uid, "crypto", plan_id, PLANS[plan_id]["price"], "FIAT/CRYPTO", "credited", "")
    await _credit_referral(uid, net_rub=float(PLANS[plan_id]["price"]))
    token=await create_subscription(uid, days=days)
    await c.message.answer(f"Оплата через @CryptoBot получена.\nВыдана подписка на {days} дней.")
    await c.message.answer(text_v2raytun(token), reply_markup=kb_v2raytun(token), disable_web_page_preview=True)
    await c.answer()

@router.callback_query(lambda c: c.data=="menu")
async def cb_menu(c:CallbackQuery):
    await c.message.answer("Главное меню:", reply_markup=main_menu()); await c.answer()

# ==================== RUNNERS ===========================
async def run_fastapi():
    config=uvicorn.Config(app, host=API_HOST, port=API_PORT, log_level="info", loop="asyncio")
    server=uvicorn.Server(config); await server.serve()

async def main():
    if not BOT_TOKEN or BOT_TOKEN=="CHANGE_ME":
        raise SystemExit("Задай BOT_TOKEN через переменные окружения.")
    await db_init()
    asyncio.create_task(expire_gc_loop())

    bot=Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp=Dispatcher(); dp.include_router(router)

    api_task=asyncio.create_task(run_fastapi())
    try:
        await dp.start_polling(bot)
    finally:
        api_task.cancel()
        with contextlib.suppress(Exception): await api_task

if __name__=="__main__":
    asyncio.run(main())
