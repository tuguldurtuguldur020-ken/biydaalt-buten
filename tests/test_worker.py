from copy import deepcopy
from pathlib import Path
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image

from platewatch.plates import Detection
from platewatch.settings import DEFAULTS
from platewatch.storage import RecordStore
from platewatch.worker import DetectionWorker


class FakeRecognizer:
    def __init__(self, *args, **kwargs):
        pass

    def detect(self, frame):
        return [Detection((10, 10, 180, 60), "1234УБА", .95, .92, "1234 УБА")]


class WorkerIntegrationTests(unittest.TestCase):
    def test_image_is_published_before_ai_finishes_loading(self):
        entered, resume = threading.Event(), threading.Event()
        class SlowRecognizer(FakeRecognizer):
            def __init__(self, *args, **kwargs):
                entered.set()
                resume.wait(5)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            path = Path(temp) / "preview.png"
            Image.new("RGB", (220, 100), (10, 20, 30)).save(path)
            worker = DetectionWorker(deepcopy(DEFAULTS), RecordStore(Path(temp) / "data"))
            with patch("platewatch.worker.PlateRecognizer", SlowRecognizer):
                worker.start("image", [path])
                try:
                    self.assertTrue(entered.wait(3))
                    preview = worker.frames.get_nowait()
                    self.assertEqual(tuple(preview[0, 0]), (10, 20, 30))
                    self.assertFalse(worker.store.records())
                finally:
                    resume.set()
                    worker.thread.join(6)
            self.assertEqual(len(worker.store.records()), 1)

    def test_ai_failure_keeps_selected_image_visible(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            path = Path(temp) / "preview.png"
            Image.new("RGB", (220, 100), "white").save(path)
            worker = DetectionWorker(deepcopy(DEFAULTS), RecordStore(Path(temp) / "data"))
            with patch("platewatch.worker.PlateRecognizer", side_effect=RuntimeError("model failed")):
                worker.start("image", [path])
                worker.thread.join(6)
            self.assertFalse(worker.frames.empty())
            self.assertIn("error", [kind for kind, _ in list(worker.events.queue)])
    def test_camera_capture_and_stop_release_without_real_hardware(self):
        class FakeCamera:
            def __init__(self):
                self.released = False

            def isOpened(self):
                return True

            def set(self, *args):
                return True

            def read(self):
                time.sleep(.015)
                return True, np.full((100, 220, 3), 200, np.uint8)

            def release(self):
                self.released = True

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            camera = FakeCamera()
            worker = DetectionWorker(deepcopy(DEFAULTS), RecordStore(Path(temp) / "data"))
            with patch("platewatch.worker.PlateRecognizer", FakeRecognizer), patch("cv2.VideoCapture", return_value=camera):
                worker.start("camera", 0)
                deadline = time.monotonic() + 5
                while not worker.store.records() and time.monotonic() < deadline:
                    time.sleep(.02)
                worker.stop_event.set()
                worker.thread.join(timeout=5)
            self.assertFalse(worker.alive)
            self.assertTrue(camera.released)
            self.assertEqual(len(worker.store.records()), 1)
            self.assertEqual(worker.store.records()[0]["source_kind"], "camera")

    def test_image_batch_unicode_paths_and_repeat_plate(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            paths = [root / "Монгол зураг 1.png", root / "Монгол зураг 2.png"]
            for path in paths:
                Image.fromarray(np.full((100, 220, 3), 225, np.uint8)).save(path)
            worker = DetectionWorker(deepcopy(DEFAULTS), RecordStore(root / "data"))
            with patch("platewatch.worker.PlateRecognizer", FakeRecognizer):
                worker.start("image", paths)
                worker.thread.join(timeout=10)
            self.assertFalse(worker.alive)
            self.assertEqual(len(worker.store.records()), 2)
            events = list(worker.events.queue)
            self.assertNotIn("error", [k for k, v in events])
            self.assertIn("done", [k for k, v in events])

    def test_video_sampling_confirmation_and_output_file(self):
        import cv2
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            path = root / "sample.avi"
            video = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (220, 100))
            self.assertTrue(video.isOpened())
            for _ in range(12):
                video.write(np.full((100, 220, 3), 200, np.uint8))
            video.release()
            settings = deepcopy(DEFAULTS)
            settings.update(frame_stride=2, save_video=True)
            worker = DetectionWorker(settings, RecordStore(root / "data"))
            with patch("platewatch.worker.PlateRecognizer", FakeRecognizer):
                worker.start("video", path)
                worker.thread.join(timeout=15)
            self.assertFalse(worker.alive)
            self.assertEqual(len(worker.store.records()), 1)
            self.assertEqual(float(worker.store.records()[0]["video_seconds"]), .2)
            self.assertTrue(list((root / "data" / "videos").glob("*.mp4")))
            self.assertNotIn("error", [k for k, v in list(worker.events.queue)])


if __name__ == "__main__":
    unittest.main()
