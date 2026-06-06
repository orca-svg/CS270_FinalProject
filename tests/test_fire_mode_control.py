import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gesture_bt"))

from fire_mode_control import (
    VALID_MODES,
    make_control_payload,
    read_control_mode,
    write_control_mode,
)


class FireModeControlTests(unittest.TestCase):
    def test_read_control_mode_returns_valid_mode_from_minimal_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode_file = Path(tmp) / "control_mode.json"
            mode_file.write_text(json.dumps({"mode": "burst"}), encoding="utf-8")

            self.assertEqual(read_control_mode(mode_file, default="single"), "burst")

    def test_read_control_mode_accepts_voice_metadata_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode_file = Path(tmp) / "control_mode.json"
            mode_file.write_text(
                json.dumps(
                    {
                        "mode": "safe",
                        "source": "voice",
                        "transcript": "발사 중지",
                        "confidence": 0.93,
                        "updated_at": "2026-06-06T12:00:00+09:00",
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(read_control_mode(mode_file, default="single"), "safe")

    def test_read_control_mode_falls_back_for_missing_invalid_or_malformed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            self.assertEqual(read_control_mode(missing, default="single"), "single")

            invalid = Path(tmp) / "invalid.json"
            invalid.write_text(json.dumps({"mode": "not-a-mode"}), encoding="utf-8")
            self.assertEqual(read_control_mode(invalid, default="guard"), "guard")

            malformed = Path(tmp) / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            self.assertEqual(read_control_mode(malformed, default="safe"), "safe")

    def test_make_control_payload_normalizes_and_keeps_metadata(self):
        payload = make_control_payload("BURST", source="voice", transcript="연발", confidence=0.88)

        self.assertEqual(payload["mode"], "burst")
        self.assertEqual(payload["source"], "voice")
        self.assertEqual(payload["transcript"], "연발")
        self.assertEqual(payload["confidence"], 0.88)

    def test_write_control_mode_normalizes_and_persists_mode_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode_file = Path(tmp) / "nested" / "control_mode.json"

            write_control_mode(mode_file, "BURST", source="voice", transcript="연발")

            payload = json.loads(mode_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "burst")
            self.assertEqual(payload["source"], "voice")
            self.assertEqual(payload["transcript"], "연발")
            self.assertEqual(read_control_mode(mode_file, default="single"), "burst")

    def test_valid_modes_cover_presentation_modes(self):
        self.assertTrue({"single", "burst", "safe", "guard"}.issubset(VALID_MODES))


if __name__ == "__main__":
    unittest.main()
