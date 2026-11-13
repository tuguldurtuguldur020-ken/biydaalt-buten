"""CSV index + JSON metadata + JPEG images; no SQL or database service."""
import csv
import logging
from pathlib import Path
import threading
from uuid import uuid4
from .settings import DATA_DIR, atomic_json, now_ub

FIELDS = ["id", "detected_at", "plate", "source", "source_kind", "video_seconds", "detector_confidence", "ocr_confidence", "rule_code", "rule_label", "image_path", "crop_path", "metadata_path"]


class RecordStore:
    def __init__(self, directory=DATA_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.directory / "detections.csv"
        self.lock = threading.RLock()

    def records(self):
        with self.lock:
            if not self.csv_path.exists():
                return []
            with self.csv_path.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                records = []
                for row in reader:
                    # DictReader fills missing cells with None. Keep malformed
                    # rows out of every consumer, including history and rules.
                    if (None in row or any(row.get(field) is None for field in FIELDS)
                            or any(not row[field].strip() for field in ("id", "detected_at", "plate"))):
                        logging.warning("Skipping incomplete CSV record at %s:%s", self.csv_path, reader.line_num)
                        continue
                    records.append(row)
                return records

    def query(self, plate="", day="", restricted_only=False):
        result = self.records()
        if plate:
            result = [r for r in result if plate in r.get("plate", "")]
        if day:
            result = [r for r in result if r.get("detected_at", "").startswith(day)]
        if restricted_only:
            result = [r for r in result if r.get("rule_code") == "restricted"]
        return sorted(result, key=lambda r: r["detected_at"], reverse=True)

    def resolve(self, relative):
        return self.directory / relative

    def add(self, record, annotated_rgb, crop_rgb, rule, at=None):
        from PIL import Image
        at = at or now_ub()
        token = at.strftime("%H%M%S_%f") + "_" + uuid4().hex[:6]
        relative = Path("evidence") / at.date().isoformat()
        folder = self.directory / relative
        folder.mkdir(parents=True, exist_ok=True)
        stem = token + "_" + record["plate"]
        image_path = relative / (stem + ".jpg")
        crop_path = relative / (stem + "_plate.jpg")
        metadata_path = relative / (stem + ".json")
        Image.fromarray(annotated_rgb).save(self.resolve(image_path), quality=94)
        Image.fromarray(crop_rgb).save(self.resolve(crop_path), quality=97)
        row = {k: "" for k in FIELDS}
        row.update(record)
        row.update(id=token, detected_at=at.isoformat(timespec="milliseconds"), rule_code=rule.code, rule_label=rule.label,
                   image_path=image_path.as_posix(), crop_path=crop_path.as_posix(), metadata_path=metadata_path.as_posix())
        atomic_json(self.resolve(metadata_path), {**row, "rule": rule.as_dict(), "rule_basis": "user_configured_schedule", "time_basis": "import_processing_time" if row["source_kind"] != "camera" else "live_capture_time"})
        with self.lock:
            header = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
            with self.csv_path.open("a", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore")
                if header:
                    writer.writeheader()
                writer.writerow(row)
        return row

    def export(self, destination, records):
        destination = Path(destination).resolve()
        if destination == self.csv_path.resolve():
            raise ValueError("Экспортын файлыг үндсэн detections.csv-ээс өөр нэрээр хадгална уу.")
        with destination.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                writer.writerow({k: "'" + str(v) if str(v).startswith(("=", "+", "-", "@")) else v for k, v in record.items()})
