import asyncio
import queue
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gesture_bt"))

from balloon_intercept_win import (
    clear_pending_fire_commands,
    command_requests_fire,
)
from pybricks_ble import (
    EXPECTED_SERVER_VERSION,
    HubDiagnostics,
    PybricksBleSender,
)


class BleSafetyTests(unittest.TestCase):
    def test_windows_queue_drops_all_pending_fire_commands(self):
        commands = queue.Queue()
        commands.put("M,1,2,1")
        commands.put("M,3,4,0")
        commands.put("M,5,6,1")

        clear_pending_fire_commands(commands, latest_no_fire="M,7,8,0")

        self.assertEqual(commands.qsize(), 1)
        self.assertEqual(commands.get_nowait(), "M,7,8,0")

    def test_windows_fire_check_reads_only_fourth_packet_field(self):
        self.assertTrue(command_requests_fire("M,10,20,1"))
        self.assertFalse(command_requests_fire("M,10,20,0"))
        self.assertFalse(command_requests_fire("M,1,0,0"))

    def test_hub_diagnostics_accept_expected_version_and_all_required_ports(self):
        diagnostics = HubDiagnostics()
        for line in (
            "PORT_A_OK",
            "PORT_B_OK",
            "PORT_C_OK",
            "PORT_D_TILT_OK",
            "PORT_F_PAN_OK",
            f"SERVER_VERSION {EXPECTED_SERVER_VERSION}",
        ):
            diagnostics.consume(line)

        result = diagnostics.result()
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, ())

    def test_hub_diagnostics_reject_wrong_version_and_missing_motor(self):
        diagnostics = HubDiagnostics()
        for line in (
            "PORT_A_OK",
            "PORT_B_OK",
            "PORT_C_MISSING",
            "PORT_D_TILT_OK",
            "PORT_F_PAN_OK",
            "SERVER_VERSION old-version",
        ):
            diagnostics.consume(line)

        result = diagnostics.result()
        self.assertFalse(result.valid)
        self.assertIn("server_version", result.errors)
        self.assertIn("port_C", result.errors)

    def test_hub_validation_y_override_is_kept_for_process_lifetime(self):
        sender = PybricksBleSender("Team5")
        sender.connected = True
        sender._program_running = True
        sender.ready.set()
        answers = iter(["y"])

        first = asyncio.run(
            sender.ensure_hub_valid(
                timeout=0,
                input_func=lambda _prompt: next(answers),
            )
        )
        second = asyncio.run(
            sender.ensure_hub_valid(
                timeout=0,
                input_func=lambda _prompt: self.fail("must not prompt twice"),
            )
        )

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertTrue(sender.allow_unverified_hub)

    def test_hub_validation_defaults_to_reject(self):
        sender = PybricksBleSender("Team5")
        sender.connected = True
        sender._program_running = True
        sender.ready.set()

        accepted = asyncio.run(
            sender.ensure_hub_valid(timeout=0, input_func=lambda _prompt: "")
        )

        self.assertFalse(accepted)
        self.assertTrue(sender.hub_validation_rejected)
