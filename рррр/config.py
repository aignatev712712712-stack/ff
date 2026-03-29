import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = (os.getenv("API_TOKEN") or "").strip()
if not API_TOKEN:
    raise ValueError("API_TOKEN не задан в .env")

ADMIN_IDS_STR = (os.getenv("ADMIN_IDS") or "").strip()
if not ADMIN_IDS_STR:
    raise ValueError("ADMIN_IDS не задан в .env")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()]

YOOKASSA_SHOP_ID = (os.getenv("YOOKASSA_SHOP_ID") or "").strip()
YOOKASSA_SECRET_KEY = (os.getenv("YOOKASSA_SECRET_KEY") or "").strip()
if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
    raise ValueError("Настройки ЮKassa не заданы в .env")

FRAGMENT_STATE_PATH = (Path(__file__).resolve().parent / "fragment_state.json").as_posix()
FRAGMENT_ORDER_TIMEOUT = int((os.getenv("FRAGMENT_ORDER_TIMEOUT") or "180").strip())
FRAGMENT_AUTO_DELIVERY = (os.getenv("FRAGMENT_AUTO_DELIVERY") or "1").strip() == "1"
