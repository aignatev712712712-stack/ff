from aiogram.fsm.state import State, StatesGroup

class BuyStarsState(StatesGroup):
    waiting_for_stars = State()
    waiting_for_confirmation = State()

class PromoState(StatesGroup):
    waiting_for_code = State()
    message_id = State()

class AdminPriceState(StatesGroup):
    waiting_for_price = State()

class AdminPromoState(StatesGroup):
    waiting_for_code = State()
    waiting_for_type = State()
    waiting_for_value = State()
    waiting_for_max_uses = State()
    message_id = State()

class TopupState(StatesGroup):
    waiting_for_amount = State()

class CalcState(StatesGroup):
    waiting_for_value = State()
