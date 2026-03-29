import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

STATE_PATH = Path(__file__).resolve().parent / "fragment_state.json"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("Открой Fragment и войди в аккаунт вручную.")
        await page.goto("https://fragment.com/", wait_until="domcontentloaded")

        print("\nКогда уже войдёшь в аккаунт Fragment, нажми Enter в консоли...")
        input()

        await context.storage_state(path=str(STATE_PATH))
        print(f"Сессия сохранена в {STATE_PATH}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
