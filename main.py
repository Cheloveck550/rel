import asyncio
import logging
import secrets
import uuid
from decimal import Decimal

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

from aiocryptopay import AioCryptoPay, Networks
from yoomoney import Quickpay, Client

import aiosqlite
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================== Конфигурация =====================
BOT_TOKEN = "8204126907:AAGAuUipqhzEkyfreOFCpBhMdaXtQ5xMN_o"
YOOMONEY_WALLET = "4100118758572112"
YOOMONEY_TOKEN = "4100118758572112.13EBE862F9FE5CEF1E565C77A561584DD5651427DF02D3214BA6FCBF9BCD9CCBFFA058B13F34A4DB6BAF7214DAFB06E57B32E3B55ECC159676A6CE6F5B3BC5C8C37C2CE1FDA52E818E2A1B7518FEE6E2FDF2E1CC630F03A8771818CE4D7C576873CFF7D0EC73EFE5E8CA9C95C072B5E64629B35532F6AF1DDE8ADD144B8B5B07"
REFERRAL_PERCENT = 0.2        # 20% от пополнения
YOOMONEY_FEE_PERCENT = 0.05    # 5% комиссия YooMoney
VPN_SUBSCRIPTION_PRICE = 100   # Цена подписки в рублях

DOMAIN = "64.188.64.214"       # для ссылок вида http://<DOMAIN>/subs/<token>

# Ключи сервера для формирования ссылки vless (PUBLIC KEY и SHORT ID)
PUBLIC_KEY = "m7n-24tmvfTdp2-Szr-vAaM3t9NzGDpTNrva6xM6-ls"
SHORT_ID   = "ba4211bb433df45d"

DB_PATH = "bot_database.db"             # локально рядом с main.py
DB_ABS  = "/root/rel/bot_database.db"   # для server.py используем абсолютный путь

# ---------- Инициализация бота и провайдеров ----------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Инициализация CryptoPay
# crypto_pay = AioCryptoPay('457050:AAeSxxok8YAr7DgKK7s965MGgAyjHoDL6yP', network=Networks.MAIN_NET) # основная сеть
crypto_pay = AioCryptoPay(token='47563:AAzvRdC9XPKzyMpvayG5Hdji1HrPx1E4zoL', network=Networks.TEST_NET)  # тестовая сеть

# ======================= FSM =======================
class PaymentState(StatesGroup):
    waiting_for_payment_method = State()
    waiting_for_cryptobot_amount = State()
    waiting_for_yoomoney_amount = State()
    waiting_for_vpn_confirmation = State()

