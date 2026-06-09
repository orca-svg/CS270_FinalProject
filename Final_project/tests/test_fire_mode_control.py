import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gesture_bt"))

from fire_mode_control import (
    ControlModeMonitor,
    VALID_MODES,
    VoiceControlSession,
    VoiceWriterLock,
    accepts_voice_mode,
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

    def test_write_control_mode_adds_session_command_and_heartbeat_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode_file = Path(tmp) / "control_mode.json"
            write_control_mode(
                mode_file,
                "single",
                session_id="session-1",
                command_id="command-1",
                heartbeat_at="2026-06-09T00:00:02+00:00",
                updated_at="2026-06-09T00:00:00+00:00",
            )
            payload = json.loads(mode_file.read_text(encoding="utf-8"))

        self.assertEqual(payload["session_id"], "session-1")
        self.assertEqual(payload["command_id"], "command-1")
        self.assertEqual(payload["heartbeat_at"], "2026-06-09T00:00:02+00:00")

    def test_write_control_mode_replaces_file_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode_file = Path(tmp) / "control_mode.json"
            with mock.patch("fire_mode_control.os.replace", wraps=os.replace) as replace:
                write_control_mode(mode_file, "safe")

            replace.assert_called_once()
            self.assertEqual(json.loads(mode_file.read_text())["mode"], "safe")
            self.assertEqual(list(mode_file.parent.glob(f".{mode_file.name}.*.tmp")), [])

    def test_monitor_starts_safe_accepts_fresh_command_and_expires_after_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_mode.json"
            write_control_mode(
                path,
                "burst",
                session_id="s1",
                command_id="c1",
                updated_at="2026-06-09T00:00:00+00:00",
                heartbeat_at="2026-06-09T00:00:00+00:00",
            )
            monitor = ControlModeMonitor(path, ttl_seconds=10.0)
            now = datetime(2026, 6, 9, 0, 0, 5, tzinfo=timezone.utc).timestamp()

            self.assertEqual(monitor.mode, "safe")
            self.assertEqual(monitor.poll(now=now), "burst")
            self.assertEqual(monitor.poll(now=now + 6), "safe")

    def test_monitor_does_not_restore_expired_command_from_heartbeat_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_mode.json"
            write_control_mode(
                path,
                "single",
                session_id="s1",
                command_id="c1",
                updated_at="2026-06-09T00:00:00+00:00",
                heartbeat_at="2026-06-09T00:00:00+00:00",
            )
            monitor = ControlModeMonitor(path, ttl_seconds=10.0)
            base = datetime(2026, 6, 9, 0, 0, 1, tzinfo=timezone.utc).timestamp()
            self.assertEqual(monitor.poll(now=base), "single")
            self.assertEqual(monitor.poll(now=base + 11), "safe")

            write_control_mode(
                path,
                "single",
                session_id="s1",
                command_id="c1",
                updated_at="2026-06-09T00:00:00+00:00",
                heartbeat_at="2026-06-09T00:00:13+00:00",
            )
            self.assertEqual(monitor.poll(now=base + 13), "safe")

            write_control_mode(
                path,
                "single",
                session_id="s1",
                command_id="c2",
                updated_at="2026-06-09T00:00:14+00:00",
                heartbeat_at="2026-06-09T00:00:14+00:00",
            )
            self.assertEqual(monitor.poll(now=base + 14), "single")

    def test_monitor_keeps_last_valid_mode_for_transient_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_mode.json"
            write_control_mode(
                path,
                "guard",
                command_id="c1",
                heartbeat_at="2026-06-09T00:00:00+00:00",
            )
            monitor = ControlModeMonitor(path, ttl_seconds=10.0)
            base = datetime(2026, 6, 9, 0, 0, 1, tzinfo=timezone.utc).timestamp()
            self.assertEqual(monitor.poll(now=base), "guard")

            path.write_text("{", encoding="utf-8")
            self.assertEqual(monitor.poll(now=base + 5), "guard")
            self.assertEqual(monitor.poll(now=base + 12), "safe")

    def test_voice_writer_lock_rejects_second_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_mode.json"
            first = VoiceWriterLock(path)
            second = VoiceWriterLock(path)
            first.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    second.acquire()
            finally:
                first.release()

    def test_voice_session_writes_safe_on_enter_heartbeat_and_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_mode.json"
            with VoiceControlSession(path, source="test", heartbeat_interval=60) as session:
                startup = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(startup["mode"], "safe")
                session.write_mode("burst", transcript="옵티머스 연발", confidence=0.9)
                command = json.loads(path.read_text(encoding="utf-8"))
                session.heartbeat_once()
                heartbeat = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(heartbeat["command_id"], command["command_id"])
                self.assertEqual(heartbeat["updated_at"], command["updated_at"])
            shutdown = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(shutdown["mode"], "safe")
            self.assertNotEqual(shutdown["command_id"], command["command_id"])

    def test_voice_session_exception_still_writes_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control_mode.json"
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with VoiceControlSession(path, source="test", heartbeat_interval=60) as session:
                    session.write_mode("burst", confidence=0.9)
                    raise RuntimeError("boom")

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "safe")
            self.assertEqual(payload["transcript"], "voice process shutdown")

    def test_firing_modes_require_confidence_at_threshold(self):
        self.assertFalse(accepts_voice_mode("single", 0.59))
        self.assertTrue(accepts_voice_mode("single", 0.60))
        self.assertFalse(accepts_voice_mode("burst", None))
        self.assertTrue(accepts_voice_mode("safe", None))
        self.assertTrue(accepts_voice_mode("guard", 0.1))

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
