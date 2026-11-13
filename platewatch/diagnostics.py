"""Offline verification for the Python and packaged executable versions."""
from dataclasses import asdict
from pathlib import Path
import traceback
from .settings import DATA_DIR, atomic_json, load_settings, now_ub


def verify_image(source, report_path=None):
    report_path = Path(report_path) if report_path else DATA_DIR / "verification.json"
    report = {"checked_at": now_ub().isoformat(), "source": str(source), "ok": False}
    try:
        import cv2
        import numpy as np
        from PIL import Image
        from .recognition import PlateRecognizer, annotate
        settings = load_settings()
        frame = cv2.imdecode(np.fromfile(str(source), dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Image could not be decoded")
        recognizer = PlateRecognizer(settings)
        found = recognizer.detect(frame)
        report.update(ok=any(d.plate for d in found), detections=[asdict(d) for d in found])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(annotate(frame, found, settings["rules"])).save(report_path.with_suffix(".jpg"))
    except Exception:
        report["error"] = traceback.format_exc()
    atomic_json(report_path, report)
    return 0 if report["ok"] else 1
