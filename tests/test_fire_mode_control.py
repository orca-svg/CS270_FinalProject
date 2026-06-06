import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gesture_bt"))

from fire_mode_control import (
    VALID_MODES,
    describe_burst_decision,
    describe_visibility_fire_decision,
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

    def test_describe_burst_decision_explains_fire_gate_reasons(self):
        ready = describe_burst_decision(
            current_time=10.0,
            last_burst_fire_time=8.0,
            burst_interval=0.7,
            target_visible=True,
            no_fire=False,
            hub_program_running=True,
        )
        self.assertTrue(ready["should_request_fire"])
        self.assertEqual(ready["reason"], "ready")

        not_visible = describe_burst_decision(
            current_time=10.0,
            last_burst_fire_time=8.0,
            burst_interval=0.7,
            target_visible=False,
            no_fire=False,
            hub_program_running=True,
        )
        self.assertFalse(not_visible["should_request_fire"])
        self.assertEqual(not_visible["reason"], "target_not_visible")

        cooling_down = describe_burst_decision(
            current_time=10.0,
            last_burst_fire_time=9.8,
            burst_interval=0.7,
            target_visible=True,
            no_fire=False,
            hub_program_running=True,
        )
        self.assertFalse(cooling_down["should_request_fire"])
        self.assertEqual(cooling_down["reason"], "cooldown")
        self.assertAlmostEqual(cooling_down["cooldown_remaining"], 0.5)

        no_fire = describe_burst_decision(
            current_time=10.0,
            last_burst_fire_time=8.0,
            burst_interval=0.7,
            target_visible=True,
            no_fire=True,
            hub_program_running=True,
        )
        self.assertFalse(no_fire["should_request_fire"])
        self.assertEqual(no_fire["reason"], "no_fire_flag")

        hub_stopped = describe_burst_decision(
            current_time=10.0,
            last_burst_fire_time=8.0,
            burst_interval=0.7,
            target_visible=True,
            no_fire=False,
            hub_program_running=False,
        )
        self.assertFalse(hub_stopped["should_request_fire"])
        self.assertEqual(hub_stopped["reason"], "hub_program_stopped")

    def test_visibility_fire_decision_requires_visible_target_for_0_4_seconds(self):
        waiting = describe_visibility_fire_decision(
            current_time=10.2,
            target_first_seen_time=10.0,
            required_visible_seconds=0.4,
            target_visible=True,
            no_fire=False,
            hub_program_running=True,
        )
        self.assertFalse(waiting["should_request_fire"])
        self.assertEqual(waiting["reason"], "visible_warmup")
        self.assertAlmostEqual(waiting["remaining_visible_seconds"], 0.2)

        ready = describe_visibility_fire_decision(
            current_time=10.4,
            target_first_seen_time=10.0,
            required_visible_seconds=0.4,
            target_visible=True,
            no_fire=False,
            hub_program_running=True,
        )
        self.assertTrue(ready["should_request_fire"])
        self.assertEqual(ready["reason"], "ready")

        lost = describe_visibility_fire_decision(
            current_time=10.6,
            target_first_seen_time=None,
            required_visible_seconds=0.4,
            target_visible=False,
            no_fire=False,
            hub_program_running=True,
        )
        self.assertFalse(lost["should_request_fire"])
        self.assertEqual(lost["reason"], "target_not_visible")


if __name__ == "__main__":
    unittest.main()
