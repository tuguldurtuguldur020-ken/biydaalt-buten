from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from . import __version__

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PLATEWATCH_DATA_DIR", str(APP_DIR / "data")))
APP_TITLE = f"PlateWatch {__version__} • Автомашины дугаар танигч"
UB_TIME = timezone(timedelta(hours=8), "Asia/Ulaanbaatar")
DEFAULTS = {
    "model_path": "", "camera_index": 0, "camera_backend": "auto", "device": "cpu",
    "detection_confidence": 0.35, "ocr_confidence": 0.35,
    "frame_stride": 5, "cooldown_seconds": 20, "confirmation_frames": 2,
    "accent": "Цэнхэр", "save_video": False,
    "rules": {
        "mode": "weekly", "start": "08:00", "end": "20:00",
        "in_zone": True, "even_on_even_date": True,
        "weekdays": {"0": [1, 6], "1": [2, 7], "2": [3, 8], "3": [4, 9], "4": [5, 0], "5": [], "6": []},
        "holidays": [], "exempt_plates": [],
    },
}


def now_ub():
    return datetime.now(UB_TIME)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_settings(directory=DATA_DIR):
    result = deepcopy(DEFAULTS)
    path = Path(directory) / "settings.json"
    if path.exists():
        try:
            incoming = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(incoming, dict):
                raise ValueError("Тохиргоо JSON object байх ёстой.")
            rules = incoming.pop("rules", {})
            result.update({k: v for k, v in incoming.items() if k in DEFAULTS})
            if isinstance(rules, dict):
                result["rules"].update(rules)
        except (ValueError, OSError):
            pass  # Preserve damaged settings for recovery.
    return result


def save_settings(settings, directory=DATA_DIR):
    atomic_json(Path(directory) / "settings.json", settings)
