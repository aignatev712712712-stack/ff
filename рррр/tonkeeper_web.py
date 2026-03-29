import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

from config import TONKEEPER_STATE_PATH, TONKEEPER_WEB_URL

STATE_DIR = Path(TONKEEPER_STATE_PATH)
STATE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = STATE_DIR / "state.json"

async def login_and_save():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("Открой Tonkeeper Web и залогинься вручную.")
        await page.goto(TONKEEPER_WEB_URL, wait_until="domcontentloaded")

        print("Когда войдёшь в Tonkeeper Web, нажми Enter в консоли...")
        input()

        await context.storage_state(path=str(STATE_FILE))
        print(f"Сессия Tonkeeper Web сохранена в {STATE_FILE}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(login_and_save())