# =================== Инициализация БД ===================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0,
                vpn_active_until DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id INTEGER,
                referral_id INTEGER PRIMARY KEY,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                type TEXT,
                description TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS referral_earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referral_id INTEGER,
                amount REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                token TEXT UNIQUE,
                expires_at TEXT,
                traffic_limit_gb REAL
            )
        ''')
        # таблица, которую читает server.py для выдачи ссылки HappVPN
        await db.execute('''
            CREATE TABLE IF NOT EXISTS vpn_links (
                user_id INTEGER PRIMARY KEY,
                vpn_link TEXT,
                expires_at DATETIME
            )
        ''')
        await db.commit()

# ===================== Клавиатуры =====================
def main_menu_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Пополнить баланс", callback_data="top_up_balance")
    kb.button(text="🔐 Купить VPN", callback_data="buy_vpn")
    kb.button(text="👥 Реферальная система", callback_data="referral_system")
    kb.button(text="💼 Профиль", callback_data="profile")
    kb.adjust(1)
    return kb.as_markup()

def confirm_cancel_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="confirm_vpn")
    kb.button(text="❌ Отмена", callback_data="back_to_main")
    kb.adjust(2)
    return kb.as_markup()

def payment_methods_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 CryptoBot (0%)", callback_data="payment_cryptobot")
    kb.button(text=f"💳 YooMoney (+{int(YOOMONEY_FEE_PERCENT*100)}%)", callback_data="payment_yoomoney")
    kb.button(text="🔙 Назад", callback_data="back_to_main")
    kb.adjust(1)
    return kb.as_markup()

def back_to_payment_methods_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="back_to_payment_methods")
    return kb.as_markup()

# =================== Вспомогательные ===================
async def get_user_balance(user_id: int) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else 0.0

async def add_vpn_link(user_id: int, user_uuid: str):
    """
    Создаёт/обновляет для пользователя готовую VLESS ссылку в таблице vpn_links.
    """
    expires_at = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    vpn_link = (
        f"vless://{user_uuid}@{DOMAIN}:443?"
        f"type=tcp&security=reality&pbk={PUBLIC_KEY}"
        f"&sni=www.google.com&flow=xtls-rprx-vision&sid={SHORT_ID}#Pro100VPN"
    )
    async with aiosqlite.connect(DB_PATH) as db:
        # один пользователь — одна активная ссылка (обновляем)
        await db.execute(
            "INSERT OR REPLACE INTO vpn_links (user_id, vpn_link, expires_at) VALUES (?, ?, ?)",
            (user_id, vpn_link, expires_at)
        )
        await db.commit()

# ======================== Хэндлеры ========================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username

    referrer_id = None
    if len(message.text.split()) > 1:
        try:
            referrer_id = int(message.text.split()[1])
        except ValueError:
            referrer_id = None

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
        if referrer_id and referrer_id != user_id:
            cursor = await db.execute('SELECT 1 FROM users WHERE user_id = ?', (referrer_id,))
            if await cursor.fetchone():
                await db.execute('INSERT OR IGNORE INTO referrals (referrer_id, referral_id) VALUES (?, ?)', (referrer_id, user_id))
        await db.commit()

    await message.answer("👋 Добро пожаловать!\nВыберите действие:", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "top_up_balance")
async def top_up_balance(callback: types.CallbackQuery):
    await callback.message.edit_text("💳 Выберите способ оплаты:", reply_markup=payment_methods_keyboard())

@dp.callback_query(F.data == "back_to_payment_methods")
async def back_to_payment_methods(callback: types.CallbackQuery):
    await callback.message.edit_text("💳 Выберите способ оплаты:", reply_markup=payment_methods_keyboard())

# -------------------- CryptoBot --------------------
@dp.callback_query(F.data == "payment_cryptobot")
async def payment_cryptobot(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💎 Введите сумму пополнения в рублях (мин. 100):",
        reply_markup=back_to_payment_methods_keyboard()
    )
    await state.set_state(PaymentState.waiting_for_cryptobot_amount)

@dp.message(PaymentState.waiting_for_cryptobot_amount)
async def process_cryptopay_payment(message: types.Message, state: FSMContext):
    try:
        if message.text == "🔙 Назад":
            await state.clear()
            await message.answer("💳 Выберите способ оплаты:", reply_markup=payment_methods_keyboard())
            return

        amount = Decimal(message.text.replace(',', '.'))
        if amount < 100:
            await message.answer("❌ Минимальная сумма пополнения — 100 рублей")
            return

        invoice = await crypto_pay.create_invoice(
            currency_type="fiat",
            fiat="RUB",
            amount=str(amount),
            description="Пополнение баланса",
            accepted_assets=["USDT", "TON", "BTC", "ETH", "BNB", "TRX"],
            swap_to="USDT"
        )

        await state.update_data(amount=float(amount), invoice_id=getattr(invoice, 'invoice_id', None), attempts=0)

        pay_url = getattr(invoice, 'bot_invoice_url', None) or getattr(invoice, 'pay_url', None) or getattr(invoice, 'url', None)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data="check_cryptobot_payment")]
        ])

        await message.answer(
            f"💳 Для пополнения на {amount:.2f} RUB — оплатите по ссылке:\n{pay_url}\n\n"
            "На оплату даётся 15 минут. После оплаты нажмите «Проверить».",
            reply_markup=kb
        )
    except Exception as e:
        logger.exception(f"CryptoBot payment error: {e}")
        await message.answer("❌ Ошибка при создании платежа. Попробуйте другую сумму.")
        await state.clear()

@dp.callback_query(F.data == "check_cryptobot_payment")
async def check_cryptobot_payment(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("⌛ Проверяем оплату...")
    await asyncio.sleep(3)

    data = await state.get_data()
    invoice_id = data.get("invoice_id")
    amount = Decimal(str(data.get("amount"))) if data.get("amount") is not None else None
    attempts = data.get("attempts", 0) + 1

    if attempts > 10:
        await callback.message.answer("❌ Превышено количество попыток. Начните заново.")
        await state.clear()
        return

    await state.update_data(attempts=attempts)

    if not invoice_id:
        await callback.message.answer("⚠️ Данные платежа устарели. Начните заново.")
        await state.clear()
        return

    try:
        invs = await crypto_pay.get_invoices(invoice_ids=[invoice_id])
        status = getattr(invs[0], 'status', None) if invs else None

        if status == "paid":
            user_id = callback.from_user.id
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (float(amount), user_id))
                await db.execute('INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)',
                                 (user_id, float(amount), 'deposit', 'Пополнение через CryptoBot'))

                # Реферальный бонус
                cursor = await db.execute('SELECT referrer_id FROM referrals WHERE referral_id = ?', (user_id,))
                referrer = await cursor.fetchone()
                if referrer:
                    referrer_id = referrer[0]
                    ref_bonus = float(amount) * REFERRAL_PERCENT
                    await db.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (ref_bonus, referrer_id))
                    await db.execute('INSERT INTO referral_earnings (referrer_id, referral_id, amount) VALUES (?, ?, ?)',
                                     (referrer_id, user_id, ref_bonus))
                    try:
                        await bot.send_message(referrer_id, f"🎉 Реферал пополнил баланс! +{ref_bonus:.2f} ₽")
                    except Exception:
                        pass
                await db.commit()

            await callback.message.answer(f"✅ Оплата получена! Баланс пополнен на {amount:.2f} ₽")
            await state.clear()
        else:
            await callback.message.answer(f"⌛ Оплата не найдена (попытка {attempts}/10). Попробуйте позже.")
    except Exception as e:
        logger.exception(f"Ошибка проверки криптоплатежа: {e}")
        await callback.message.answer("⚠️ Ошибка проверки. Попробуйте позже.")

# -------------------- YooMoney --------------------
@dp.callback_query(F.data == "payment_yoomoney")
async def payment_yoomoney_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("💳 Введите сумму пополнения в рублях:", reply_markup=back_to_payment_methods_keyboard())
    await state.set_state(PaymentState.waiting_for_yoomoney_amount)

@dp.message(PaymentState.waiting_for_yoomoney_amount)
async def process_yoomoney_payment(message: types.Message, state: FSMContext):
    try:
        if message.text == "🔙 Назад":
            await state.clear()
            await message.answer("💳 Выберите способ оплаты:", reply_markup=payment_methods_keyboard())
            return

        amount = Decimal(message.text.replace(',', '.'))
        if amount < 100:
            await message.answer("❌ Минимальная сумма пополнения — 100 рублей")
            return

        amount_with_fee = amount * (1 + Decimal(YOOMONEY_FEE_PERCENT))
        payment_id = str(uuid.uuid4())

        quickpay = Quickpay(
            receiver=YOOMONEY_WALLET,
            quickpay_form="shop",
            targets="Пополнение баланса",
            paymentType="SB",
            sum=amount_with_fee.quantize(Decimal('0.01')),
            label=payment_id
        )

        await state.update_data(payment_id=payment_id, amount=float(amount), payment_method="yoomoney")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data="check_yoomoney_payment")]
        ])

        await message.answer(
            f"💳 Оплата через YooMoney\n"
            f"Сумма: {amount:.2f} ₽\nКомиссия: {YOOMONEY_FEE_PERCENT*100:.0f}%\nИтого: {amount_with_fee:.2f} ₽\n\n"
            f"Ссылка для оплаты: {quickpay.redirected_url}",
            reply_markup=kb
        )
    except Exception as e:
        logger.exception(f"YooMoney payment error: {e}")
        await message.answer("❌ Ошибка при создании платежа")
        await state.clear()

@dp.callback_query(F.data == "check_yoomoney_payment")
async def check_yoomoney_payment(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    payment_id = data.get("payment_id")

    if not payment_id:
        await callback.answer("❌ Данные платежа не найдены")
        return

    try:
        client = Client(YOOMONEY_TOKEN)
        history = client.operation_history(label=payment_id)

        operation_found = False
        for operation in history.operations:
            if getattr(operation, 'label', None) == payment_id and getattr(operation, 'status', None) == "success":
                operation_found = True
                break

        if operation_found:
            amount = float(data.get("amount") or 0)
            user_id = callback.from_user.id
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
                await db.execute('INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)',
                                 (user_id, amount, 'deposit', 'Пополнение через YooMoney'))

                cursor = await db.execute('SELECT referrer_id FROM referrals WHERE referral_id = ?', (user_id,))
                referrer = await cursor.fetchone()
                if referrer:
                    referrer_id = referrer[0]
                    ref_bonus = float(amount) * REFERRAL_PERCENT
                    await db.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (ref_bonus, referrer_id))
                    await db.execute('INSERT INTO referral_earnings (referrer_id, referral_id, amount) VALUES (?, ?, ?)',
                                     (referrer_id, user_id, ref_bonus))
                await db.commit()

            await callback.message.edit_text(f"✅ Оплата получена! Баланс пополнен на {amount:.2f} ₽")
            await state.clear()
        else:
            await callback.answer("⌛ Оплата ещё не поступила, попробуйте позже.")
    except Exception as e:
        logger.exception(f"YooMoney check error: {e}")
        await callback.answer("❌ Ошибка при проверке платежа")

# -------------------- Покупка VPN --------------------
@dp.callback_query(F.data == "buy_vpn")
async def buy_vpn(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    balance = await get_user_balance(user_id)

    if balance < VPN_SUBSCRIPTION_PRICE:
        await callback.message.edit_text(
            f"❌ Недостаточно средств. Нужно {VPN_SUBSCRIPTION_PRICE} ₽, у вас {balance:.2f} ₽.",
            reply_markup=main_menu_keyboard()
        )
        return

    await callback.message.edit_text(
        f"🔐 Подписка HappVPN за {VPN_SUBSCRIPTION_PRICE} ₽.\nБаланс: {balance:.2f} ₽.\nПодтвердить?",
        reply_markup=confirm_cancel_keyboard()
    )
    await state.set_state(PaymentState.waiting_for_vpn_confirmation)

@dp.callback_query(F.data == "confirm_vpn", PaymentState.waiting_for_vpn_confirmation)
async def happvpn_purchase(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        row = await cursor.fetchone()
        balance = row[0] if row else 0.0

        if balance < VPN_SUBSCRIPTION_PRICE:
            await callback.answer("❌ Недостаточно средств для покупки")
            await state.clear()
            return

        # списываем баланс
        await db.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (VPN_SUBSCRIPTION_PRICE, user_id))

        # создаём подписку
        token = secrets.token_urlsafe(16)
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        traffic_limit = 30.0

        await db.execute('INSERT OR REPLACE INTO subscriptions(user_id, token, expires_at, traffic_limit_gb) VALUES (?, ?, ?, ?)',
                         (user_id, token, expires_at.isoformat(), traffic_limit))

        # для корректного отображения в профиле (как в исходном коде)
        await db.execute('UPDATE users SET vpn_active_until=? WHERE user_id=?', (expires_at.isoformat(), user_id))

        await db.execute('INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)',
                         (user_id, -VPN_SUBSCRIPTION_PRICE, 'vpn', 'Покупка HappVPN'))
        await db.commit()

    # генерируем UUID и создаём/обновляем vpn_link
    user_uuid = str(uuid.uuid4())
    await add_vpn_link(user_id, user_uuid)

    deeplink = f"http://{DOMAIN}/subs/{token}"
    kb = InlineKeyboardBuilder()
    kb.button(text="Добавить в HappVPN", url=deeplink)
    kb.adjust(1)

    await callback.message.edit_text(
        f"✅ HappVPN активирован до {expires_at.strftime('%d.%m.%Y')}!",
        reply_markup=kb.as_markup()
    )
    await state.clear()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("👋 Добро пожаловать!\nВыберите действие:", reply_markup=main_menu_keyboard())

@dp.callback_query(F.data == "referral_system")
async def referral_system(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
        ref_count = (await cursor.fetchone())[0]
        cursor = await db.execute('SELECT COALESCE(SUM(amount), 0) FROM referral_earnings WHERE referrer_id = ?', (user_id,))
        ref_earnings = (await cursor.fetchone())[0]

    ref_link = f"https://t.me/Pro100VPN_RoBot?start={user_id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]])

    await callback.message.edit_text(
        f"👥 Реферальная система\n\n"
        f"💎 Ваша реферальная ссылка:\n{ref_link}\n\n"
        f"📊 Статистика:\n• Рефералов: {ref_count}\n• Заработано: {ref_earnings:.2f} ₽\n\n"
        f"💵 Вы получаете {REFERRAL_PERCENT*100:.0f}% от пополнений",
        reply_markup=kb
    )

@dp.callback_query(F.data == "profile")
async def profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT balance, vpn_active_until FROM users WHERE user_id = ?', (user_id,))
        user_data = await cursor.fetchone()
        balance = user_data[0] if user_data else 0
        vpn_until = user_data[1] if user_data else None

    vpn_status = "❌ Не активна"
    if vpn_until:
        try:
            until_date = datetime.fromisoformat(vpn_until)
            if until_date > datetime.now(timezone.utc):
                vpn_status = f"✅ Активна до {until_date.strftime('%d.%m.%Y')}"
        except Exception:
            pass

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]])
    await callback.message.edit_text(
        f"💼 Ваш профиль\n\n💰 Баланс: {balance:.2f} ₽\n🔐 VPN подписка: {vpn_status}\n\nID: {user_id}",
        reply_markup=kb
    )

# ============ Фоновая задача: проверка подписок ============
async def check_expired_subscriptions():
    while True:
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT user_id, expires_at FROM subscriptions")
            rows = await cursor.fetchall()
            for user_id, expires_at in rows:
                try:
                    if datetime.fromisoformat(expires_at) < now:
                        # удаляем подписку и очищаем vpn_links
                        await db.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
                        await db.execute("DELETE FROM vpn_links WHERE user_id = ?", (user_id,))
                        await db.execute("UPDATE users SET vpn_active_until=NULL WHERE user_id=?", (user_id,))
                        await db.commit()
                        try:
                            await bot.send_message(user_id, "⚠️ Ваша подписка VPN закончилась. Купите новую для продления.")
                        except Exception as e:
                            logger.warning(f"Не удалось уведомить {user_id}: {e}")
                except Exception:
                    pass
        await asyncio.sleep(86400)  # раз в сутки

# ======================= Запуск бота =======================
async def main():
    await init_db()
    asyncio.create_task(check_expired_subscriptions())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
