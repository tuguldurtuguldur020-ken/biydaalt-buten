"""Position-aware OCR cleanup for common Mongolian 4 digit + 3 letter plates."""
from dataclasses import dataclass
import re

CYRILLIC = "АБВГДЕЁЖЗИЙКЛМНОӨПРСТУҮФХЦЧШЩЪЫЬЭЮЯ"
ALLOWLIST = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" + CYRILLIC
LATIN_TO_CYR = str.maketrans({"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У"})
DIGIT_CONFUSIONS = str.maketrans({"O": "0", "О": "0", "I": "1", "І": "1", "З": "3"})


def clean_text(text):
    return re.sub(r"[^0-9A-Z" + CYRILLIC + r"]", "", str(text).upper())


def normalize_plate(text):
    value = clean_text(text)
    if len(value) != 7:
        return ""
    digits = value[:4].translate(DIGIT_CONFUSIONS)
    letters = value[4:].translate(LATIN_TO_CYR)
    if re.fullmatch(r"[0-9]{4}", digits) and re.fullmatch("[" + CYRILLIC + "]{3}", letters):
        return digits + letters
    return ""


def display_plate(text):
    return text[:4] + " " + text[4:] if len(text) == 7 else text


def select_ocr_candidate(items):
    """Join separate OCR boxes in reading order; preserve conservative confidence."""
    if not items:
        return "", 0.0, ""
    ordered = sorted(items, key=lambda item: (sum(p[1] for p in item[0]) / 4, min(p[0] for p in item[0])))
    heights = [max(p[1] for p in i[0]) - min(p[1] for p in i[0]) for i in items]
    centers = [sum(p[1] for p in i[0]) / 4 for i in items]
    if max(centers) - min(centers) <= max(heights) * 0.65:
        ordered = sorted(items, key=lambda item: min(p[0] for p in item[0]))
    candidates = []
    for start in range(len(ordered)):
        for end in range(start + 1, min(len(ordered), start + 4) + 1):
            group = ordered[start:end]
            raw = "".join(str(item[1]) for item in group)
            plate = normalize_plate(raw)
            if plate:
                candidates.append((plate, min(float(item[2]) for item in group), raw))
    return max(candidates, key=lambda value: value[1]) if candidates else ("", 0.0, " ".join(str(i[1]) for i in ordered))


@dataclass
class Detection:
    bbox: tuple
    plate: str = ""
    detector_confidence: float = 0.0
    ocr_confidence: float = 0.0
    raw_text: str = ""


class TemporalGate:
    """Confirm repeated readings in a short window; suppress duplicate records."""
    def __init__(self, confirmations=2, cooldown=20, window=8):
        self.confirmations = confirmations
        self.cooldown = cooldown
        self.window = window
        self.hits = {}
        self.saved = {}

    def ready(self, plate, clock, single_image=False):
        if not plate:
            return False
        if single_image:
            return True
        if clock - self.saved.get(plate, float("-inf")) < self.cooldown:
            return False
        hits = [t for t in self.hits.get(plate, []) if clock - t <= self.window]
        hits.append(clock)
        self.hits[plate] = hits[-self.confirmations:]
        return len(hits) >= self.confirmations

    def mark_saved(self, plate, clock):
        self.saved[plate] = clock
        self.hits.pop(plate, None)
        if len(self.saved) > 5000:
            self.saved = {p: t for p, t in self.saved.items() if clock - t < self.cooldown}
        if len(self.hits) > 1000:
            self.hits = {p: times for p, times in self.hits.items() if times and clock - times[-1] <= self.window}
