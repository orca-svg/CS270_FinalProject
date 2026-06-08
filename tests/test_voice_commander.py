import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gesture_bt"))

from voice_commander import DEFAULT_WAKE_WORDS, analyze_intent, build_parser, is_wake_phrase, main, parse_wake_words, write_mode_from_transcript


class VoiceCommanderTests(unittest.TestCase):
    def test_analyze_intent_supports_english_commands(self):
        self.assertEqual(analyze_intent("switch to guard patrol mode"), "guard")
        self.assertEqual(analyze_intent("single precision shot"), "single")
        self.assertEqual(analyze_intent("burst fire at will"), "burst")
        self.assertEqual(analyze_intent("cease fire and safe down"), "safe")

    def test_analyze_intent_supports_natural_fire_commands(self):
        self.assertEqual(analyze_intent("hey you fire"), "single")
        self.assertEqual(analyze_intent("shoot the target"), "single")
        self.assertEqual(analyze_intent("open fire"), "burst")
        self.assertEqual(analyze_intent("rapid fire"), "burst")

    def test_analyze_intent_supports_korean_commands(self):
        self.assertEqual(analyze_intent("경계 모드로 전환"), "guard")
        self.assertEqual(analyze_intent("단발 정밀 사격"), "single")
        self.assertEqual(analyze_intent("발사"), "single")
        self.assertEqual(analyze_intent("쏴"), "single")
        self.assertEqual(analyze_intent("연발 모드 시작"), "burst")
        self.assertEqual(analyze_intent("안전 모드로 정지"), "safe")

    def test_analyze_intent_defaults_to_safe_for_unclear_text(self):
        self.assertEqual(analyze_intent("hello robot"), "safe")
        self.assertEqual(analyze_intent(""), "safe")

    def test_wake_phrase_matching_handles_common_recognition_variants(self):
        self.assertTrue(is_wake_phrase("Hey you please wake up"))
        self.assertTrue(is_wake_phrase("hey, you"))
        self.assertTrue(is_wake_phrase("hey u"))
        self.assertTrue(is_wake_phrase("헤이 유"))
        self.assertFalse(is_wake_phrase("single precision shot"))

    def test_cli_default_wake_words_include_korean_variants(self):
        args = build_parser().parse_args([])
        self.assertIn("헤이 유", parse_wake_words(args.wake_words))
        self.assertEqual(parse_wake_words(args.wake_words), DEFAULT_WAKE_WORDS)

    def test_custom_wake_words_are_parsed_from_cli_value(self):
        wake_words = parse_wake_words("robot, computer")
        self.assertTrue(is_wake_phrase("hello robot", wake_words))
        self.assertTrue(is_wake_phrase("computer start", wake_words))
        self.assertFalse(is_wake_phrase("hey you", wake_words))

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
