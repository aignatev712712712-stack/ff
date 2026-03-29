import asyncio
import uuid
import logging
from datetime import datetime
from decimal import Decimal

import aiohttp
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_ENABLED, FRAGMENT_AUTO_DELIVERY
from database import (
    cursor, conn, get_user_balance, update_user_balance, add_purchase,
    get_purchase, update_purchase_status, try_lock_purchase, format_price,
    get_price_per_star, calc_stars_cost, set_price_per_star
)
from keyboards import (
    main_menu_keyboard, back_button, topup_amount_keyboard,
    payment_keyboard, admin_panel_keyboard, help_keyboard, calculator_keyboard
)
from states import (
    BuyStarsState, PromoState, AdminPriceState,
    AdminPromoState, TopupState, CalcState
)
from fragment_bot import deliver_stars_to_user

router = Router()
logger = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=30)

BOT_USERNAME = None


def _safe_user_tag(user) -> str:
    username = getattr(user, "username", None)
    return f"@{username}" if username else "нет юзернейма"


async def show_main_menu(message_or_callback, user_id: int, edit: bool = False):
    balance = get_user_balance(user_id)
    text = (
        f"Добро пожаловать, Flakon актуальчик ботик по закупочке звездочек ниже рыночка!\n\n"
        f"💰 Текущий баланс: {format_price(balance)} руб.\n\n"
        f"Выберите действие"
    )
    keyboard = main_menu_keyboard(user_id, user_id in ADMIN_IDS)

    if isinstance(message_or_callback, CallbackQuery):
        if edit:
            await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message_or_callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        if edit:
            await message_or_callback.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""

    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split('_')[1])
        except Exception:
            referrer_id = None

    cursor.execute(
        '''
        INSERT INTO users (user_id, username, full_name, referrer_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name
        ''',
        (user_id, username, full_name, referrer_id)
    )
    conn.commit()

    await show_main_menu(message, user_id)


@router.callback_query(F.data == "buy_stars")
async def buy_stars_start(callback: CallbackQuery, state: FSMContext):
    price = get_price_per_star()
    balance = get_user_balance(callback.from_user.id)
    max_stars = int(balance / (price * 100)) if price > 0 else 0

    text = (
        f"★ Покупка звёзд\n"
        f"- Цена за 1 звезду: {price:.2f}₽/шт.;\n"
        f"- Минимум: 50 звёзд;\n"
        f"- Максимум (за один заказ): 10 000 звёзд.\n"
        f"- Баланса хватает на покупку: ~{max_stars} звёзд ({format_price(balance)}₽).\n\n"
        f"Введите количество звёзд для покупки:"
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await state.update_data(bot_msg_id=callback.message.message_id)
    await state.set_state(BuyStarsState.waiting_for_stars)
    await callback.answer()


@router.message(StateFilter(BuyStarsState.waiting_for_stars), F.text.regexp(r'^\d+$'))
async def buy_stars_enter(message: Message, state: FSMContext):
    stars = int(message.text)
    if stars < 50:
        await message.answer("❌ Минимальное количество – 50 звёзд. Попробуйте ещё раз.")
        return
    if stars > 10000:
        await message.answer("❌ Максимальное количество – 10 000 звёзд. Попробуйте ещё раз.")
        return

    cost_kopecks = calc_stars_cost(stars)
    cost_rub = format_price(cost_kopecks)

    await state.update_data(stars=stars, cost_kopecks=cost_kopecks)

    balance = get_user_balance(message.from_user.id)
    if balance >= cost_kopecks:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Купить с баланса", callback_data="buy_with_balance")],
            [InlineKeyboardButton(text="💳 Оплатить картой", callback_data="pay_with_card")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
        text = (
            f"⭐️ {stars} звёзд\n"
            f"💰 Стоимость: {cost_rub} руб.\n"
            f"💵 Ваш баланс: {format_price(balance)} руб.\n\n"
            f"Выберите способ оплаты:"
        )
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить картой", callback_data="pay_with_card")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
        text = (
            f"⭐️ {stars} звёзд\n"
            f"💰 Стоимость: {cost_rub} руб.\n"
            f"⚠️ Недостаточно средств на балансе.\n\n"
            f"Выберите способ оплаты:"
        )

    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    if bot_msg_id:
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=message.chat.id,
                message_id=bot_msg_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception:
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

    await state.set_state(BuyStarsState.waiting_for_confirmation)


@router.callback_query(StateFilter(BuyStarsState.waiting_for_confirmation), F.data == "buy_with_balance")
async def buy_with_balance(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stars = data.get('stars')
    cost_kopecks = data.get('cost_kopecks')
    if stars is None or cost_kopecks is None:
        await callback.message.answer("❌ Данные заказа потеряны. Начните заново.")
        await state.clear()
        return

    user_id = callback.from_user.id
    balance = get_user_balance(user_id)
    if balance < cost_kopecks:
        await callback.message.answer("Недостаточно средств на балансе")
        return

    update_user_balance(user_id, -cost_kopecks)
    purchase_id = add_purchase(user_id, stars, cost_kopecks, 'balance', 'paid')
    await check_referral_bonus(callback.bot, user_id, cost_kopecks)

    fragment_done = False
    fragment_error = None

    if FRAGMENT_AUTO_DELIVERY:
        cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
        urow = cursor.fetchone()
        username = urow[0] if urow else None

        if username:
            try:
                fragment_result = await deliver_stars_to_user(username=username, stars=stars)
                fragment_done = bool(fragment_result.get("ok"))
                if not fragment_done:
                    fragment_error = fragment_result.get("error", "unknown error")
            except Exception as e:
                fragment_error = str(e)
        else:
            fragment_error = "У пользователя нет @username"

    if fragment_done:
        update_purchase_status(purchase_id, 'completed', datetime.now())
        await callback.message.edit_text(
            f"✅ Покупка завершена!\n\n"
            f"🛒 Заказ #{purchase_id}\n"
            f"⭐️ {stars} звёзд\n"
            f"💰 Стоимость: {format_price(cost_kopecks)} руб.\n\n"
            f"🎉 Звёзды отправлены автоматически.",
            parse_mode="HTML"
        )
    else:
        if not fragment_error:
            fragment_error = "Автовыдача отключена"

        await callback.message.edit_text(
            f"✅ Покупка завершена!\n\n"
            f"🛒 Заказ #{purchase_id}\n"
            f"⭐️ {stars} звёзд\n"
            f"💰 Стоимость: {format_price(cost_kopecks)} руб.\n\n"
            f"⚠️ Автовыдача не выполнена, заказ передан админу.",
            parse_mode="HTML"
        )

        admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Звёзды выданы", callback_data=f"complete_order_{purchase_id}")
        ]])

        admin_message = (
            f"💸 Покупка с баланса\n\n"
            f"🛒 Заказ #{purchase_id}\n"
            f"👤 Покупатель: {_safe_user_tag(callback.from_user)}\n"
            f"🆔 ID: {user_id}\n"
            f"⭐️ Количество: {stars} звёзд\n"
            f"💰 Сумма: {format_price(cost_kopecks)} руб.\n"
            f"📅 Время: {datetime.now().strftime('%H:%M %d.%m.%Y')}\n\n"
            f"⚠️ Автовыдача не сработала.\n"
            f"Причина: {fragment_error or 'unknown'}\n\n"
            f"Выдайте пользователю {stars} звёзд, затем нажмите кнопку."
        )

        for admin_id in ADMIN_IDS:
            await callback.bot.send_message(
                admin_id,
                admin_message,
                reply_markup=admin_keyboard,
                parse_mode="HTML"
            )

    await state.clear()
    await asyncio.sleep(1)
    await show_main_menu(callback, user_id, edit=True)
    await callback.answer()


