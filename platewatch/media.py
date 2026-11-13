"""Open local images and camera streams without depending on AI startup."""
from pathlib import Path
import sys

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".jfif", ".tif", ".tiff", ".gif")
VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v", ".webm")


def read_image(path):
    """Pillow handles Unicode filenames, EXIF orientation, TIFF and GIF frames."""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps, UnidentifiedImageError
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"Зургийн файл олдсонгүй: {path}")
    try:
        with Image.open(path) as original:
            rgb = np.asarray(ImageOps.exif_transpose(original).convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise RuntimeError(f"Зураг нээж чадсангүй: {path.name}. JPG, PNG, WEBP, BMP, TIFF эсвэл GIF файл сонгоно уу.\n{exc}") from exc


def open_camera(index="auto", backend="auto", report=lambda text: None, cancel=None):
    """Find a working camera, including when a stale/manual index is unavailable."""
    import cv2
    choices = [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF), ("AUTO", cv2.CAP_ANY)] if sys.platform == "win32" else [("AUTO", cv2.CAP_ANY)]
    if backend != "auto":
        choices.sort(key=lambda item: item[0].lower() != backend.lower())
    requested = None if index is None or str(index).lower() in ("auto", "авто") else int(index)
    indices = list(dict.fromkeys(([requested] if requested is not None else []) + [0, 1, 2, 3]))
    for candidate in indices:
        for name, api in choices:
            if cancel and cancel.is_set():
                raise InterruptedError()
            report(f"Камер хайж байна • төхөөрөмж {candidate} • {name}")
            capture = cv2.VideoCapture(candidate, api)
            if capture.isOpened():
                for _ in range(3):
                    if cancel and cancel.is_set():
                        capture.release()
                        raise InterruptedError()
                    ok, frame = capture.read()
                    if ok and frame is not None and frame.size:
                        return capture, frame, name, candidate
            capture.release()
    raise RuntimeError("Ажиллах камер олдсонгүй.\nКамер ашиглаж буй бусад програмыг хааж, Windows Camera permission болон камерын холболтоо шалгана уу.")
