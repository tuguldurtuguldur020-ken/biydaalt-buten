"""Capture starts immediately; AI runs independently of the Tk event loop."""
from copy import deepcopy
import logging
from pathlib import Path
import queue
import threading
import time
from .media import open_camera, read_image
from .plates import TemporalGate
from .recognition import PlateRecognizer, annotate
from .rules import evaluate
from .settings import now_ub


class DetectionWorker:
    def __init__(self, settings, store):
        self.settings = deepcopy(settings)
        self.store = store
        self.events = queue.Queue()
        self.frames = queue.Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.camera_ready = threading.Event()
        self.thread = None
        self.recognizer = None
        self.latest = None
        self.latest_annotations = ([], 0)
        self.actual_camera_index = None
        self.latest_lock = threading.Lock()
        self.processed = 0
        self.saved_count = 0

    @property
    def alive(self):
        return bool(self.thread and self.thread.is_alive())

    def emit(self, kind, value):
        self.events.put((kind, value))

    def publish(self, frame):
        try:
            self.frames.put_nowait(frame)
        except queue.Full:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self.frames.put_nowait(frame)
            except queue.Full:
                pass

    def start(self, kind, source):
        if self.alive:
            return False
        self.stop_event.clear()
        self.pause_event.clear()
        self.camera_ready.clear()
        while not self.frames.empty():
            try:
                self.frames.get_nowait()
            except queue.Empty:
                break
        self.latest = None
        self.latest_annotations = ([], 0)
        self.processed = self.saved_count = 0
        self.thread = threading.Thread(target=self.run, args=(kind, source), daemon=True, name="platewatch-inference")
        self.thread.start()
        return True

    def wait_if_paused(self):
        while self.pause_event.is_set() and not self.stop_event.wait(.08):
            pass
        return self.stop_event.is_set()

    def load_recognizer(self):
        if self.stop_event.is_set():
            raise InterruptedError()
        if self.recognizer is None:
            self.recognizer = PlateRecognizer(self.settings, lambda text: self.emit("status", text), self.stop_event)
        if self.stop_event.is_set():
            raise InterruptedError()

    def run(self, kind, source):
        logging.info("Source start: %s %s", kind, source)
        self.gate = TemporalGate(int(self.settings["confirmation_frames"]), float(self.settings["cooldown_seconds"]))
        try:
            if kind == "image":
                self.run_images(source)
            elif kind == "camera":
                self.run_camera(source)
            elif kind == "video":
                self.run_video(source)
            else:
                raise RuntimeError(f"Эх үүсвэрийн төрөл буруу: {kind}")
            if not self.stop_event.is_set():
                text = f"Дууслаа • {self.processed} кадр шалгаж, {self.saved_count} дугаар хадгаллаа."
                if not self.saved_count:
                    text += " Дугаар уншигдаагүй бол тод, ойроос авсан зураг сонгоно уу."
                self.emit("status", text)
        except InterruptedError:
            pass
        except Exception as exc:
            logging.exception("Detection failed: %s", source)
            self.emit("error", str(exc))
        finally:
            self.stop_event.set()
            self.emit("done", None)
            logging.info("Source finished: %s; saved=%s", kind, self.saved_count)

    def run_images(self, source):
        import cv2
        paths = [source] if isinstance(source, (str, Path)) else list(source)
        if not paths:
            return
        for index, path in enumerate(paths):
            if self.wait_if_paused():
                return
            frame = read_image(path)
            # A selected picture is visible even if model loading is slow or fails.
            self.publish(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self.emit("source_ready", {"kind": "image", "source": str(path)})
            self.emit("status", f"Зураг нээгдлээ • {Path(path).name} • AI бэлтгэж байна...")
            self.load_recognizer()
            self.emit("ready", "image")
            self.process(frame, "image", str(path), 0, single_image=True)
            self.emit("progress", (index + 1) / len(paths))

    def run_camera(self, index):
        camera_thread = threading.Thread(target=self.capture_camera, args=(index,), daemon=True, name="platewatch-camera")
        camera_thread.start()
        try:
            while not self.camera_ready.wait(.05):
                if self.stop_event.is_set() or not camera_thread.is_alive():
                    return
            if self.stop_event.is_set():
                return
            # Capture is already publishing frames while the heavy models load.
            self.load_recognizer()
            self.emit("ready", "camera")
            seen = -1
            while not self.stop_event.wait(.02):
                if self.wait_if_paused():
                    return
                with self.latest_lock:
                    sample = self.latest
                if sample is None or sample[0] == seen:
                    continue
                seen, frame, captured_at = sample
                self.process(frame, "camera", f"Камер {self.actual_camera_index}", 0, at=captured_at)
        finally:
            self.stop_event.set()
            camera_thread.join(timeout=3)

    def capture_camera(self, index):
        import cv2
        capture = None
        try:
            capture, frame, backend, actual_index = open_camera(index, self.settings.get("camera_backend", "auto"),
                                                  lambda text: self.emit("status", text), self.stop_event)
            self.actual_camera_index = actual_index
            self.emit("source_ready", {"kind": "camera", "source": str(actual_index), "backend": backend, "shape": list(frame.shape)})
            failures = 0
            number = 0
            while not self.stop_event.is_set():
                if self.wait_if_paused():
                    break
                number += 1
                with self.latest_lock:
                    self.latest = (number, frame, now_ub())
                self.publish(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                self.camera_ready.set()
                ok, next_frame = capture.read()
                if not ok or next_frame is None or not next_frame.size:
                    failures += 1
                    if failures >= 10:
                        raise RuntimeError("Камерын дүрс тасарлаа. Камераа дахин эхлүүлнэ үү.")
                    self.stop_event.wait(.1)
                    continue
                failures = 0
                frame = next_frame
        except InterruptedError:
            pass
        except Exception as exc:
            logging.exception("Camera failed")
            self.emit("error", str(exc))
            self.stop_event.set()
        finally:
            if capture is not None:
                capture.release()
            self.camera_ready.set()

    def run_video(self, source):
        import cv2
        capture = cv2.VideoCapture(str(source))
        recorder = None
        try:
            ok, frame = capture.read() if capture.isOpened() else (False, None)
            if not ok or frame is None:
                raise RuntimeError("Видео нээгдсэнгүй. MP4 (H.264), AVI эсвэл MKV файл сонгоно уу.")
            self.publish(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self.emit("source_ready", {"kind": "video", "source": str(source)})
            self.load_recognizer()
            self.emit("ready", "video")
            fps = capture.get(cv2.CAP_PROP_FPS)
            fps = fps if 1 <= fps <= 240 else 25.0
            total = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
            stride = int(self.settings["frame_stride"])
            if self.settings.get("save_video"):
                folder = self.store.directory / "videos"
                folder.mkdir(exist_ok=True)
                path = folder / (now_ub().strftime("%Y%m%d_%H%M%S_%f") + ".mp4")
                recorder = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (frame.shape[1], frame.shape[0]))
                if not recorder.isOpened():
                    raise RuntimeError("Видео хадгалах codec ажилласангүй. Тохиргооноос видео хадгалахыг унтраана уу.")
            index = 0
            detections = []
            while not self.stop_event.is_set():
                if self.wait_if_paused():
                    return
                started = time.monotonic()
                if index % stride == 0:
                    detections, rgb = self.process(frame, "video", str(source), index / fps)
                else:
                    rgb = annotate(frame, detections, self.settings["rules"])
                    self.publish(rgb)
                if recorder:
                    recorder.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                index += 1
                self.emit("progress", min(1.0, index / total))
                self.stop_event.wait(max(0, 1 / fps - (time.monotonic() - started)))
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
        finally:
            capture.release()
            if recorder:
                recorder.release()

    def process(self, frame, kind, source, video_seconds, single_image=False, at=None):
        import cv2
        started = time.monotonic()
        at = at or now_ub()
        detections = self.recognizer.detect(frame)
        if self.stop_event.is_set():
            return detections, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.processed += 1
        if kind == "camera":
            # Let the GUI draw recent boxes over the newest camera frame.
            self.latest_annotations = (detections, time.monotonic())
            self.emit("overlay", (detections, time.monotonic()))
        rgb = annotate(frame, detections, self.settings["rules"], at)
        clock = video_seconds if kind == "video" else time.monotonic()
        seen = set()
        for detection in detections:
            plate = detection.plate
            if not plate or plate in seen:
                continue
            seen.add(plate)
            rule = evaluate(plate, self.settings["rules"], at)
            self.emit("detection", (detection, rule))
            if not self.gate.ready(plate, clock, single_image=single_image):
                continue
            x1, y1, x2, y2 = detection.bbox
            crop = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
            record = self.store.add({"plate": plate, "source": source, "source_kind": kind,
                                     "video_seconds": round(video_seconds, 3) if kind == "video" else "",
                                     "raw_ocr_text": detection.raw_text, "bbox": list(detection.bbox),
                                     "method": getattr(detection, "method", "yolo_ocr"),
                                     "detector_confidence": round(detection.detector_confidence, 4),
                                     "ocr_confidence": round(detection.ocr_confidence, 4)}, rgb, crop, rule, at)
            self.gate.mark_saved(plate, clock)
            self.saved_count += 1
            self.emit("record", record)
        elapsed = time.monotonic() - started
        self.emit("metrics", (len(detections), round(elapsed * 1000), round(1 / max(.001, elapsed), 1)))
        if kind != "camera":
            self.publish(rgb)
        return detections, rgb
