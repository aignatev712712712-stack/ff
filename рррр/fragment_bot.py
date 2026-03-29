import logging
import time
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from config import FRAGMENT_STATE_PATH, FRAGMENT_ORDER_TIMEOUT, TONKEEPER_AUTO_CONFIRM

MIN_FRAGMENT_TIMEOUT = 5
TONKEEPER_CONFIRM_INTERVAL = 5

try:
    from tonkeeper_confirm import confirm_tonkeeper_click
    TONKEEPER_CONFIRM_AVAILABLE = True
    TONKEEPER_CONFIRM_IMPORT_ERROR = None
except ImportError as e:
    confirm_tonkeeper_click = None
    TONKEEPER_CONFIRM_AVAILABLE = False
    TONKEEPER_CONFIRM_IMPORT_ERROR = f"ImportError: {e}"
except Exception as e:
    confirm_tonkeeper_click = None
    TONKEEPER_CONFIRM_AVAILABLE = False
    TONKEEPER_CONFIRM_IMPORT_ERROR = f"Tonkeeper import failed: {e}"

logger = logging.getLogger(__name__)

async def _dump_state(page, label: str):
    try:
        logger.info(f"[Fragment] {label} URL={page.url}")
        title = await page.title()
        logger.info(f"[Fragment] {label} TITLE={title}")
    except Exception as e:
        logger.info(f"[Fragment] {label} state dump failed: {e}")

async def _try_click_by_text(page, texts, timeout=5000):
    for text in texts:
        try:
            loc = page.get_by_text(text, exact=False).first
            if await loc.count() > 0:
                await loc.click(timeout=timeout)
                logger.info(f"[Fragment] clicked text '{text}'")
                return text
        except Exception as e:
            logger.info(f"[Fragment] cannot click text '{text}': {e}")
    return None

async def _try_fill_by_selector(page, selectors, value, timeout=5000):
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                await loc.fill(value, timeout=timeout)
                logger.info(f"[Fragment] filled '{selector}' with '{value}'")
                return selector
        except Exception as e:
            logger.info(f"[Fragment] cannot fill '{selector}': {e}")
    return None

async def _try_select_radio_like(page, candidates):
    for text in candidates:
        try:
            loc = page.get_by_text(text, exact=False).first
            if await loc.count() > 0:
                await loc.click(timeout=5000)
                logger.info(f"[Fragment] selected package '{text}'")
                return text
        except Exception as e:
            logger.info(f"[Fragment] cannot select package '{text}': {e}")
    return None

def _try_confirm_tonkeeper():
    if not TONKEEPER_CONFIRM_AVAILABLE or confirm_tonkeeper_click is None:
        return {"ok": False, "error": f"Tonkeeper import failed: {TONKEEPER_CONFIRM_IMPORT_ERROR}"}

    try:
        return confirm_tonkeeper_click()
    except Exception as e:
        return {"ok": False, "error": f"Tonkeeper confirm failed: {e}"}

async def _wait_for_fragment_success(page, username: str, stars: int):
    success_markers = [
        "success",
        "completed",
        "purchased",
        "done",
        "успешно",
        "оплачено",
        "завершено",
        "sent a gift",
        "gift for",
        "transaction",
    ]

    confirmation_timeout = None
    if FRAGMENT_ORDER_TIMEOUT > 0:
        confirmation_timeout = max(MIN_FRAGMENT_TIMEOUT, FRAGMENT_ORDER_TIMEOUT)
    confirmation_deadline = (
        time.monotonic() + confirmation_timeout if confirmation_timeout else None
    )
    next_confirm_at = 0.0
    last_confirm_error = None

    if confirmation_deadline is None:
        logger.info("[Fragment] waiting for Tonkeeper confirmation without timeout")

    while True:
        if confirmation_deadline and time.monotonic() >= confirmation_deadline:
            break
        if page.is_closed():
            return {"ok": False, "error": "Страница Fragment закрыта до подтверждения Tonkeeper"}
        if TONKEEPER_AUTO_CONFIRM and time.monotonic() >= next_confirm_at:
            next_confirm_at = time.monotonic() + TONKEEPER_CONFIRM_INTERVAL
            confirm_result = _try_confirm_tonkeeper()
            if confirm_result.get("ok"):
                logger.info(f"[Tonkeeper] confirm clicked ({confirm_result.get('method')})")
                last_confirm_error = None
            else:
                last_confirm_error = confirm_result.get("error")
                logger.info(f"[Tonkeeper] confirm not clicked: {last_confirm_error}")

        page_text = ""
        try:
            page_text = await page.locator("body").inner_text(timeout=5000)
        except Exception:
            pass

        if any(m in page_text.lower() for m in success_markers):
            await page.screenshot(path=str(Path(__file__).resolve().parent / "fragment_success.png"), full_page=True)
            return {"ok": True, "message": f"Fragment success detected for @{username}, requested {stars} stars"}

        await page.wait_for_timeout(2000)

    await page.screenshot(path=str(Path(__file__).resolve().parent / "fragment_debug_after_confirm.png"), full_page=True)
    if last_confirm_error:
        return {"ok": False, "error": f"Не удалось подтвердить Tonkeeper: {last_confirm_error}"}
    return {"ok": False, "error": "Подтверждение Tonkeeper не выполнено за отведённое время"}

