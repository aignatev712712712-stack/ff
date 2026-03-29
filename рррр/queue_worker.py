import asyncio
import logging
from datetime import datetime

from database import (
    cursor, conn, get_next_queued_delivery, set_delivery_status,
    increment_delivery_attempt, get_purchase, update_purchase_status,
    format_price
)
from fragment_bot import deliver_stars_to_user
from config import FRAGMENT_AUTO_DELIVERY, ADMIN_IDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("queue_worker")

WORKER_SLEEP = 5

async def process_one(app_bot=None):
    row = get_next_queued_delivery()
    if not row:
        return False

    queue_id = row["id"]
    purchase_id = row["purchase_id"]

    increment_delivery_attempt(queue_id, "picked by worker")

    purchase = get_purchase(purchase_id)
    if not purchase:
        set_delivery_status(queue_id, "failed", "purchase not found")
        return True

    user_id, stars, amount_kopecks, status, payment_id, payment_method = purchase

    if status != "paid":
        set_delivery_status(queue_id, "failed", f"bad purchase status: {status}")
        return True

    cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
    urow = cursor.fetchone()
    username = urow[0] if urow else None
    if not username:
        set_delivery_status(queue_id, "failed", "no username")
        return True

    try:
        result = await deliver_stars_to_user(username=username, stars=stars)
        if result.get("ok"):
            update_purchase_status(purchase_id, "completed", datetime.now())
            set_delivery_status(queue_id, "done", None)
            logger.info(f"Purchase #{purchase_id} completed")
        else:
            err = result.get("error", "unknown")
            set_delivery_status(queue_id, "failed", err)
            logger.error(f"Purchase #{purchase_id} failed: {err}")
    except Exception as e:
        set_delivery_status(queue_id, "failed", str(e))
        logger.exception(f"Purchase #{purchase_id} worker error")

    return True

async def worker_loop():
    logger.info("Queue worker started")
    while True:
        try:
            processed = await process_one()
            if not processed:
                await asyncio.sleep(WORKER_SLEEP)
            else:
                await asyncio.sleep(1)
        except Exception:
            logger.exception("Worker loop error")
            await asyncio.sleep(WORKER_SLEEP)

if __name__ == "__main__":
    asyncio.run(worker_loop())
