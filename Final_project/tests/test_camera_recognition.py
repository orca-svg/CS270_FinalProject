import sys
import unittest
from pathlib import Path

try:
    import cv2
    import numpy as np
except ModuleNotFoundError:
    cv2 = None
    np = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gesture_bt"))


@unittest.skipIf(cv2 is None or np is None, "OpenCV and NumPy are required")
class CameraRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from balloon_intercept import red_mask as mac_red_mask
        from balloon_intercept_win import red_mask as win_red_mask

        cls.red_masks = (mac_red_mask, win_red_mask)

    def test_borderline_red_is_detected_on_both_platforms(self):
        hsv = np.zeros((100, 100, 3), dtype=np.uint8)
        hsv[25:75, 25:75] = (0, 115, 68)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        for red_mask in self.red_masks:
            with self.subTest(platform=red_mask.__module__):
                self.assertGreaterEqual(cv2.countNonZero(red_mask(frame)), 2400)

    def test_single_pixel_red_noise_is_removed_on_both_platforms(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame[50, 50] = (0, 0, 255)

        for red_mask in self.red_masks:
            with self.subTest(platform=red_mask.__module__):
                self.assertEqual(cv2.countNonZero(red_mask(frame)), 0)


if __name__ == "__main__":
    unittest.main()
