import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gesture_bt"))

from voice_commander import analyze_intent, main, write_mode_from_transcript


class VoiceCommanderTests(unittest.TestCase):
    def test_analyze_intent_supports_english_commands(self):
        self.assertEqual(analyze_intent("switch to guard patrol mode"), "guard")
        self.assertEqual(analyze_intent("single precision shot"), "single")
        self.assertEqual(analyze_intent("burst fire at will"), "burst")
        self.assertEqual(analyze_intent("cease fire and safe down"), "safe")

    def test_analyze_intent_supports_korean_commands(self):
        self.assertEqual(analyze_intent("경계 모드로 전환"), "guard")
        self.assertEqual(analyze_intent("단발 정밀 사격"), "single")
        self.assertEqual(analyze_intent("연발 모드 시작"), "burst")
        self.assertEqual(analyze_intent("안전 모드로 정지"), "safe")

    def test_analyze_intent_defaults_to_safe_for_unclear_text(self):
        self.assertEqual(analyze_intent("hello robot"), "safe")
        self.assertEqual(analyze_intent(""), "safe")

    def test_write_mode_from_transcript_uses_project_json_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "control_mode.json"
            mode = write_mode_from_transcript(path, "please burst now")
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(mode, "burst")
        self.assertEqual(payload["mode"], "burst")
        self.assertEqual(payload["source"], "voice")
        self.assertEqual(payload["transcript"], "please burst now")
        self.assertEqual(payload["confidence"], 0.99)
        self.assertIn("updated_at", payload)

    def test_dry_run_cli_writes_json_without_microphone_dependency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "control_mode.json"
            exit_code = main([
                "--control-mode-file",
                str(path),
                "--dry-run-text",
                "경계 모드",
            ])
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "guard")
        self.assertEqual(payload["source"], "voice")


if __name__ == "__main__":
    unittest.main()
