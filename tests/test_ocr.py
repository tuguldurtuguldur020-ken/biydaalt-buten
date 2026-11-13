from unittest.mock import patch, MagicMock
import unittest
import numpy as np
import cv2
from copy import deepcopy
from types import SimpleNamespace
from platewatch.settings import DEFAULTS
from platewatch.ocr import text_regions
from platewatch.plates import select_ocr_candidate


class OcrCropTests(unittest.TestCase):
    def test_partial_digit_box_is_widened_to_include_letters(self):
        from platewatch.recognition import PlateRecognizer
        recognizer = PlateRecognizer.__new__(PlateRecognizer)
        recognizer.settings = deepcopy(DEFAULTS)
        recognizer.class_ids = [0]
        recognizer.device = "cpu"
        box = SimpleNamespace(xyxy=np.array([[0, 235, 452, 391]]), conf=[.4])
        recognizer.model = MagicMock()
        recognizer.model.predict.return_value = [SimpleNamespace(boxes=[box])]
        recognizer.read_crop = lambda crop: ("9638УЕН", .98, "9638УЕН") if crop.shape[1] == 720 else ("", 0, "9638")
        result = recognizer.detect(np.full((720, 720, 3), 200, np.uint8))
        self.assertEqual(result[0].plate, "9638УЕН")
        self.assertEqual(result[0].bbox[2], 720)
    def test_prominent_text_region_excludes_small_country_label(self):
        image = np.full((120, 480), 255, np.uint8)
        cv2.putText(image, "MNG", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, .4, 0, 1)
        cv2.putText(image, "1234 ABA", (65, 95), cv2.FONT_HERSHEY_SIMPLEX, 1.7, 0, 3)
        regions = text_regions(image)
        self.assertTrue(regions)
        self.assertTrue(all(region[2] > 20 for region in regions))

    def test_no_detected_characters_uses_whole_plate_in_recognizer(self):
        from platewatch.recognition import PlateRecognizer
        recognizer = PlateRecognizer.__new__(PlateRecognizer)
        recognizer.reader = MagicMock()
        recognizer.reader.recognize.return_value = [([[0, 0], [220, 0], [220, 70], [0, 70]], "1234УБА", .95)]
        plate, confidence, raw = recognizer.read_crop(np.full((80, 250, 3), 255, np.uint8))
        self.assertEqual(plate, "1234УБА")
        self.assertGreater(confidence, .9)
        recognizer.reader.readtext.assert_not_called()
        regions = recognizer.reader.recognize.call_args.kwargs["horizontal_list"]
        self.assertIsInstance(regions, list)
        self.assertTrue(regions)
        self.assertEqual(regions[0][0], 0)

    def test_split_two_line_plate_can_be_combined(self):
        items = [([[0, 0], [180, 0], [180, 40], [0, 40]], "1234", .9),
                 ([[25, 55], [155, 55], [155, 95], [25, 95]], "УБА", .85)]
        self.assertEqual(select_ocr_candidate(items)[0], "1234УБА")

    def test_country_logo_gap_keeps_digits_and_letters_separate(self):
        image = np.full((100, 400), 255, np.uint8)
        cv2.putText(image, "1234", (12, 76), cv2.FONT_HERSHEY_SIMPLEX, 1.7, 0, 3)
        cv2.circle(image, (215, 52), 10, 0, 1)
        cv2.putText(image, "ABA", (260, 76), cv2.FONT_HERSHEY_SIMPLEX, 1.7, 0, 3)
        regions = text_regions(image)
        self.assertGreaterEqual(len(regions), 2)
        self.assertTrue(all(not (box[0] < 215 < box[1]) for box in regions))

    def test_large_oval_country_logo_is_not_a_character(self):
        image = np.full((156, 720), 255, np.uint8)
        cv2.putText(image, "9638", (55, 130), cv2.FONT_HERSHEY_SIMPLEX, 3, 0, 5)
        cv2.ellipse(image, (380, 95), (36, 24), 0, 0, 360, 0, 2)
        cv2.putText(image, "YEH", (440, 130), cv2.FONT_HERSHEY_SIMPLEX, 3, 0, 5)
        regions = text_regions(image)
        self.assertGreaterEqual(len(regions), 2)
        self.assertTrue(all(not (box[0] < 380 < box[1]) for box in regions))
