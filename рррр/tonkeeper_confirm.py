import time
from pathlib import Path

import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2

BASE_DIR = Path(__file__).resolve().parent

def confirm_tonkeeper_click():
    """
    Ищет кнопку подтверждения в окне Tonkeeper по изображению и кликает по ней.
    """

    time.sleep(2)

    templates = [
        BASE_DIR / "confirm_button.png",
    ]

    last_error = None

    for template in templates:
        if not template.exists():
            last_error = f"Файл не найден: {template.name}"
            continue

        try:
            pos = pyautogui.locateCenterOnScreen(str(template), confidence=0.85)
            if pos:
                pyautogui.click(pos.x, pos.y)
                return {"ok": True, "method": f"clicked {template.name}", "x": pos.x, "y": pos.y}
        except Exception as e:
            last_error = str(e)

    return {"ok": False, "error": last_error or "Кнопка подтверждения не найдена на экране"}

if __name__ == "__main__":
    print(confirm_tonkeeper_click())
