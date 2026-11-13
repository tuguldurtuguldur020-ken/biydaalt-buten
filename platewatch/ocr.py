"""Mongolian OCR for an already detected plate crop.

YOLO locates plates, so a second CRAFT/VGG text detector is unnecessary here.
EasyOCR's documented detector=False + recognize() API avoids the temporary
400+ MB VGG classifier allocation and reduces CPU/RAM usage during camera use.
"""
from pathlib import Path


def create_reader(directory, gpu=False):
    import easyocr
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return easyocr.Reader(["mn", "en"], gpu=gpu, detector=False,
                           model_storage_directory=str(directory),
                           user_network_directory=str(directory / "user_network"), verbose=False)


def text_regions(gray):
    """Find prominent text rows in a plate; suppress small country labels."""
    import cv2
    height, width = gray.shape[:2]
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if .28 * height <= h <= .94 * height and 2 <= w <= min(.30 * width, 1.25 * h) and w * h >= width * height * .001:
            boxes.append((x, y, w, h))
    rows = []
    for box in sorted(boxes, key=lambda b: b[1] + b[3] / 2):
        x, y, w, h = box
        for row in rows:
            center = sum(b[1] + b[3] / 2 for b in row) / len(row)
            if abs(center - (y + h / 2)) <= .45 * max(h, max(b[3] for b in row)):
                row.append(box)
                break
        else:
            rows.append([box])
    regions = []
    for row in rows:
        tallest = max(b[3] for b in row)
        row = [b for b in row if b[3] >= .60 * tallest]
        # The circular MNG logo between digits and letters is not plate text.
        # Keep widely separated groups separate so OCR never reads that logo.
        groups = []
        gap_limit = max(8, max(b[3] for b in row) * .45)
        for box in sorted(row):
            if groups and box[0] - max(b[0] + b[2] for b in groups[-1]) <= gap_limit:
                groups[-1].append(box)
            else:
                groups.append([box])
        for group in groups:
            if len(group) < 2:
                continue
            left, top = min(b[0] for b in group), min(b[1] for b in group)
            right, bottom = max(b[0] + b[2] for b in group), max(b[1] + b[3] for b in group)
            pad = max(3, int((bottom - top) * .08))
            regions.append([max(0, left - pad), min(width, right + pad), max(0, top - pad), min(height, bottom + pad)])
    return regions