async def deliver_stars_to_user(username: str, stars: int) -> dict:
    state_path = Path(FRAGMENT_STATE_PATH)
    if not state_path.exists():
        return {"ok": False, "error": "fragment_state.json не найден. Сначала авторизуй Fragment через fragment_login.py"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=str(state_path))
        page = await context.new_page()

        try:
            logger.info(f"[Fragment] Start delivery to @{username}, stars={stars}")

            await page.goto("https://fragment.com/stars/buy", wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            await _dump_state(page, "buy page")

            await _try_fill_by_selector(page, [
                'input[type="search"]',
                'input[type="text"]',
                'input[name*="recipient"]',
                'input[placeholder*="username"]',
            ], username)

            await page.wait_for_timeout(1000)
            await _dump_state(page, "after recipient fill")

            await _try_fill_by_selector(page, [
                'input[name="quantity"]',
                'input[type="number"]',
                'input[name*="quantity"]',
            ], str(stars))

            await page.wait_for_timeout(1000)
            await _dump_state(page, "after quantity fill")

            if stars == 50:
                await _try_select_radio_like(page, [
                    "50 Stars",
                    "⭐ 50 Stars",
                    "Buy 50 Telegram Stars",
                ])

            await page.wait_for_timeout(1000)
            await _dump_state(page, "after package select")

            clicked = await _try_click_by_text(page, [
                f"Buy {stars} Telegram Stars",
                f"Buy {stars} Stars",
                "Buy Telegram Stars",
                "Buy Stars",
                "Buy",
            ])
            if not clicked:
                await page.screenshot(path=str(Path(__file__).resolve().parent / "fragment_debug_no_buy_button.png"), full_page=True)
                return {"ok": False, "error": "Не найдена кнопка Buy. Смотри fragment_debug_no_buy_button.png"}

            await page.wait_for_timeout(2000)
            await _dump_state(page, "after first buy click")

            # Ждём модалку подтверждения и кликаем её кнопку
            confirm_clicked = await _try_click_by_text(page, [
                "Buy Stars for",
                "Buy Stars",
                "Confirm",
                "Continue",
                "Proceed",
                "Подтвердить",
                "Продолжить",
                "Оплатить",
            ])

            if confirm_clicked:
                logger.info(f"[Fragment] clicked confirm '{confirm_clicked}'")
                await page.wait_for_timeout(3000)
                await _dump_state(page, "after confirm click")
            else:
                # иногда модалка появляется чуть позже, повторим короткую попытку
                await page.wait_for_timeout(1500)
                confirm_clicked = await _try_click_by_text(page, [
                    "Buy Stars for",
                    "Buy Stars",
                    "Confirm",
                    "Continue",
                    "Proceed",
                    "Подтвердить",
                    "Продолжить",
                    "Оплатить",
                ])
                if confirm_clicked:
                    logger.info(f"[Fragment] clicked confirm second try '{confirm_clicked}'")
                    await page.wait_for_timeout(3000)
                    await _dump_state(page, "after confirm click second try")
                else:
                    await page.screenshot(path=str(Path(__file__).resolve().parent / "fragment_debug_confirm_missing.png"), full_page=True)
                    return {"ok": False, "error": "Не найдена кнопка подтверждения в модалке. Смотри fragment_debug_confirm_missing.png"}

            return await _wait_for_fragment_success(page, username, stars)

        except PlaywrightTimeoutError as e:
            logger.exception("[Fragment] timeout")
            try:
                await page.screenshot(path=str(Path(__file__).resolve().parent / "fragment_debug_timeout.png"), full_page=True)
            except Exception:
                pass
            return {"ok": False, "error": f"Timeout: {e}"}
        except Exception as e:
            logger.exception("[Fragment] purchase failed")
            try:
                await page.screenshot(path=str(Path(__file__).resolve().parent / "fragment_debug_error.png"), full_page=True)
            except Exception:
                pass
            return {"ok": False, "error": str(e)}
        finally:
            await context.close()
            await browser.close()
