"""YOLO license-plate localisation and Mongolian EasyOCR recognition."""
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import threading
import urllib.request
from .ocr import create_reader, text_regions
from .plates import ALLOWLIST, Detection, display_plate, select_ocr_candidate
from .rules import evaluate
from .settings import APP_DIR, DATA_DIR, now_ub

MODEL_REVISION = "83c98fbe7412fe8b3950adb5637cfd08b0f04809"
MODEL_URL = f"https://huggingface.co/Koushim/yolov8-license-plate-detection/resolve/{MODEL_REVISION}/best.pt"
MODEL_SHA256 = "2d95861825bb4184404344c9cf809f40fd31dba785fe54e8ba5b9a3583789822"


def ensure_detector(settings, report=lambda text: None, cancel=None):
    if settings.get("model_path"):
        path = Path(settings["model_path"])
        if not path.is_file():
            raise RuntimeError("Сонгосон YOLO загвар олдсонгүй. Тохиргооноос .pt загвараа дахин сонгоно уу.")
        return path
    bundled = APP_DIR / "models" / "plate_detector.pt"
    target = bundled if bundled.exists() else DATA_DIR / "models" / "plate_detector.pt"
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == MODEL_SHA256:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".download")
    report("Дугаар илрүүлэх загвар татаж байна (6.25 MB)...")
    try:
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "PlateWatch/2.0"})
        with urllib.request.urlopen(request, timeout=30) as response, part.open("wb") as file:
            while True:
                if cancel and cancel.is_set():
                    raise InterruptedError("Таталтыг зогсоолоо.")
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                file.write(chunk)
        if hashlib.sha256(part.read_bytes()).hexdigest() != MODEL_SHA256:
            raise RuntimeError("Загварын SHA-256 тохирсонгүй. Дахин татна уу.")
        part.replace(target)
    except Exception as exc:
        part.unlink(missing_ok=True)
        if isinstance(exc, InterruptedError):
            raise
        raise RuntimeError("YOLO загвар татаж чадсангүй. Интернэтээ шалгах эсвэл Тохиргооноос өөрийн .pt загварыг сонгоно уу.\n" + str(exc)) from exc
    return target


