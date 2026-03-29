import json
import os
import time
from pathlib import Path

import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2

BASE_DIR = Path(__file__).resolve().parent
LAST_POS_FILE = BASE_DIR / "tonkeeper_confirm_last.json"

def _parse_templates():
    raw = (os.getenv("TONKEEPER_CONFIRM_TEMPLATES") or "").strip()
    if raw:
        templates = [Path(item.strip()) for item in raw.split(",") if item.strip()]
    else:
        templates = [BASE_DIR / "confirm_button.png"]

    resolved = []
    for template in templates:
        resolved.append(template if template.is_absolute() else (BASE_DIR / template))
    return resolved

def _parse_region():
    raw = (os.getenv("TONKEEPER_CONFIRM_REGION") or "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 4:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None

def _parse_position():
    raw = (os.getenv("TONKEEPER_CONFIRM_POSITION") or "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None

def _load_last_position():
    if not LAST_POS_FILE.exists():
        return None
    try:
        data = json.loads(LAST_POS_FILE.read_text(encoding="utf-8"))
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            return None
        return int(x), int(y)
    except Exception:
        return None

def _save_last_position(x: int, y: int):
    try:
        LAST_POS_FILE.write_text(json.dumps({"x": x, "y": y}), encoding="utf-8")
    except Exception:
        pass

def _confirm_confidence() -> float:
    raw = (os.getenv("TONKEEPER_CONFIRM_CONFIDENCE") or "0.85").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.85

def confirm_tonkeeper_click():
    """
    Ищет кнопку подтверждения в окне Tonkeeper и кликает по ней.
    Приоритет: шаблоны (TONKEEPER_CONFIRM_TEMPLATES) -> точка (TONKEEPER_CONFIRM_POSITION)
    -> последняя удачная позиция.
    """

    time.sleep(2)

    templates = _parse_templates()
    region = _parse_region()
    confidence = _confirm_confidence()
    last_error = None

    for template in templates:
        if not template.exists():
            last_error = f"Файл не найден: {template.name}"
            continue

        try:
            pos = pyautogui.locateCenterOnScreen(
                str(template),
                confidence=confidence,
                region=region,
                grayscale=True
            )
            if pos:
                pyautogui.click(pos.x, pos.y)
                _save_last_position(pos.x, pos.y)
                return {"ok": True, "method": f"clicked {template.name}", "x": pos.x, "y": pos.y}
        except Exception as e:
            last_error = str(e)

    fallback_pos = _parse_position() or _load_last_position()
    if fallback_pos:
        x, y = fallback_pos
        try:
            pyautogui.click(x, y)
            return {"ok": True, "method": "clicked fixed position", "x": x, "y": y}
        except Exception as e:
            last_error = str(e)

    return {
        "ok": False,
        "error": last_error or "Кнопка подтверждения не найдена. Добавьте шаблон или задайте позицию."
    }

if __name__ == "__main__":
    print(confirm_tonkeeper_click())
