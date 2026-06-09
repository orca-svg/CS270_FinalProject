import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gesture_bt"))

from voice_commander import (
    DEFAULT_WAKE_WORDS,
    analyze_intent,
    build_parser,
    command_from_wake_phrase,
    is_wake_phrase,
    main,
    parse_wake_words,
    write_mode_from_transcript,
)


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

    def test_analyze_intent_prioritizes_safety_over_fire_keywords(self):
        self.assertEqual(analyze_intent("do not fire"), "safe")
        self.assertEqual(analyze_intent("don't shoot"), "safe")
        self.assertEqual(analyze_intent("cancel launch"), "safe")
        self.assertEqual(analyze_intent("cancel rapid fire"), "safe")

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
        self.assertTrue(is_wake_phrase("옵티머스"))
        self.assertTrue(is_wake_phrase("옵티머스 준비"))
        self.assertTrue(is_wake_phrase("옵티 머스"))
        self.assertTrue(is_wake_phrase("옵티.머스"))
        self.assertTrue(is_wake_phrase("Optimus, 발사"))
        self.assertFalse(is_wake_phrase("single precision shot"))
        self.assertFalse(is_wake_phrase("헤이 유 발사"))

    def test_wake_phrase_can_include_command_in_same_transcript(self):
        self.assertEqual(command_from_wake_phrase("옵티머스 발사"), "single")
        self.assertEqual(command_from_wake_phrase("옵티 머스 연발"), "burst")
        self.assertEqual(command_from_wake_phrase("옵티머스 멈춰"), "safe")
        self.assertIsNone(command_from_wake_phrase("옵티머스"))
        self.assertIsNone(command_from_wake_phrase("fire"))

    def test_commander_returns_to_safe_when_process_exits(self):
        class WaitTimeoutError(Exception):
            pass

        class UnknownValueError(Exception):
            pass

        class Microphone:
            def __init__(self, device_index=None):
                self.device_index = device_index

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class Recognizer:
            transcripts = iter(["옵티머스 발사", KeyboardInterrupt()])

            def adjust_for_ambient_noise(self, source, duration):
                pass

            def listen(self, source, timeout, phrase_time_limit):
                value = next(self.transcripts)
                if isinstance(value, BaseException):
                    raise value
                return value

            def recognize_google(self, audio, language, show_all=False):
                if show_all:
                    return {"alternative": [{"transcript": audio, "confidence": 0.99}]}
                return audio

        fake_sr = types.SimpleNamespace(
            Recognizer=Recognizer,
            Microphone=Microphone,
            WaitTimeoutError=WaitTimeoutError,
            UnknownValueError=UnknownValueError,
        )

        import voice_commander

        original_import_module = voice_commander.importlib.import_module
        voice_commander.importlib.import_module = (
            lambda name: fake_sr
            if name == "speech_recognition"
            else original_import_module(name)
        )
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "control_mode.json"
                args = build_parser().parse_args([
                    "--control-mode-file",
                    str(path),
                    "--language",
                    "ko-KR",
                ])
                voice_commander.run_commander(args)
                payload = json.loads(path.read_text(encoding="utf-8"))
        finally:
            voice_commander.importlib.import_module = original_import_module

        self.assertEqual(payload["mode"], "safe")
        self.assertEqual(payload["transcript"], "voice process shutdown")

    def test_cli_default_wake_words_use_optimus_variants(self):
        args = build_parser().parse_args([])
        self.assertIn("옵티머스", parse_wake_words(args.wake_words))
        self.assertNotIn("헤이 유", parse_wake_words(args.wake_words))
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
