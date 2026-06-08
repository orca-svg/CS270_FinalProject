import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gesture_bt"))

sys.modules.setdefault("cv2", types.ModuleType("cv2"))
sys.modules.setdefault("numpy", types.ModuleType("numpy"))
pybricks_ble = types.ModuleType("pybricks_ble")
setattr(pybricks_ble, "DEFAULT_HUB_NAME", "Team5")
setattr(pybricks_ble, "DryRunSender", object)
setattr(pybricks_ble, "PybricksBleSender", object)
setattr(pybricks_ble, "clamp", lambda value, low, high: max(low, min(high, value)))
sys.modules.setdefault("pybricks_ble", pybricks_ble)

from balloon_intercept import build_parser as build_mac_parser
from balloon_intercept_win import build_parser as build_win_parser


class TrackingModeParserTests(unittest.TestCase):
    def test_model_tracking_does_not_limit_targets_to_sports_ball_by_default(self):
        for build_parser in (build_mac_parser, build_win_parser):
            with self.subTest(parser=build_parser.__module__):
                args = build_parser().parse_args(["--tracking-mode", "model"])
                self.assertIsNone(args.allowed_categories)

    def test_model_tracking_allows_explicit_category_filter_when_needed(self):
        args = build_mac_parser().parse_args([
            "--tracking-mode",
            "model",
            "--allowed-categories",
            "sports ball",
            "person",
        ])
        self.assertEqual(args.allowed_categories, ["sports ball", "person"])


if __name__ == "__main__":
    unittest.main()