@router.callback_query(StateFilter(BuyStarsState.waiting_for_confirmation), F.data == "pay_with_card")
async def pay_with_card(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stars = data.get('stars')
    cost_kopecks = data.get('cost_kopecks')
    if stars is None or cost_kopecks is None:
        await callback.answer("❌ Данные заказа потеряны. Начните заново.", show_alert=True)
        await state.clear()
        return

    user_id = callback.from_user.id

    if not YOOKASSA_ENABLED:
        await callback.message.answer("❌ Оплата картой недоступна. Настройте ЮKassa в .env.")
        await state.clear()
        return

    purchase_id = add_purchase(user_id, stars, cost_kopecks, 'yookassa', 'creating_payment')
    cursor.execute('SELECT order_id FROM purchases WHERE id = ?', (purchase_id,))
    row = cursor.fetchone()
    order_id = row[0] if row else None

    payment_data = {
        "amount": {"value": f"{cost_kopecks / 100:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{callback.from_user.username}" if callback.from_user.username else "https://t.me"
        },
        "description": f"Покупка {stars} Telegram Stars",
        "metadata": {
            "purchase_id": purchase_id,
            "user_id": user_id,
            "order_id": order_id,
            "type": "stars"
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Idempotence-Key": str(uuid.uuid4())
    }
    auth = aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)

    await callback.message.edit_text("<b>⏳ Создаем платеж...</b>", parse_mode="HTML")

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        try:
            async with session.post(
                "https://api.yookassa.ru/v3/payments",
                json=payment_data,
                headers=headers,
                auth=auth
            ) as resp:
                response_text = await resp.text()

                if resp.status in (200, 201):
                    payment_info = await resp.json()
                    payment_id = payment_info['id']
                    confirmation_url = payment_info['confirmation']['confirmation_url']

                    cursor.execute(
                        'UPDATE purchases SET payment_id = ?, status = ? WHERE id = ?',
                        (payment_id, 'waiting_payment', purchase_id)
                    )
                    conn.commit()

                    keyboard = payment_keyboard(confirmation_url, purchase_id)
                    await callback.message.edit_text(
                        f"💳 ОПЛАТА ЧЕРЕЗ ЮKASSA\n\n"
                        f"🛒 Заказ #{purchase_id}\n"
                        f"⭐️ {stars} звёзд\n"
                        f"💰 {format_price(cost_kopecks)} руб.\n\n"
                        f"👇 Нажмите кнопку для оплаты:",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    logger.error(f"Ошибка YooKassa: status={resp.status}, body={response_text}")
                    await callback.message.edit_text("❌ Ошибка при создании платежа. Попробуйте позже.")
        except Exception:
            logger.exception("Ошибка соединения с YooKassa")
            await callback.message.edit_text("❌ Ошибка соединения. Попробуйте позже.")

    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: CallbackQuery):
    await callback.answer()

    if not YOOKASSA_ENABLED:
        await callback.message.answer("❌ Проверка оплаты недоступна. Настройте ЮKassa в .env.")
        return

    try:
        purchase_id = int(callback.data.split('_')[2])
    except (IndexError, ValueError):
        await callback.message.answer("❌ Некорректный номер заказа")
        return

    purchase = get_purchase(purchase_id)
    if not purchase:
        await callback.message.answer("Покупка не найдена")
        return

    user_id, stars, amount_kopecks, status, payment_id, payment_method = purchase

    if status == 'completed':
        await callback.message.answer("✅ Звёзды уже выданы")
        return
    if status not in ('waiting_payment', 'paid'):
        await callback.message.answer("Статус платежа неизвестен")
        return
    if not payment_id:
        await callback.message.answer("❌ У заказа нет payment_id")
        return

    auth = aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", auth=auth) as resp:
                response_text = await resp.text()

                if resp.status != 200:
                    logger.error(f"Ошибка проверки YooKassa: status={resp.status}, body={response_text}")
                    await callback.message.answer("Ошибка при проверке платежа.")
                    return

                payment_info = await resp.json()
                payment_status = payment_info.get('status')

                if payment_status != 'succeeded':
                    if payment_status == 'pending':
                        await callback.message.answer("⏳ Платеж в обработке. Подождите и проверьте снова.")
                    else:
                        await callback.message.answer(f"Статус платежа: {payment_status}")
                    return

                cursor.execute('SELECT status FROM purchases WHERE id = ?', (purchase_id,))
                row = cursor.fetchone()
                if not row:
                    await callback.message.answer("Заказ не найден")
                    return

                current_status = row[0]
                if current_status == 'completed':
                    await callback.message.answer("✅ Звёзды уже выданы")
                    return
                if current_status != 'waiting_payment':
                    await callback.message.answer("Статус заказа некорректен")
                    return

                update_purchase_status(purchase_id, 'paid', datetime.now())

                fragment_done = False
                fragment_error = None

                if FRAGMENT_AUTO_DELIVERY:
                    cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
                    urow = cursor.fetchone()
                    username = urow[0] if urow else None

                    if username:
                        try:
                            fragment_result = await deliver_stars_to_user(username=username, stars=stars)
                            fragment_done = bool(fragment_result.get("ok"))
                            if not fragment_done:
                                fragment_error = fragment_result.get("error", "unknown error")
                        except Exception as e:
                            fragment_error = str(e)
                    else:
                        fragment_error = "У пользователя нет @username"

                if fragment_done:
                    update_purchase_status(purchase_id, 'completed', datetime.now())
                    await callback.message.edit_text(
                        f"✅ Оплата подтверждена!\n\n"
                        f"🛒 Заказ #{purchase_id}\n"
                        f"⭐️ {stars} звёзд\n"
                        f"💰 {format_price(amount_kopecks)} руб.\n\n"
                        f"🎉 Звёзды отправлены автоматически.",
                        parse_mode="HTML"
                    )
                else:
                    await callback.message.edit_text(
                        f"✅ Оплата подтверждена!\n\n"
                        f"🛒 Заказ #{purchase_id}\n"
                        f"⭐️ {stars} звёзд\n"
                        f"💰 {format_price(amount_kopecks)} руб.\n\n"
                        f"⚠️ Автовыдача не выполнена, заказ передан админу.",
                        parse_mode="HTML"
                    )

                    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="✅ Звёзды выданы", callback_data=f"complete_order_{purchase_id}")
                    ]])

                    admin_message = (
                        f"💳 НОВАЯ ОПЛАТА ЧЕРЕЗ ЮKASSA\n\n"
                        f"🛒 Заказ #{purchase_id}\n"
                        f"👤 Покупатель: {_safe_user_tag(callback.from_user)}\n"
                        f"🆔 ID: {user_id}\n"
                        f"⭐️ Количество: {stars} звёзд\n"
                        f"💰 Сумма: {format_price(amount_kopecks)} руб.\n"
                        f"📅 Время: {datetime.now().strftime('%H:%M %d.%m.%Y')}\n\n"
                        f"⚠️ Автовыдача не сработала.\n"
                        f"Причина: {fragment_error or 'unknown'}\n\n"
                        f"Выдайте пользователю {stars} звёзд, затем нажмите кнопку."
                    )

                    for admin_id in ADMIN_IDS:
                        await callback.bot.send_message(
                            admin_id,
                            admin_message,
                            reply_markup=admin_keyboard,
                            parse_mode="HTML"
                        )

    except Exception:
        logger.exception("Ошибка проверки платежа")
        await callback.message.answer("Ошибка при проверке платежа.")