@lru_cache(maxsize=8)
def overlay_font(size):
    from PIL import ImageFont
    for name in [str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeuib.ttf"), "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def annotate(frame, detections, rules, at=None):
    """Pillow renders Cyrillic labels correctly (cv2.putText cannot). Returns RGB."""
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font_size = max(16, min(28, image.width // 45))
    font = overlay_font(font_size)
    for detection in detections:
        x1, y1, x2, y2 = detection.bbox
        rule = evaluate(detection.plate, rules, at)
        color = "#fb7185" if rule.restricted_now else "#33dbc4" if detection.plate else "#fbbf24"
        draw.rectangle((x1, y1, x2, y2), outline=color, width=max(2, image.width // 500))
        label = f"{display_plate(detection.plate)}  {detection.ocr_confidence:.0%}" if detection.plate else "Дугаар • уншиж байна"
        if rule.restricted_now:
            label += " • ХЯЗГААРЛАЛТТАЙ"
        box = draw.textbbox((0, 0), label, font=font)
        width, height = box[2] + 14, font_size + 12
        top = max(0, y1 - height)
        left = min(x1, max(0, image.width - width))
        draw.rounded_rectangle((left, top, left + width, top + height), radius=4, fill=color)
        draw.text((left + 7, top + 3), label, font=font, fill="#09131f")
    return np.asarray(image)


class PlateRecognizer:
    def __init__(self, settings, report=lambda text: None, cancel=None):
        model_path = ensure_detector(settings, report, cancel)
        report("YOLO загвар ачаалж байна...")
        os.environ.setdefault("YOLO_CONFIG_DIR", str(DATA_DIR / "ultralytics"))
        os.environ.setdefault("YOLO_AUTOINSTALL", "false")
        try:
            import torch
            from ultralytics import YOLO
            import easyocr
        except (ImportError, OSError) as exc:
            raise RuntimeError("AI сан ачаалж чадсангүй. run.bat-аа дахин ажиллуулна уу.\nWindows DLL хориглосон бол Windows Security / Application Control тохиргоог админтай шалгана уу.\n" + str(exc)) from exc
        self.settings = settings
        torch.set_num_threads(max(1, min(2, os.cpu_count() or 2)))
        self.device = "0" if settings.get("device") == "auto" and torch.cuda.is_available() else "cpu"
        self.model = YOLO(str(model_path), task="detect")
        names = list(self.model.names.values())
        self.class_ids = [i for i, name in self.model.names.items() if "plate" in name.lower() or "licen" in name.lower() or "дугаар" in name.lower()]
        if not self.class_ids and len(names) == 1:
            self.class_ids = [0]
        if not self.class_ids:
            raise RuntimeError("Энэ YOLO загвар дугаарын class агуулаагүй. License plate илрүүлэхээр сургасан .pt загвар сонгоно уу.")
        report("Монгол OCR ачаалж байна. Анх удаа жин татах тул интернэт хэрэгтэй...")
        cache = DATA_DIR / "models" / "ocr"
        cache.mkdir(parents=True, exist_ok=True)
        self.reader = create_reader(cache, gpu=self.device != "cpu")
        report("YOLO + Монгол OCR бэлэн")

    def read_crop(self, crop):
        import cv2
        height, width = crop.shape[:2]
        if not height or not width:
            return "", 0.0, ""
        scale = min(4.0, max(1.0, 100 / height))
        resized = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        variants = [gray, cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)]
        best = ("", 0.0, "")
        for variant in variants:
            regions = text_regions(variant)
            full_plate = [[0, variant.shape[1], 0, variant.shape[0]]]
            for boxes in ([regions, full_plate] if regions else [full_plate]):
                items = self.reader.recognize(variant, horizontal_list=boxes, free_list=[], detail=1,
                                               paragraph=False, allowlist=ALLOWLIST, workers=0, batch_size=1)
                candidate = select_ocr_candidate(items)
                if candidate[1] > best[1] or (not best[0] and candidate[2]):
                    best = candidate
                if best[0] and best[1] >= .8:
                    break
            if best[0] and best[1] >= 0.8:
                break
        return best

    def detect(self, frame):
        result = self.model.predict(frame, conf=float(self.settings["detection_confidence"]),
                                    classes=self.class_ids, device=self.device, imgsz=640, max_det=15, verbose=False)[0]
        found = []
        if result.boxes is None:
            return found
        h, w = frame.shape[:2]
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            pad_x, pad_y = max(2, int((x2 - x1) * .04)), max(2, int((y2 - y1) * .08))
            x1, y1, x2, y2 = max(0, x1 - pad_x), max(0, y1 - pad_y), min(w, x2 + pad_x), min(h, y2 + pad_y)
            if x2 <= x1 or y2 <= y1:
                continue
            plate, confidence, raw = self.read_crop(frame[y1:y2, x1:x2])
            # A generic detector sometimes boxes only the four digits on a
            # Mongolian plate. Retry a wider region to include the three letters.
            if not plate and x2 - x1 < 4.5 * (y2 - y1):
                target_width = min(w, int((y2 - y1) * 5.4))
                left = max(0, min(w - target_width, int((x1 + x2 - target_width) / 2)))
                right = left + target_width
                if right - left > x2 - x1:
                    wider = self.read_crop(frame[y1:y2, left:right])
                    if wider[0]:
                        plate, confidence, raw = wider
                        x1, x2 = left, right
            if confidence < float(self.settings["ocr_confidence"]):
                plate = ""
            found.append(Detection((x1, y1, x2, y2), plate, float(box.conf[0]), confidence, raw))
        return found
