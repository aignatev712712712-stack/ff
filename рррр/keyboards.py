from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import ADMIN_IDS

def main_menu_keyboard(user_id: int, is_admin: bool):
    rows = [
        [InlineKeyboardButton(text="⭐ Купить звёзды", callback_data="buy_stars")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="topup")],
        [InlineKeyboardButton(text="🧮 Калькулятор", callback_data="calculator")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🤝 Рефералка", callback_data="referral")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def payment_keyboard(confirmation_url: str, purchase_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=confirmation_url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_payment_{purchase_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔄 Оплаченные (ожидают)", callback_data="admin_pending")],
        [InlineKeyboardButton(text="💵 Установить цену", callback_data="admin_set_price")],
        [InlineKeyboardButton(text="🎁 Промокоды", callback_data="admin_list_promos")],
        [InlineKeyboardButton(text="➕ Создать промо", callback_data="admin_create_promo")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def back_button(target: str | None = None):
    cb = target if target else "back_to_menu"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=cb)]])

def topup_amount_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="100₽", callback_data="topup_100"),
            InlineKeyboardButton(text="200₽", callback_data="topup_200"),
            InlineKeyboardButton(text="500₽", callback_data="topup_500"),
        ],
        [
            InlineKeyboardButton(text="1000₽", callback_data="topup_1000"),
            InlineKeyboardButton(text="2000₽", callback_data="topup_2000"),
            InlineKeyboardButton(text="5000₽", callback_data="topup_5000"),
        ],
        [InlineKeyboardButton(text="Другая сумма", callback_data="topup_custom")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def calculator_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔢 Звёзды → Рубли", callback_data="calc_stars_to_rub")],
        [InlineKeyboardButton(text="💱 Рубли → Звёзды", callback_data="calc_rub_to_stars")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def help_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Поддержка", callback_data="support")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
