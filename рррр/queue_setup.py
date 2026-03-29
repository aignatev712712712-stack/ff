from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_keyboard(user_id: int, is_admin: bool = False):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ Купить звёзды", callback_data="buy_stars")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🎁 Промокод", callback_data="promo")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="topup")],
        [InlineKeyboardButton(text="🧮 Калькулятор", callback_data="calculator")],
        [InlineKeyboardButton(text="🤝 Реферальная система", callback_data="referral")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
    ])
    if is_admin:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    return keyboard

def back_button(callback_data: str = "back_to_menu"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data)]])

def topup_amount_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="100 руб.", callback_data="topup_100")],
        [InlineKeyboardButton(text="500 руб.", callback_data="topup_500")],
        [InlineKeyboardButton(text="1000 руб.", callback_data="topup_1000")],
        [InlineKeyboardButton(text="Своя сумма", callback_data="topup_custom")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def payment_keyboard(payment_url: str, purchase_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_payment_{purchase_id}")]
    ])

def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔄 Ожидают выдачи", callback_data="admin_pending")],
        [InlineKeyboardButton(text="💰 Установить цену звезды", callback_data="admin_set_price")],
        [InlineKeyboardButton(text="🎁 Создать промокод", callback_data="admin_create_promo")],
        [InlineKeyboardButton(text="📜 Промокоды", callback_data="admin_list_promos")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def help_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Поддержка", callback_data="support")],
        [InlineKeyboardButton(text="❓ Часто задаваемые вопросы", callback_data="faq")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def calculator_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ Звёзды → Рубли", callback_data="calc_stars_to_rub")],
        [InlineKeyboardButton(text="💰 Рубли → Звёзды", callback_data="calc_rub_to_stars")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
