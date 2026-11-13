import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from platewatch.instance import desktop_instance


@unittest.skipUnless(sys.platform == "win32", "Windows desktop instance guard")
class InstanceTests(unittest.TestCase):
    def test_duplicate_launch_is_rejected_and_guard_is_released(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            with patch("platewatch.instance.APP_DIR", Path(temp)):
                with desktop_instance() as first:
                    self.assertTrue(first)
                    with desktop_instance() as second:
                        self.assertFalse(second)
                with desktop_instance() as after_close:
                    self.assertTrue(after_close)
