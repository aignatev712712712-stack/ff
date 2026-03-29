import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

# Путь к распакованной папке расширения Tonkeeper
# Укажите реальный путь на вашей машине или через переменную окружения TONKEEPER_EXT_DIR
EXT_DIR = Path(os.environ.get("TONKEEPER_EXT_DIR", "C:/path/to/tonkeeper_unpacked"))

# Папка профиля, в которую нужно загрузить расширение (можно сделать той же, что и для Fragment)
PROFILE_DIR = Path(__file__).resolve().parent / "tonkeeper_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# Куда сохранить state (опционально)
STATE_FILE = PROFILE_DIR / "tonkeeper_state.json"

async def main():
    if not EXT_DIR.exists():
        print(f"Extension folder not found: {EXT_DIR}")
        return

    async with async_playwright() as p:
        # Запускаем persistent context — расширения работают только в persistent context и только в headed режиме
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=[
                f"--disable-extensions-except={EXT_DIR}",
                f"--load-extension={EXT_DIR}",
                "--start-maximized",
            ],
        )

        # Даем время открыть браузер и расширение; откройте popup расширения вручную или откройте его внутреннюю страницу
        print("Браузер запущен с загруженным расширением.")
        print("Откройте расширение Tonkeeper (иконка в тулбаре), настройте/войдите и привяжите кошелёк.")
        print("Когда закончите, нажмите Enter в этой консоли.")
        input()

        # Можно попытаться сохранить storage_state, но расширения могут иметь собственные хранилища.
        try:
            await context.storage_state(path=str(STATE_FILE))
            print(f"Storage saved to {STATE_FILE}")
        except Exception as e:
            print(f"Не удалось сохранить storage_state: {e}")

        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