@router.callback_query(F.data.startswith("complete_order_"), F.from_user.id.in_(ADMIN_IDS))
async def complete_order(callback: CallbackQuery):
    try:
        purchase_id = int(callback.data.split('_')[2])
    except (IndexError, ValueError):
        await callback.answer("Некорректный заказ", show_alert=True)
        return

    cursor.execute('''
        SELECT p.user_id, p.stars_count, p.amount_rub, u.username, u.full_name, p.status
        FROM purchases p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.id = ?
    ''', (purchase_id,))
    order = cursor.fetchone()
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    user_id, stars, amount_kopecks, username, full_name, status = order
    if not try_lock_purchase(purchase_id, 'paid', 'completed', datetime.now()):
        await callback.answer("Заказ уже обработан", show_alert=True)
        return

    try:
        await callback.bot.send_message(
            user_id,
            f"🎉 ЗАКАЗ ВЫПОЛНЕН!\n\n"
            f"✅ Администратор выдал вам {stars} звёзд.\n"
            f"🛒 Заказ #{purchase_id}\n"
            f"⭐️ Количество: {stars} звёзд\n"
            f"💰 Сумма: {format_price(amount_kopecks)} руб.\n\n"
            f"Спасибо за покупку! 🚀",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

    await callback.message.edit_text(
        text=f"✅ ВЫДАЧА ПОДТВЕРЖДЕНА\n\n"
             f"📋 Заказ #{purchase_id}\n"
             f"👤 {full_name} (@{username or 'нет'})\n"
             f"⭐️ {stars} звёзд выданы\n"
             f"💰 {format_price(amount_kopecks)} руб.\n"
             f"👑 Выдал: @{callback.from_user.username or 'админ'}\n"
             f"⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}",
        reply_markup=None,
        parse_mode="HTML"
    )
    await callback.answer("✅ Заказ отмечен выполненным")


async def check_referral_bonus(bot: Bot, user_id: int, amount_kopecks: int):
    cursor.execute('SELECT referrer_id FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0]:
        referrer_id = row[0]
        cursor.execute('UPDATE users SET invited_paid_count = invited_paid_count + 1 WHERE user_id = ?', (referrer_id,))
        conn.commit()

        cursor.execute('SELECT invited_paid_count, bonus_stars_earned FROM users WHERE user_id = ?', (referrer_id,))
        ref_row = cursor.fetchone()
        if not ref_row:
            return

        count, earned = ref_row
        if count >= 10 and earned == 0:
            stars_bonus = 100
            order_id = f"REF_{referrer_id}_{int(datetime.now().timestamp())}"
            cursor.execute(
                '''INSERT INTO purchases (user_id, order_id, stars_count, amount_rub, payment_method, status, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (referrer_id, order_id, stars_bonus, 0, 'referral_bonus', 'completed', datetime.now().isoformat())
            )
            cursor.execute('UPDATE users SET bonus_stars_earned = bonus_stars_earned + ? WHERE user_id = ?', (stars_bonus, referrer_id))
            conn.commit()

            await bot.send_message(
                referrer_id,
                f"🎉 Реферальный бонус!\n\nПоздравляем! 10 ваших друзей совершили оплату. Вы получили {stars_bonus} звёзд.\nСпасибо за приглашения!",
                parse_mode="HTML"
            )
            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    admin_id,
                    f"🎁 Реферальный бонус\nРеферер: {referrer_id}\nНачислено: {stars_bonus} звёзд за 10 оплативших приглашённых.",
                    parse_mode="HTML"
                )


@router.callback_query(F.data == "referral")
async def referral_info(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute('SELECT invited_count, bonus_stars_earned FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    invited_count, bonus = row if row else (0, 0)

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await callback.bot.get_me()
        BOT_USERNAME = me.username

    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    text = (
        f"🤝 Реферальная система\n\n"
        f"Приглашайте друзей и получайте бонусы!\n"
        f"Ваша реферальная ссылка:\n{link}\n\n"
        f"📊 Приглашено друзей: {invited_count}\n"
        f"⭐️ Получено бонусных звёзд: {bonus}\n\n"
        f"Условия:\n"
        f"• За каждого приглашённого друга, который совершит любую оплату, счётчик увеличивается.\n"
        f"• Как только 10 приглашённых друзей совершат оплату, вы получите 100 звёзд (бонус начисляется один раз).\n"
        f"• Бонус зачисляется автоматически."
    )
    await callback.message.edit_text(text, reply_markup=back_button(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute('SELECT username, full_name, balance, reg_date FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    username, full_name, balance_kopecks, reg_date = user
    cursor.execute('SELECT COUNT(*), SUM(stars_count), SUM(amount_rub) FROM purchases WHERE user_id = ? AND status = "completed"', (user_id,))
    stats = cursor.fetchone()
    total_orders = stats[0] or 0
    total_stars = stats[1] or 0
    total_spent = stats[2] or 0

    text = (
        f"👤 Профиль\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {full_name}\n"
        f"🔗 @{username or 'нет'}\n"
        f"💰 Баланс: {format_price(balance_kopecks)} руб.\n"
        f"📅 Регистрация: {reg_date[:16] if reg_date else '—'}\n\n"
        f"📊 Статистика покупок:\n"
        f"🛒 Всего заказов: {total_orders}\n"
        f"⭐️ Всего звёзд: {total_stars}\n"
        f"💸 Потрачено: {format_price(total_spent)} руб."
    )
    await callback.message.edit_text(text, reply_markup=back_button(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "help")
async def help_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "❓ Помощь\n\nВыберите раздел:",
        reply_markup=help_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    if ADMIN_IDS:
        admin_chat = await callback.bot.get_chat(ADMIN_IDS[0])
        admin_link = f"https://t.me/{admin_chat.username}" if admin_chat.username else f"tg://user?id={ADMIN_IDS[0]}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📩 Написать администратору", url=admin_link)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="help")]
        ])
        await callback.message.edit_text(
            "📞 Связь с администратором\n\n"
            "Если у вас возникли вопросы или проблемы, напишите нам:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text("❌ Администратор не назначен.")
    await callback.answer()


@router.callback_query(F.data == "faq")
async def faq(callback: CallbackQuery):
    faq_text = (
        "❓ Часто задаваемые вопросы\n\n"
        "— Как происходит выдача товара?\n"
        "После подтверждения оплаты заказ выполняется автоматически, либо администратором, если авто-выдача не сработала.\n\n"
        "— Как быстро приходят звезды?\n"
        "Обычно это занимает 5-15 минут.\n\n"
        "— Могу ли я покупать звезды только для себя?\n"
        "Нет, вы можете отправлять подарки любым пользователям, у которых есть @username.\n"
    )
    await callback.message.edit_text(faq_text, reply_markup=back_button("help"), parse_mode="HTML")
    await callback.answer()


@router.message(StateFilter(CalcState.waiting_for_value), F.text)
async def calc_result(message: Message, state: FSMContext):
    data = await state.get_data()
    direction = data.get('direction')
    if not direction:
        await message.answer("❌ Ошибка расчёта. Начните заново.")
        await state.clear()
        return

    try:
        value = float(message.text.replace(',', '.'))
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.")
        return

    price = get_price_per_star()
    price_float = float(price)

    if direction == "stars_to_rub":
        total = value * price_float
        result = f"{value} звёзд = {total:.2f} руб."
    else:
        stars = value / price_float
        result = f"{value:.2f} руб. = {stars:.2f} звёзд"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="calculator")]
    ])
    await message.answer(result, reply_markup=keyboard, parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data == "calc_stars_to_rub")
async def calc_stars_to_rub_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите количество звёзд:")
    await state.update_data(direction="stars_to_rub")
    await state.set_state(CalcState.waiting_for_value)
    await callback.answer()


@router.callback_query(F.data == "calc_rub_to_stars")
async def calc_rub_to_stars_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите сумму в рублях:")
    await state.update_data(direction="rub_to_stars")
    await state.set_state(CalcState.waiting_for_value)
    await callback.answer()


@router.callback_query(F.data == "admin_panel", F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(callback: CallbackQuery):
    await callback.message.edit_text("👑 Админ-панель", reply_markup=admin_panel_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_stats", F.from_user.id.in_(ADMIN_IDS))
async def admin_stats(callback: CallbackQuery):
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM purchases WHERE status = 'completed'")
    completed = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM purchases WHERE status = 'paid'")
    awaiting_issue = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(amount_rub) FROM purchases WHERE status = 'completed'")
    revenue = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(stars_count) FROM purchases WHERE status = 'completed'")
    stars_sold = cursor.fetchone()[0] or 0

    text = (
        f"📊 Статистика\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"✅ Выполнено заказов: {completed}\n"
        f"🔄 Ожидают выдачи: {awaiting_issue}\n"
        f"💰 Выручка: {format_price(revenue)} руб.\n"
        f"⭐️ Продано звёзд: {stars_sold}"
    )
    await callback.message.edit_text(text, reply_markup=back_button("admin_panel"), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_pending", F.from_user.id.in_(ADMIN_IDS))
async def admin_pending(callback: CallbackQuery):
    cursor.execute('''
        SELECT p.id, p.user_id, u.username, u.full_name, p.stars_count, p.amount_rub, p.created_at, p.status, p.payment_method
        FROM purchases p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.status IN ('paid')
        ORDER BY p.created_at DESC
    ''')
    orders = cursor.fetchall()

    if not orders:
        await callback.message.edit_text("✅ Нет заказов, ожидающих выдачи.")
        await callback.answer()
        return

    text = "🔄 Заказы, ожидающие выдачи:\n\n"
    for order in orders:
        order_id, user_id, username, full_name, stars, amount_kopecks, created_at, status, payment_method = order
        created_str = created_at[:16] if created_at else "—"
        text += (
            f"🆔 Заказ #{order_id}\n"
            f"👤 {full_name} (@{username or 'нет'})\n"
            f"⭐️ {stars} звёзд\n"
            f"💰 {format_price(amount_kopecks)} руб.\n"
            f"📅 {created_str}\n"
            f"📌 Статус: {status}\n"
            f"💳 Способ: {payment_method}\n\n"
        )

    await callback.message.edit_text(text, reply_markup=back_button("admin_panel"), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_set_price", F.from_user.id.in_(ADMIN_IDS))
async def admin_set_price(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите новую цену за 1 звезду (в рублях, например 1.15):")
    await state.set_state(AdminPriceState.waiting_for_price)
    await callback.answer()


@router.message(StateFilter(AdminPriceState.waiting_for_price), F.text)
async def set_price_value(message: Message, state: FSMContext):
    try:
        price = Decimal(message.text.replace(',', '.'))
        if price <= 0:
            raise ValueError
        set_price_per_star(price)
        await message.answer(f"✅ Цена звезды установлена: {price:.2f} руб.")
        await state.clear()
    except Exception:
        await message.answer("❌ Неверный формат. Введите положительное число (например, 1.15).")


@router.callback_query(F.data == "admin_create_promo", F.from_user.id.in_(ADMIN_IDS))
async def admin_create_promo(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.answer("Введите код промокода (латиница, без пробелов):")
    await state.update_data(message_id=msg.message_id)
    await state.set_state(AdminPromoState.waiting_for_code)
    await callback.answer()


@router.message(StateFilter(AdminPromoState.waiting_for_code), F.text)
async def promo_code_entered(message: Message, state: FSMContext):
    code = message.text.strip()
    cursor.execute('SELECT 1 FROM promocodes WHERE code = ?', (code,))
    if cursor.fetchone():
        data = await state.get_data()
        bot_msg_id = data.get('message_id')
        await message.bot.edit_message_text(
            "❌ Промокод с таким кодом уже существует. Введите другой код.",
            chat_id=message.chat.id,
            message_id=bot_msg_id
        )
        return

    await state.update_data(code=code)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Фиксированное количество звёзд", callback_data="promo_type_fixed")],
        [InlineKeyboardButton(text="📊 Процент скидки", callback_data="promo_type_percent")]
    ])
    data = await state.get_data()
    bot_msg_id = data.get('message_id')
    await message.bot.edit_message_text(
        "Выберите тип промокода:",
        chat_id=message.chat.id,
        message_id=bot_msg_id,
        reply_markup=keyboard
    )
    await state.set_state(AdminPromoState.waiting_for_type)


@router.callback_query(StateFilter(AdminPromoState.waiting_for_type), F.data.startswith("promo_type_"))
async def promo_type_selected(callback: CallbackQuery, state: FSMContext):
    raw_type = callback.data.split('_')[2]
    discount_type = 'fixed_stars' if raw_type == 'fixed' else 'percent'
    await state.update_data(discount_type=discount_type)
    data = await state.get_data()
    bot_msg_id = data.get('message_id')

    if discount_type == 'fixed_stars':
        await callback.bot.edit_message_text(
            "Введите количество звёзд для начисления:",
            chat_id=callback.message.chat.id,
            message_id=bot_msg_id
        )
    else:
        await callback.bot.edit_message_text(
            "Введите процент скидки (целое число от 1 до 100):",
            chat_id=callback.message.chat.id,
            message_id=bot_msg_id
        )
    await state.set_state(AdminPromoState.waiting_for_value)
    await callback.answer()


@router.message(StateFilter(AdminPromoState.waiting_for_value), F.text)
async def promo_value_entered(message: Message, state: FSMContext):
    try:
        value = int(message.text)
        data = await state.get_data()
        if data['discount_type'] == 'fixed_stars':
            if value <= 0:
                raise ValueError
        else:
            if value < 1 or value > 100:
                raise ValueError
    except ValueError:
        data = await state.get_data()
        bot_msg_id = data.get('message_id')
        await message.bot.edit_message_text(
            "❌ Неверное значение. Введите целое положительное число.",
            chat_id=message.chat.id,
            message_id=bot_msg_id
        )
        return

    await state.update_data(discount_value=value)
    data = await state.get_data()
    bot_msg_id = data.get('message_id')
    await message.bot.edit_message_text(
        "Введите максимальное количество активаций (целое число):",
        chat_id=message.chat.id,
        message_id=bot_msg_id
    )
    await state.set_state(AdminPromoState.waiting_for_max_uses)


@router.message(StateFilter(AdminPromoState.waiting_for_max_uses), F.text)
async def promo_max_uses_entered(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text)
        if max_uses <= 0:
            raise ValueError
    except ValueError:
        data = await state.get_data()
        bot_msg_id = data.get('message_id')
        await message.bot.edit_message_text(
            "❌ Введите целое положительное число.",
            chat_id=message.chat.id,
            message_id=bot_msg_id
        )
        return

    data = await state.get_data()
    code = data['code']
    discount_type = data['discount_type']
    discount_value = data['discount_value']

    cursor.execute(
        'INSERT INTO promocodes (code, discount_type, discount_value, max_uses, created_by) VALUES (?, ?, ?, ?, ?)',
        (code, discount_type, discount_value, max_uses, message.from_user.id)
    )
    conn.commit()

    bot_msg_id = data.get('message_id')
    await message.bot.edit_message_text(
        f"✅ Промокод {code} создан.\n"
        f"Тип: {'фиксированные звёзды' if discount_type == 'fixed_stars' else 'скидка %'}\n"
        f"Значение: {discount_value}\n"
        f"Макс. активаций: {max_uses}",
        chat_id=message.chat.id,
        message_id=bot_msg_id
    )
    await state.clear()


@router.callback_query(F.data == "admin_list_promos", F.from_user.id.in_(ADMIN_IDS))
async def admin_list_promos(callback: CallbackQuery):
    cursor.execute('SELECT id, code, discount_type, discount_value, max_uses, used_count FROM promocodes ORDER BY id DESC')
    promos = cursor.fetchall()
    if not promos:
        await callback.message.edit_text("Нет созданных промокодов.")
        return

    text = "🎁 Список промокодов\n\n"
    for promo in promos:
        promo_id, code, d_type, d_value, max_uses, used = promo
        type_str = "фикс. звёзды" if d_type == 'fixed_stars' else f"{d_value}%"
        text += f"• {code} – {type_str} – {used}/{max_uses}\n"

    await callback.message.edit_text(text, reply_markup=back_button("admin_panel"), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "topup")
async def topup_start(callback: CallbackQuery):
    await callback.message.edit_text(
        "💰 Пополнение баланса\nВыберите сумму (в рублях):",
        reply_markup=topup_amount_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("topup_"))
async def topup_amount(callback: CallbackQuery, state: FSMContext):
    amount_str = callback.data.split('_')[1]
    if amount_str == 'custom':
        await callback.message.edit_text("Введите сумму пополнения (от 1 до 10000 рублей):")
        await state.update_data(bot_msg_id=callback.message.message_id)
        await state.set_state(TopupState.waiting_for_amount)
        await callback.answer()
        return

    amount = int(amount_str)
    await create_topup_payment(
        callback.bot, callback.from_user.id, callback.from_user.username,
        callback.message.chat.id, callback.message.message_id, amount
    )
    await callback.answer()


@router.message(StateFilter(TopupState.waiting_for_amount), F.text)
async def topup_custom_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount < 1 or amount > 10000:
            raise ValueError
        amount_rub = int(amount)
    except Exception:
        await message.answer("❌ Неверная сумма. Введите число от 1 до 10000.")
        return

    data = await state.get_data()
    bot_msg_id = data.get('bot_msg_id')
    await state.clear()

    if not bot_msg_id:
        sent = await message.answer("⏳")
        bot_msg_id = sent.message_id

    await create_topup_payment(
        message.bot, message.from_user.id, message.from_user.username,
        message.chat.id, bot_msg_id, amount_rub
    )


async def create_topup_payment(bot: Bot, user_id: int, username: str, chat_id: int, message_id: int, amount_rub: int):
    if not YOOKASSA_ENABLED:
        await bot.edit_message_text(
            "❌ Пополнение недоступно. Настройте ЮKassa в .env.",
            chat_id=chat_id,
            message_id=message_id
        )
        return

    amount_kopecks = amount_rub * 100
    purchase_id = add_purchase(user_id, 0, amount_kopecks, 'topup', 'creating_payment')
    cursor.execute('SELECT order_id FROM purchases WHERE id = ?', (purchase_id,))
    row = cursor.fetchone()
    order_id = row[0] if row else None

    payment_data = {
        "amount": {"value": f"{amount_rub}.00", "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{username}" if username else "https://t.me"
        },
        "description": f"Пополнение баланса на {amount_rub} руб.",
        "metadata": {
            "purchase_id": purchase_id,
            "user_id": user_id,
            "order_id": order_id,
            "type": "topup"
        }
    }

    headers = {"Content-Type": "application/json", "Idempotence-Key": str(uuid.uuid4())}
    auth = aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)

    try:
        await bot.edit_message_text("<b>⏳ Создаем платеж...</b>", chat_id=chat_id, message_id=message_id, parse_mode="HTML")
    except Exception:
        pass

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        try:
            async with session.post(
                "https://api.yookassa.ru/v3/payments",
                json=payment_data,
                headers=headers,
                auth=auth
            ) as resp:
                response_text = await resp.text()

                if resp.status in (200, 201):
                    payment_info = await resp.json()
                    payment_id = payment_info['id']
                    confirmation_url = payment_info['confirmation']['confirmation_url']
                    cursor.execute('UPDATE purchases SET payment_id = ?, status = ? WHERE id = ?', (payment_id, 'waiting_payment', purchase_id))
                    conn.commit()
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Перейти к оплате", url=confirmation_url)],
                        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_topup_{purchase_id}")]
                    ])
                    await bot.edit_message_text(
                        f"💳 ОПЛАТА ПОПОЛНЕНИЯ\n\n"
                        f"🛒 Заказ #{purchase_id}\n"
                        f"💰 Сумма: {amount_rub} руб.\n\n"
                        f"👇 Нажмите кнопку для оплаты:",
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    logger.error(f"Ошибка YooKassa topup: status={resp.status}, body={response_text}")
                    await bot.edit_message_text(
                        "❌ Ошибка при создании платежа. Попробуйте позже.",
                        chat_id=chat_id,
                        message_id=message_id
                    )
        except Exception:
            logger.exception("Ошибка соединения с YooKassa topup")
            await bot.edit_message_text(
                "❌ Ошибка соединения. Попробуйте позже.",
                chat_id=chat_id,
                message_id=message_id
            )


@router.callback_query(F.data.startswith("check_topup_"))
async def check_topup(callback: CallbackQuery):
    await callback.answer()

    if not YOOKASSA_ENABLED:
        await callback.message.answer("❌ Пополнение недоступно. Настройте ЮKassa в .env.")
        return

    try:
        purchase_id = int(callback.data.split('_')[2])
    except (IndexError, ValueError):
        await callback.message.answer("❌ Некорректный номер заказа")
        return

    purchase = get_purchase(purchase_id)
    if not purchase:
        await callback.message.answer("Пополнение не найдено")
        return

    user_id, stars, amount_kopecks, status, payment_id, payment_method = purchase

    if status == 'completed':
        await callback.message.answer("Баланс уже пополнен")
        return
    if status not in ('waiting_payment', 'paid'):
        await callback.message.answer("Статус платежа неизвестен")
        return
    if not payment_id:
        await callback.message.answer("❌ У заказа нет payment_id")
        return

    auth = aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", auth=auth) as resp:
                response_text = await resp.text()

                if resp.status != 200:
                    logger.error(f"Ошибка проверки YooKassa: status={resp.status}, body={response_text}")
                    await callback.message.answer("Ошибка при проверке платежа.")
                    return

                payment_info = await resp.json()
                payment_status = payment_info.get('status')

                if payment_status != 'succeeded':
                    if payment_status == 'pending':
                        await callback.message.answer("⏳ Платеж в обработке. Подождите и проверьте снова.")
                    else:
                        await callback.message.answer(f"Статус платежа: {payment_status}")
                    return

                cursor.execute('SELECT status FROM purchases WHERE id = ?', (purchase_id,))
                row = cursor.fetchone()
                if not row:
                    await callback.message.answer("Заказ не найден")
                    return

                current_status = row[0]
                if current_status == 'completed':
                    await callback.message.answer("Баланс уже пополнен")
                    return
                if current_status not in ('waiting_payment', 'paid'):
                    await callback.message.answer("Статус заказа некорректен")
                    return

                locked = try_lock_purchase(purchase_id, 'waiting_payment', 'completed', datetime.now())
                if not locked:
                    locked = try_lock_purchase(purchase_id, 'paid', 'completed', datetime.now())
                if not locked:
                    await callback.message.answer("Баланс уже пополнен")
                    return

                update_user_balance(user_id, amount_kopecks)
                await callback.message.edit_text(
                    f"✅ Баланс пополнен!\n\n"
                    f"🛒 Заказ #{purchase_id}\n"
                    f"💰 Сумма: {format_price(amount_kopecks)} руб.\n\n"
                    f"Ваш баланс успешно пополнен.",
                    parse_mode="HTML"
                )

    except Exception:
        logger.exception("Ошибка проверки платежа")
        await callback.message.answer("Ошибка при проверке платежа.")


@router.callback_query(F.data.startswith("complete_order_"), F.from_user.id.in_(ADMIN_IDS))
async def complete_order(callback: CallbackQuery):
    try:
        purchase_id = int(callback.data.split('_')[2])
    except (IndexError, ValueError):
        await callback.answer("Некорректный заказ", show_alert=True)
        return

    cursor.execute('''
        SELECT p.user_id, p.stars_count, p.amount_rub, u.username, u.full_name, p.status
        FROM purchases p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.id = ?
    ''', (purchase_id,))
    order = cursor.fetchone()
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    user_id, stars, amount_kopecks, username, full_name, status = order
    if not try_lock_purchase(purchase_id, 'paid', 'completed', datetime.now()):
        await callback.answer("Заказ уже обработан", show_alert=True)
        return

    try:
        await callback.bot.send_message(
            user_id,
            f"🎉 ЗАКАЗ ВЫПОЛНЕН!\n\n"
            f"✅ Администратор выдал вам {stars} звёзд.\n"
            f"🛒 Заказ #{purchase_id}\n"
            f"⭐️ Количество: {stars} звёзд\n"
            f"💰 Сумма: {format_price(amount_kopecks)} руб.\n\n"
            f"Спасибо за покупку! 🚀",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

    await callback.message.edit_text(
        text=f"✅ ВЫДАЧА ПОДТВЕРЖДЕНА\n\n"
             f"📋 Заказ #{purchase_id}\n"
             f"👤 {full_name} (@{username or 'нет'})\n"
             f"⭐️ {stars} звёзд выданы\n"
             f"💰 {format_price(amount_kopecks)} руб.\n"
             f"👑 Выдал: @{callback.from_user.username or 'админ'}\n"
             f"⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}",
        reply_markup=None,
        parse_mode="HTML"
    )
    await callback.answer("✅ Заказ отмечен выполненным")


async def check_referral_bonus(bot: Bot, user_id: int, amount_kopecks: int):
    cursor.execute('SELECT referrer_id FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0]:
        referrer_id = row[0]
        cursor.execute('UPDATE users SET invited_paid_count = invited_paid_count + 1 WHERE user_id = ?', (referrer_id,))
        conn.commit()

        cursor.execute('SELECT invited_paid_count, bonus_stars_earned FROM users WHERE user_id = ?', (referrer_id,))
        ref_row = cursor.fetchone()
        if not ref_row:
            return

        count, earned = ref_row
        if count >= 10 and earned == 0:
            stars_bonus = 100
            order_id = f"REF_{referrer_id}_{int(datetime.now().timestamp())}"
            cursor.execute(
                '''INSERT INTO purchases (user_id, order_id, stars_count, amount_rub, payment_method, status, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (referrer_id, order_id, stars_bonus, 0, 'referral_bonus', 'completed', datetime.now().isoformat())
            )
            cursor.execute('UPDATE users SET bonus_stars_earned = bonus_stars_earned + ? WHERE user_id = ?', (stars_bonus, referrer_id))
            conn.commit()

            await bot.send_message(
                referrer_id,
                f"🎉 Реферальный бонус!\n\nПоздравляем! 10 ваших друзей совершили оплату. Вы получили {stars_bonus} звёзд.\nСпасибо за приглашения!",
                parse_mode="HTML"
            )
            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    admin_id,
                    f"🎁 Реферальный бонус\nРеферер: {referrer_id}\nНачислено: {stars_bonus} звёзд за 10 оплативших приглашённых.",
                    parse_mode="HTML"
                )


@router.callback_query(F.data == "referral")
async def referral_info(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute('SELECT invited_count, bonus_stars_earned FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    invited_count, bonus = row if row else (0, 0)

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await callback.bot.get_me()
        BOT_USERNAME = me.username

    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    text = (
        f"🤝 Реферальная система\n\n"
        f"Приглашайте друзей и получайте бонусы!\n"
        f"Ваша реферальная ссылка:\n{link}\n\n"
        f"📊 Приглашено друзей: {invited_count}\n"
        f"⭐️ Получено бонусных звёзд: {bonus}\n\n"
        f"Условия:\n"
        f"• За каждого приглашённого друга, который совершит любую оплату, счётчик увеличивается.\n"
        f"• Как только 10 приглашённых друзей совершат оплату, вы получите 100 звёзд (бонус начисляется один раз).\n"
        f"• Бонус зачисляется автоматически."
    )
    await callback.message.edit_text(text, reply_markup=back_button(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute('SELECT username, full_name, balance, reg_date FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    username, full_name, balance_kopecks, reg_date = user
    cursor.execute('SELECT COUNT(*), SUM(stars_count), SUM(amount_rub) FROM purchases WHERE user_id = ? AND status = "completed"', (user_id,))
    stats = cursor.fetchone()
    total_orders = stats[0] or 0
    total_stars = stats[1] or 0
    total_spent = stats[2] or 0

    text = (
        f"👤 Профиль\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {full_name}\n"
        f"🔗 @{username or 'нет'}\n"
        f"💰 Баланс: {format_price(balance_kopecks)} руб.\n"
        f"📅 Регистрация: {reg_date[:16] if reg_date else '—'}\n\n"
        f"📊 Статистика покупок:\n"
        f"🛒 Всего заказов: {total_orders}\n"
        f"⭐️ Всего звёзд: {total_stars}\n"
        f"💸 Потрачено: {format_price(total_spent)} руб."
    )
    await callback.message.edit_text(text, reply_markup=back_button(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "help")
async def help_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "❓ Помощь\n\nВыберите раздел:",
        reply_markup=help_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    if ADMIN_IDS:
        admin_chat = await callback.bot.get_chat(ADMIN_IDS[0])
        admin_link = f"https://t.me/{admin_chat.username}" if admin_chat.username else f"tg://user?id={ADMIN_IDS[0]}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📩 Написать администратору", url=admin_link)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="help")]
        ])
        await callback.message.edit_text(
            "📞 Связь с администратором\n\n"
            "Если у вас возникли вопросы или проблемы, напишите нам:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text("❌ Администратор не назначен.")
    await callback.answer()


@router.callback_query(F.data == "faq")
async def faq(callback: CallbackQuery):
    faq_text = (
        "❓ Часто задаваемые вопросы\n\n"
        "— Как происходит выдача товара?\n"
        "После подтверждения оплаты заказ выполняется автоматически, либо администратором, если авто-выдача не сработала.\n\n"
        "— Как быстро приходят звезды?\n"
        "Обычно это занимает 5-15 минут.\n\n"
        "— Могу ли я покупать звезды только для себя?\n"
        "Нет, вы можете отправлять подарки любым пользователям, у которых есть @username.\n"
    )
    await callback.message.edit_text(faq_text, reply_markup=back_button("help"), parse_mode="HTML")
    await callback.answer()


@router.message(StateFilter(CalcState.waiting_for_value), F.text)
async def calc_result(message: Message, state: FSMContext):
    data = await state.get_data()
    direction = data.get('direction')
    if not direction:
        await message.answer("❌ Ошибка расчёта. Начните заново.")
        await state.clear()
        return

    try:
        value = float(message.text.replace(',', '.'))
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.")
        return

    price = get_price_per_star()
    price_float = float(price)

    if direction == "stars_to_rub":
        total = value * price_float
        result = f"{value} звёзд = {total:.2f} руб."
    else:
        stars = value / price_float
        result = f"{value:.2f} руб. = {stars:.2f} звёзд"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="calculator")]
    ])
    await message.answer(result, reply_markup=keyboard, parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data == "calc_stars_to_rub")
