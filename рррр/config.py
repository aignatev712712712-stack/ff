import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

API_TOKEN = (os.getenv("API_TOKEN") or "").strip()
if not API_TOKEN:
    raise ValueError("API_TOKEN не задан в .env")

ADMIN_IDS_STR = (os.getenv("ADMIN_IDS") or "").strip()
logger = logging.getLogger(__name__)
if not ADMIN_IDS_STR:
    logger.warning("ADMIN_IDS не задан в .env. Админ-панель будет недоступна.")
    ADMIN_IDS = []
else:
    ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()]

YOOKASSA_SHOP_ID = (os.getenv("YOOKASSA_SHOP_ID") or "").strip()
YOOKASSA_SECRET_KEY = (os.getenv("YOOKASSA_SECRET_KEY") or "").strip()
YOOKASSA_ENABLED = bool(YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY)
if not YOOKASSA_ENABLED:
    logger.warning("Настройки ЮKassa не заданы. Оплата картой и пополнение баланса будут недоступны.")

FRAGMENT_STATE_PATH = (Path(__file__).resolve().parent / "fragment_state.json").as_posix()
FRAGMENT_ORDER_TIMEOUT = int((os.getenv("FRAGMENT_ORDER_TIMEOUT") or "180").strip())
FRAGMENT_AUTO_DELIVERY = (os.getenv("FRAGMENT_AUTO_DELIVERY") or "1").strip() == "1"
