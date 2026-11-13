"""Exercise the actual Tk button callbacks, including source changes and failures."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from platewatch.gui import PlateWatchApp
from platewatch.plates import Detection
from platewatch.rules import evaluate
from platewatch.settings import DEFAULTS, UB_TIME
from platewatch.storage import RecordStore


class Recognizer:
    def __init__(self, *args, **kwargs):
        pass
    def detect(self, frame):
        return [Detection((10, 10, 140, 60), "1234УБА", .95, .9, "1234УБА")]


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp.name)
        self.store = RecordStore(self.root / "data")
        self.path = self.root / "Монгол зураг.png"
        Image.new("RGB", (220, 100), (15, 30, 45)).save(self.path)
        self.patches = [patch("platewatch.gui.RecordStore", return_value=self.store),
                        patch("platewatch.gui.load_settings", return_value=deepcopy(DEFAULTS)),
                        patch("platewatch.gui.save_settings"),
                        patch("platewatch.worker.PlateRecognizer", Recognizer)]
        for mock in self.patches:
            mock.start()
        self.app = PlateWatchApp()
        self.app.withdraw()

    def tearDown(self):
        self.app.worker.stop_event.set()
        self.app.worker.pause_event.clear()
        if self.app.worker.thread:
            self.app.worker.thread.join(5)
        self.app.close()
        for mock in reversed(self.patches):
            mock.stop()
        self.temp.cleanup()

    def pump(self, condition, timeout=7):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.update()
            if condition():
                return
            time.sleep(.02)
        self.fail("GUI condition timed out: " + self.app.status_text.get())

    def test_import_button_runs_picker_and_displays_selected_image(self):
        with patch("platewatch.gui.filedialog.askopenfilenames", return_value=(str(self.path),)) as picker:
            self.app.image_button.invoke()
            picker.assert_called_once()
        self.pump(lambda: bool(self.app.history_table.get_children()))
        self.assertIn("1234", self.app.plate_label.cget("text"))
        self.assertEqual(self.app.last_rgb.shape[:2], (100, 220))
        self.assertEqual(self.store.records()[0]["source"], str(self.path))

    def test_main_preview_image_button_imports_photo(self):
        with patch("platewatch.gui.filedialog.askopenfilenames", return_value=(str(self.path),)) as picker:
            self.app.main_image_button.invoke()
            picker.assert_called_once()
        self.pump(lambda: bool(self.app.history_table.get_children()))
        self.assertIn("1234", self.app.plate_label.cget("text"))

    def test_imported_photo_retries_preview_after_memory_error_without_new_frame(self):
        render = self.app._render_preview
        failures = []
        def fail_once():
            if self.app.last_rgb is not None and not failures:
                failures.append(True)
                raise MemoryError("Simulated preview allocation failure")
            render()
        with patch.object(self.app, "_render_preview", side_effect=fail_once):
            with patch("platewatch.gui.filedialog.askopenfilenames", return_value=(str(self.path),)):
                self.app.main_image_button.invoke()
            self.pump(lambda: self.app.preview_displayed and not self.app.worker.alive)
        self.assertEqual(len(failures), 1)
        self.assertIsNotNone(self.app.preview_photo)
        self.assertFalse(self.app._preview_failed)
        self.assertFalse(self.app._preview_dirty)
        self.assertTrue(self.app.worker.frames.empty())
        self.assertTrue(self.app.history_table.get_children())

    def test_poll_reschedules_after_unexpected_callback_failure(self):
        poll = self.app._poll_once
        attempts = []
        def fail_once():
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError("Simulated GUI callback failure")
            poll()
        with patch.object(self.app, "_poll_once", side_effect=fail_once):
            self.app.start_source("image", [str(self.path)])
            self.pump(lambda: self.app.preview_displayed and bool(self.app.history_table.get_children()))
        self.assertGreaterEqual(len(attempts), 2)

    def test_camera_reuses_tk_image_and_import_still_works_after_render_failure(self):
        class Camera:
            released = False
            def isOpened(self):
                return True
            def read(self):
                time.sleep(.015)
                return True, np.full((90, 160, 3), 200, np.uint8)
            def release(self):
                self.released = True
        camera = Camera()
        with patch("cv2.VideoCapture", return_value=camera):
            self.app.camera_button.invoke()
            self.pump(lambda: self.app.preview_displayed)
            photo = self.app.preview_photo
            with patch.object(photo, "paste", wraps=photo.paste) as paste:
                self.pump(lambda: paste.call_count >= 3)
            self.assertIs(self.app.preview_photo, photo)
            with patch.object(self.app, "_render_preview", side_effect=MemoryError("Camera allocation failed")):
                self.app._preview_retry_at = 0
                self.assertFalse(self.app.redraw_preview())
            self.pump(lambda: not self.app._preview_failed)
            with patch("platewatch.gui.filedialog.askopenfilenames", return_value=(str(self.path),)):
                self.app.main_image_button.invoke()
            self.pump(lambda: self.app.active_kind == "image" and self.app.preview_displayed
                      and any(r["source_kind"] == "image" for r in self.store.records()))
        self.assertTrue(camera.released)
        self.assertEqual(self.app.last_rgb.shape[:2], (100, 220))

    def test_large_photo_preview_is_bounded_and_keeps_original_frame(self):
        frame = np.full((2100, 3200, 3), 150, np.uint8)
        self.app.worker.publish(frame)
        self.pump(lambda: self.app.preview_displayed)
        self.assertIs(self.app.last_rgb, frame)
        self.assertLessEqual(max(self.app.preview_photo.width(), self.app.preview_photo.height()), 960)

    def test_1113_shows_wednesday_separately_from_selected_friday(self):
        self.app.nav["rules"].invoke()
        self.app.rule_plate.set("1113")
        self.assertIn("Лхагва", self.app.rule_result_label.cget("text"))
        self.assertNotIn("Баасан", self.app.rule_result_label.cget("text"))
        self.app.rule_date.set("2026-11-13")
        self.app.rule_time.set("12:00")
        self.app.check_rule()
        self.assertIn("Лхагва", self.app.rule_result_label.cget("text"))
        self.assertIn("Баасан", self.app.rule_date_result.cget("text"))
        self.assertEqual(self.app.last_rule_result.code, "allowed")
        self.app.rule_date.set("2026-11-11")
        self.app.check_rule()
        self.assertEqual(self.app.last_rule_result.code, "restricted")

    def test_incomplete_csv_row_does_not_break_history_or_rule_lookup(self):
        at = datetime(2026, 11, 13, 11, 39, tzinfo=UB_TIME)
        frame = np.full((100, 220, 3), 200, np.uint8)
        self.store.add({"plate": "6775УБА", "source": str(self.path), "source_kind": "image",
                        "ocr_confidence": .9, "detector_confidence": .95}, frame, frame[:30],
                       evaluate("6775УБА", self.app.settings["rules"], at), at)
        with self.store.csv_path.open("a", encoding="utf-8", newline="") as file:
            file.write("log\n")

        self.app.show_page("history")
        self.app.clear_filters()
        self.assertEqual(len(self.app.history_table.get_children()), 1)
        self.app.show_page("rules")
        self.app.rule_plate.set("6775")
        self.app.rule_date.set("2026-11-13")
        self.app.rule_time.set("11:39")
        self.app.check_rule()
        self.assertEqual(self.app.last_rule_result.code, "restricted")
        self.assertIn("1 бүртгэл", self.app.rule_seen_label.cget("text"))

    def test_import_cancellation_does_not_start_inference(self):
        with patch("platewatch.gui.filedialog.askopenfilenames", return_value=()):
            self.app.image_button.invoke()
        self.assertFalse(self.app.worker.alive)
        self.assertIsNone(self.app.pending_source)

    def test_video_import_button_processes_selected_file(self):
        import cv2
        path = self.root / "Видео бичлэг.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (220, 100))
        self.assertTrue(writer.isOpened())
        for _ in range(12):
            writer.write(np.full((100, 220, 3), 150, np.uint8))
        writer.release()
        with patch("platewatch.gui.filedialog.askopenfilename", return_value=str(path)) as picker:
            self.app.video_button.invoke()
            picker.assert_called_once()
        self.pump(lambda: any(r["source_kind"] == "video" for r in self.store.records()))
        self.assertEqual(self.app.active_kind, "video")

    def test_file_path_import_and_error_feedback(self):
        self.app.import_path_var.set(str(self.path))
        self.app.open_import_path()
        self.pump(lambda: bool(self.store.records()))
        self.app.import_path_var.set(str(self.root / "missing.png"))
        self.app.open_import_path()
        self.assertIn("Файл олдсонгүй", self.app.last_error)
        self.app.nav["rules"].invoke()
        self.assertEqual(self.app.current_page, "rules")

    def test_camera_to_image_switch_releases_device_and_imports(self):
        class Camera:
            released = False
            def isOpened(self):
                return True
            def read(self):
                time.sleep(.015)
                return True, np.full((90, 160, 3), 200, np.uint8)
            def release(self):
                self.released = True
        camera = Camera()
        with patch("cv2.VideoCapture", return_value=camera):
            self.app.camera_button.invoke()
            self.pump(lambda: self.app.last_rgb is not None and bool(self.store.records()))
            with patch("platewatch.gui.filedialog.askopenfilenames", return_value=(str(self.path),)):
                self.app.image_button.invoke()
            self.pump(lambda: any(r["source_kind"] == "image" for r in self.store.records()))
        self.pump(lambda: self.app.last_rgb is not None and self.app.last_rgb.shape[:2] == (100, 220))
        self.assertTrue(camera.released)
        self.assertIsNone(self.app.pending_source)

    def test_image_stays_visible_and_gui_remains_responsive_on_ai_error(self):
        with patch("platewatch.worker.PlateRecognizer", side_effect=RuntimeError("AI test failure")):
            with patch("platewatch.gui.filedialog.askopenfilenames", return_value=(str(self.path),)):
                self.app.image_button.invoke()
            self.pump(lambda: bool(self.app.last_error))
        self.assertIsNotNone(self.app.last_rgb)
        self.assertIn("AI test failure", self.app.last_error)
        self.app.nav["settings"].invoke()
        self.assertEqual(self.app.current_page, "settings")