async def calc_stars_to_rub_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите количество звёзд:")
    await state.update_data(direction="stars_to_rub")
    await state.set_state(CalcState.waiting_for_value)
    await callback.answer()


@router.callback_query(F.data == "calc_rub_to_stars")
async def calc_rub_to_stars_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите сумму в рублях:")
    await state.update_data(direction="rub_to_stars")
    await state.set_state(CalcState.waiting_for_value)
    await callback.answer()


@router.callback_query(F.data == "admin_panel", F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(callback: CallbackQuery):
    await callback.message.edit_text("👑 Админ-панель", reply_markup=admin_panel_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_stats", F.from_user.id.in_(ADMIN_IDS))
async def admin_stats(callback: CallbackQuery):
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM purchases WHERE status = 'completed'")
    completed = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM purchases WHERE status = 'paid'")
    awaiting_issue = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(amount_rub) FROM purchases WHERE status = 'completed'")
    revenue = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(stars_count) FROM purchases WHERE status = 'completed'")
    stars_sold = cursor.fetchone()[0] or 0

    text = (
        f"📊 Статистика\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"✅ Выполнено заказов: {completed}\n"
        f"🔄 Ожидают выдачи: {awaiting_issue}\n"
        f"💰 Выручка: {format_price(revenue)} руб.\n"
        f"⭐️ Продано звёзд: {stars_sold}"
    )
    await callback.message.edit_text(text, reply_markup=back_button("admin_panel"), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_pending", F.from_user.id.in_(ADMIN_IDS))
async def admin_pending(callback: CallbackQuery):
    cursor.execute('''
        SELECT p.id, p.user_id, u.username, u.full_name, p.stars_count, p.amount_rub, p.created_at, p.status, p.payment_method
        FROM purchases p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.status IN ('paid')
        ORDER BY p.created_at DESC
    ''')
    orders = cursor.fetchall()

    if not orders:
        await callback.message.edit_text("✅ Нет заказов, ожидающих выдачи.")
        await callback.answer()
        return

    text = "🔄 Заказы, ожидающие выдачи:\n\n"
    for order in orders:
        order_id, user_id, username, full_name, stars, amount_kopecks, created_at, status, payment_method = order
        created_str = created_at[:16] if created_at else "—"
        text += (
            f"🆔 Заказ #{order_id}\n"
            f"👤 {full_name} (@{username or 'нет'})\n"
            f"⭐️ {stars} звёзд\n"
            f"💰 {format_price(amount_kopecks)} руб.\n"
            f"📅 {created_str}\n"
            f"📌 Статус: {status}\n"
            f"💳 Способ: {payment_method}\n\n"
        )

    await callback.message.edit_text(text, reply_markup=back_button("admin_panel"), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_set_price", F.from_user.id.in_(ADMIN_IDS))
async def admin_set_price(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите новую цену за 1 звезду (в рублях, например 1.15):")
    await state.set_state(AdminPriceState.waiting_for_price)
    await callback.answer()


@router.message(StateFilter(AdminPriceState.waiting_for_price), F.text)
async def set_price_value(message: Message, state: FSMContext):
    try:
        price = Decimal(message.text.replace(',', '.'))
        if price <= 0:
            raise ValueError
        set_price_per_star(price)
        await message.answer(f"✅ Цена звезды установлена: {price:.2f} руб.")
        await state.clear()
    except Exception:
        await message.answer("❌ Неверный формат. Введите положительное число (например, 1.15).")


@router.callback_query(F.data == "admin_create_promo", F.from_user.id.in_(ADMIN_IDS))
async def admin_create_promo(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.answer("Введите код промокода (латиница, без пробелов):")
    await state.update_data(message_id=msg.message_id)
    await state.set_state(AdminPromoState.waiting_for_code)
    await callback.answer()


@router.message(StateFilter(AdminPromoState.waiting_for_code), F.text)
async def promo_code_entered(message: Message, state: FSMContext):
    code = message.text.strip()
    cursor.execute('SELECT 1 FROM promocodes WHERE code = ?', (code,))
    if cursor.fetchone():
        data = await state.get_data()
        bot_msg_id = data.get('message_id')
        await message.bot.edit_message_text(
            "❌ Промокод с таким кодом уже существует. Введите другой код.",
            chat_id=message.chat.id,
            message_id=bot_msg_id
        )
        return

    await state.update_data(code=code)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Фиксированное количество звёзд", callback_data="promo_type_fixed")],
        [InlineKeyboardButton(text="📊 Процент скидки", callback_data="promo_type_percent")]
    ])
    data = await state.get_data()
    bot_msg_id = data.get('message_id')
    await message.bot.edit_message_text(
        "Выберите тип промокода:",
        chat_id=message.chat.id,
        message_id=bot_msg_id,
        reply_markup=keyboard
    )
    await state.set_state(AdminPromoState.waiting_for_type)


@router.callback_query(StateFilter(AdminPromoState.waiting_for_type), F.data.startswith("promo_type_"))
async def promo_type_selected(callback: CallbackQuery, state: FSMContext):
    raw_type = callback.data.split('_')[2]
    discount_type = 'fixed_stars' if raw_type == 'fixed' else 'percent'
    await state.update_data(discount_type=discount_type)
    data = await state.get_data()
    bot_msg_id = data.get('message_id')

    if discount_type == 'fixed_stars':
        await callback.bot.edit_message_text(
            "Введите количество звёзд для начисления:",
            chat_id=callback.message.chat.id,
            message_id=bot_msg_id
        )
    else:
        await callback.bot.edit_message_text(
            "Введите процент скидки (целое число от 1 до 100):",
            chat_id=callback.message.chat.id,
            message_id=bot_msg_id
        )
    await state.set_state(AdminPromoState.waiting_for_value)
    await callback.answer()


@router.message(StateFilter(AdminPromoState.waiting_for_value), F.text)
async def promo_value_entered(message: Message, state: FSMContext):
    try:
        value = int(message.text)
        data = await state.get_data()
        if data['discount_type'] == 'fixed_stars':
            if value <= 0:
                raise ValueError
        else:
            if value < 1 or value > 100:
                raise ValueError
    except ValueError:
        data = await state.get_data()
        bot_msg_id = data.get('message_id')
        await message.bot.edit_message_text(
            "❌ Неверное значение. Введите целое положительное число.",
            chat_id=message.chat.id,
            message_id=bot_msg_id
        )
        return

    await state.update_data(discount_value=value)
    data = await state.get_data()
    bot_msg_id = data.get('message_id')
    await message.bot.edit_message_text(
        "Введите максимальное количество активаций (целое число):",
        chat_id=message.chat.id,
        message_id=bot_msg_id
    )
    await state.set_state(AdminPromoState.waiting_for_max_uses)


@router.message(StateFilter(AdminPromoState.waiting_for_max_uses), F.text)
async def promo_max_uses_entered(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text)
        if max_uses <= 0:
            raise ValueError
    except ValueError:
        data = await state.get_data()
        bot_msg_id = data.get('message_id')
        await message.bot.edit_message_text(
            "❌ Введите целое положительное число.",
            chat_id=message.chat.id,
            message_id=bot_msg_id
        )
        return

    data = await state.get_data()
    code = data['code']
    discount_type = data['discount_type']
    discount_value = data['discount_value']

    cursor.execute(
        'INSERT INTO promocodes (code, discount_type, discount_value, max_uses, created_by) VALUES (?, ?, ?, ?, ?)',
        (code, discount_type, discount_value, max_uses, message.from_user.id)
    )
    conn.commit()

    bot_msg_id = data.get('message_id')
    await message.bot.edit_message_text(
        f"✅ Промокод {code} создан.\n"
        f"Тип: {'фиксированные звёзды' if discount_type == 'fixed_stars' else 'скидка %'}\n"
        f"Значение: {discount_value}\n"
        f"Макс. активаций: {max_uses}",
        chat_id=message.chat.id,
        message_id=bot_msg_id
    )
    await state.clear()


@router.callback_query(F.data == "admin_list_promos", F.from_user.id.in_(ADMIN_IDS))
async def admin_list_promos(callback: CallbackQuery):
    cursor.execute('SELECT id, code, discount_type, discount_value, max_uses, used_count FROM promocodes ORDER BY id DESC')
    promos = cursor.fetchall()
    if not promos:
        await callback.message.edit_text("Нет созданных промокодов.")
        return

    text = "🎁 Список промокодов\n\n"
    for promo in promos:
        promo_id, code, d_type, d_value, max_uses, used = promo
        type_str = "фикс. звёзды" if d_type == 'fixed_stars' else f"{d_value}%"
        text += f"• {code} – {type_str} – {used}/{max_uses}\n"

    await callback.message.edit_text(text, reply_markup=back_button("admin_panel"), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "topup")
async def topup_start(callback: CallbackQuery):
    await callback.message.edit_text(
        "💰 Пополнение баланса\nВыберите сумму (в рублях):",
        reply_markup=topup_amount_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("topup_"))
async def topup_amount(callback: CallbackQuery, state: FSMContext):
    amount_str = callback.data.split('_')[1]
    if amount_str == 'custom':
        await callback.message.edit_text("Введите сумму пополнения (от 1 до 10000 рублей):")
        await state.update_data(bot_msg_id=callback.message.message_id)
        await state.set_state(TopupState.waiting_for_amount)
        await callback.answer()
        return

    amount = int(amount_str)
    await create_topup_payment(
        callback.bot, callback.from_user.id, callback.from_user.username,
        callback.message.chat.id, callback.message.message_id, amount
    )
    await callback.answer()


@router.message(StateFilter(TopupState.waiting_for_amount), F.text)
async def topup_custom_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount < 1 or amount > 10000:
            raise ValueError
        amount_rub = int(amount)
    except Exception:
        await message.answer("❌ Неверная сумма. Введите число от 1 до 10000.")
        return

    data = await state.get_data()
    bot_msg_id = data.get('bot_msg_id')
    await state.clear()

    if not bot_msg_id:
        sent = await message.answer("⏳")
        bot_msg_id = sent.message_id

    await create_topup_payment(
        message.bot, message.from_user.id, message.from_user.username,
        message.chat.id, bot_msg_id, amount_rub
    )


async def create_topup_payment(bot: Bot, user_id: int, username: str, chat_id: int, message_id: int, amount_rub: int):
    if not YOOKASSA_ENABLED:
        await bot.edit_message_text(
            "❌ Пополнение недоступно. Настройте ЮKassa в .env.",
            chat_id=chat_id,
            message_id=message_id
        )
        return

    amount_kopecks = amount_rub * 100
    purchase_id = add_purchase(user_id, 0, amount_kopecks, 'topup', 'creating_payment')
    cursor.execute('SELECT order_id FROM purchases WHERE id = ?', (purchase_id,))
    row = cursor.fetchone()
    order_id = row[0] if row else None

    payment_data = {
        "amount": {"value": f"{amount_rub}.00", "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{username}" if username else "https://t.me"
        },
        "description": f"Пополнение баланса на {amount_rub} руб.",
        "metadata": {
            "purchase_id": purchase_id,
            "user_id": user_id,
            "order_id": order_id,
            "type": "topup"
        }
    }

    headers = {"Content-Type": "application/json", "Idempotence-Key": str(uuid.uuid4())}
    auth = aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)

    try:
        await bot.edit_message_text("<b>⏳ Создаем платеж...</b>", chat_id=chat_id, message_id=message_id, parse_mode="HTML")
    except Exception:
        pass

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        try:
            async with session.post(
                "https://api.yookassa.ru/v3/payments",
                json=payment_data,
                headers=headers,
                auth=auth
            ) as resp:
                response_text = await resp.text()

                if resp.status in (200, 201):
                    payment_info = await resp.json()
                    payment_id = payment_info['id']
                    confirmation_url = payment_info['confirmation']['confirmation_url']
                    cursor.execute('UPDATE purchases SET payment_id = ?, status = ? WHERE id = ?', (payment_id, 'waiting_payment', purchase_id))
                    conn.commit()
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Перейти к оплате", url=confirmation_url)],
                        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_topup_{purchase_id}")]
                    ])
                    await bot.edit_message_text(
                        f"💳 ОПЛАТА ПОПОЛНЕНИЯ\n\n"
                        f"🛒 Заказ #{purchase_id}\n"
                        f"💰 Сумма: {amount_rub} руб.\n\n"
                        f"👇 Нажмите кнопку для оплаты:",
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                else:
                    logger.error(f"Ошибка YooKassa topup: status={resp.status}, body={response_text}")
                    await bot.edit_message_text(
                        "❌ Ошибка при создании платежа. Попробуйте позже.",
                        chat_id=chat_id,
                        message_id=message_id
                    )
        except Exception:
            logger.exception("Ошибка соединения с YooKassa topup")
            await bot.edit_message_text(
                "❌ Ошибка соединения. Попробуйте позже.",
                chat_id=chat_id,
                message_id=message_id
            )


@router.callback_query(F.data.startswith("check_topup_"))
async def check_topup(callback: CallbackQuery):
    await callback.answer()

    if not YOOKASSA_ENABLED:
        await callback.message.answer("❌ Пополнение недоступно. Настройте ЮKassa в .env.")
        return

    try:
        purchase_id = int(callback.data.split('_')[2])
    except (IndexError, ValueError):
        await callback.message.answer("❌ Некорректный номер заказа")
        return

    purchase = get_purchase(purchase_id)
    if not purchase:
        await callback.message.answer("Пополнение не найдено")
        return

    user_id, stars, amount_kopecks, status, payment_id, payment_method = purchase

    if status == 'completed':
        await callback.message.answer("Баланс уже пополнен")
        return
    if status not in ('waiting_payment', 'paid'):
        await callback.message.answer("Статус платежа неизвестен")
        return
    if not payment_id:
        await callback.message.answer("❌ У заказа нет payment_id")
        return

    auth = aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", auth=auth) as resp:
                response_text = await resp.text()

                if resp.status != 200:
                    logger.error(f"Ошибка проверки YooKassa: status={resp.status}, body={response_text}")
                    await callback.message.answer("Ошибка при проверке платежа.")
                    return

                payment_info = await resp.json()
                payment_status = payment_info.get('status')

                if payment_status != 'succeeded':
                    if payment_status == 'pending':
                        await callback.message.answer("⏳ Платеж в обработке. Подождите и проверьте снова.")
                    else:
                        await callback.message.answer(f"Статус платежа: {payment_status}")
                    return

                cursor.execute('SELECT status FROM purchases WHERE id = ?', (purchase_id,))
                row = cursor.fetchone()
                if not row:
                    await callback.message.answer("Заказ не найден")
                    return

                current_status = row[0]
                if current_status == 'completed':
                    await callback.message.answer("Баланс уже пополнен")
                    return
                if current_status not in ('waiting_payment', 'paid'):
                    await callback.message.answer("Статус заказа некорректен")
                    return

                locked = try_lock_purchase(purchase_id, 'waiting_payment', 'completed', datetime.now())
                if not locked:
                    locked = try_lock_purchase(purchase_id, 'paid', 'completed', datetime.now())
                if not locked:
                    await callback.message.answer("Баланс уже пополнен")
                    return

                update_user_balance(user_id, amount_kopecks)
                await callback.message.edit_text(
                    f"✅ Баланс пополнен!\n\n"
                    f"🛒 Заказ #{purchase_id}\n"
                    f"💰 Сумма: {format_price(amount_kopecks)} руб.\n\n"
                    f"Ваш баланс успешно пополнен.",
                    parse_mode="HTML"
                )

    except Exception:
        logger.exception("Ошибка проверки платежа")
        await callback.message.answer("Ошибка при проверке платежа.")


@router.callback_query(F.data.startswith("complete_order_"), F.from_user.id.in_(ADMIN_IDS))
async def complete_order(callback: CallbackQuery):
    try:
        purchase_id = int(callback.data.split('_')[2])
    except (IndexError, ValueError):
        await callback.answer("Некорректный заказ", show_alert=True)
        return

    cursor.execute('''
        SELECT p.user_id, p.stars_count, p.amount_rub, u.username, u.full_name, p.status
        FROM purchases p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.id = ?
    ''', (purchase_id,))
    order = cursor.fetchone()
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    user_id, stars, amount_kopecks, username, full_name, status = order
    if not try_lock_purchase(purchase_id, 'paid', 'completed', datetime.now()):
        await callback.answer("Заказ уже обработан", show_alert=True)
        return

    try:
        await callback.bot.send_message(
            user_id,
            f"🎉 ЗАКАЗ ВЫПОЛНЕН!\n\n"
            f"✅ Администратор выдал вам {stars} звёзд.\n"
            f"🛒 Заказ #{purchase_id}\n"
            f"⭐️ Количество: {stars} звёзд\n"
            f"💰 Сумма: {format_price(amount_kopecks)} руб.\n\n"
            f"Спасибо за покупку! 🚀",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

    await callback.message.edit_text(
        text=f"✅ ВЫДАЧА ПОДТВЕРЖДЕНА\n\n"
             f"📋 Заказ #{purchase_id}\n"
             f"👤 {full_name} (@{username or 'нет'})\n"
             f"⭐️ {stars} звёзд выданы\n"
             f"💰 {format_price(amount_kopecks)} руб.\n"
             f"👑 Выдал: @{callback.from_user.username or 'админ'}\n"
             f"⏰ {datetime.now().strftime('%H:%M %d.%m.%Y')}",
        reply_markup=None,
        parse_mode="HTML"
    )
    await callback.answer("✅ Заказ отмечен выполненным")


async def check_referral_bonus(bot: Bot, user_id: int, amount_kopecks: int):
    cursor.execute('SELECT referrer_id FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0]:
        referrer_id = row[0]
        cursor.execute('UPDATE users SET invited_paid_count = invited_paid_count + 1 WHERE user_id = ?', (referrer_id,))
        conn.commit()

        cursor.execute('SELECT invited_paid_count, bonus_stars_earned FROM users WHERE user_id = ?', (referrer_id,))
        ref_row = cursor.fetchone()
        if not ref_row:
            return

        count, earned = ref_row
        if count >= 10 and earned == 0:
            stars_bonus = 100
            order_id = f"REF_{referrer_id}_{int(datetime.now().timestamp())}"
            cursor.execute(
                '''INSERT INTO purchases (user_id, order_id, stars_count, amount_rub, payment_method, status, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (referrer_id, order_id, stars_bonus, 0, 'referral_bonus', 'completed', datetime.now().isoformat())
            )
            cursor.execute('UPDATE users SET bonus_stars_earned = bonus_stars_earned + ? WHERE user_id = ?', (stars_bonus, referrer_id))
            conn.commit()

            await bot.send_message(
                referrer_id,
                f"🎉 Реферальный бонус!\n\nПоздравляем! 10 ваших друзей совершили оплату. Вы получили {stars_bonus} звёзд.\nСпасибо за приглашения!",
                parse_mode="HTML"
            )
            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    admin_id,
                    f"🎁 Реферальный бонус\nРеферер: {referrer_id}\nНачислено: {stars_bonus} звёзд за 10 оплативших приглашённых.",
                    parse_mode="HTML"
                )


@router.callback_query(F.data == "referral")
async def referral_info(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute('SELECT invited_count, bonus_stars_earned FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    invited_count, bonus = row if row else (0, 0)

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await callback.bot.get_me()
        BOT_USERNAME = me.username

    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    text = (
        f"🤝 Реферальная система\n\n"
        f"Приглашайте друзей и получайте бонусы!\n"
        f"Ваша реферальная ссылка:\n{link}\n\n"
        f"📊 Приглашено друзей: {invited_count}\n"
        f"⭐️ Получено бонусных звёзд: {bonus}\n\n"
        f"Условия:\n"
        f"• За каждого приглашённого друга, который совершит любую оплату, счётчик увеличивается.\n"
        f"• Как только 10 приглашённых друзей совершат оплату, вы получите 100 звёзд (бонус начисляется один раз).\n"
        f"• Бонус зачисляется автоматически."
    )
    await callback.message.edit_text(text, reply_markup=back_button(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute('SELECT username, full_name, balance, reg_date FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    username, full_name, balance_kopecks, reg_date = user
    cursor.execute('SELECT COUNT(*), SUM(stars_count), SUM(amount_rub) FROM purchases WHERE user_id = ? AND status = "completed"', (user_id,))
    stats = cursor.fetchone()
    total_orders = stats[0] or 0
    total_stars = stats[1] or 0
    total_spent = stats[2] or 0

    text = (
        f"👤 Профиль\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {full_name}\n"
        f"🔗 @{username or 'нет'}\n"
        f"💰 Баланс: {format_price(balance_kopecks)} руб.\n"
        f"📅 Регистрация: {reg_date[:16] if reg_date else '—'}\n\n"
        f"📊 Статистика покупок:\n"
        f"🛒 Всего заказов: {total_orders}\n"
        f"⭐️ Всего звёзд: {total_stars}\n"
        f"💸 Потрачено: {format_price(total_spent)} руб."
    )
    await callback.message.edit_text(text, reply_markup=back_button(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "help")
async def help_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "❓ Помощь\n\nВыберите раздел:",
        reply_markup=help_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    if ADMIN_IDS:
        admin_chat = await callback.bot.get_chat(ADMIN_IDS[0])
        admin_link = f"https://t.me/{admin_chat.username}" if admin_chat.username else f"tg://user?id={ADMIN_IDS[0]}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📩 Написать администратору", url=admin_link)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="help")]
        ])
        await callback.message.edit_text(
            "📞 Связь с администратором\n\n"
            "Если у вас возникли вопросы или проблемы, напишите нам:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text("❌ Администратор не назначен.")
    await callback.answer()


@router.callback_query(F.data == "faq")
async def faq(callback: CallbackQuery):
    faq_text = (
        "❓ Часто задаваемые вопросы\n\n"
        "— Как происходит выдача товара?\n"
        "После подтверждения оплаты заказ выполняется автоматически, либо администратором, если авто-выдача не сработала.\n\n"
        "— Как быстро приходят звезды?\n"
        "Обычно это занимает 5-15 минут.\n\n"
        "— Могу ли я покупать звезды только для себя?\n"
        "Нет, вы можете отправлять подарки любым пользователям, у которых есть @username.\n"
    )
    await callback.message.edit_text(faq_text, reply_markup=back_button("help"), parse_mode="HTML")
    await callback.answer()


@router.message(StateFilter(CalcState.waiting_for_value), F.text)
async def calc_result(message: Message, state: FSMContext):
    data = await state.get_data()
    direction = data.get('direction')
    if not direction:
        await message.answer("❌ Ошибка расчёта. Начните заново.")
        await state.clear()
        return

    try:
        value = float(message.text.replace(',', '.'))
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.")
        return

    price = get_price_per_star()
    price_float = float(price)

    if direction == "stars_to_rub":
        total = value * price_float
        result = f"{value} звёзд = {total:.2f} руб."
    else:
        stars = value / price_float
        result = f"{value:.2f} руб. = {stars:.2f} звёзд"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="calculator")]
    ])
    await message.answer(result, reply_markup=keyboard, parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data == "calc_stars_to_rub")
async def calc_stars_to_rub_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите количество звёзд:")
    await state.update_data(direction="stars_to_rub")
    await state.set_state(CalcState.waiting_for_value)
    await callback.answer()


@router.callback_query(F.data == "calc_rub_to_stars")
async def calc_rub_to_stars_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите сумму в рублях:")
    await state.update_data(direction="rub_to_stars")
    await state.set_state(CalcState.waiting_for_value)
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await show_main_menu(callback, callback.from_user.id, edit=True)
    await callback.answer()


@router.message()
async def unknown_message(message: Message):
    await show_main_menu(message, message.from_user.id)
