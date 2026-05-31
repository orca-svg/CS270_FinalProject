#!/usr/bin/env python3
"""Manual BLE motor-path test for Pybricks Hub V7 fixed-packet protocol.

Run this BEFORE camera control to isolate BLE/Hub/motor issues.

Usage:
    python bt_manual_motor_test.py --hub-name "Team5"
"""
import argparse
import asyncio
from typing import Optional

from bleak import BleakClient, BleakScanner

PYBRICKS_COMMAND_EVENT_CHAR_UUID = "c5f50002-8280-46da-89f4-6d8051e4aeef"


def i8(value: int) -> int:
    value = max(-100, min(100, int(value)))
    return value & 0xFF


def packet_for(command: str) -> bytes:
    """Build a 4-byte packet for the V8 position-tracking protocol."""
    cmd = command.strip().upper()
    if cmd.startswith("M,"):
        parts = cmd.split(",")
        pan_err  = i8(float(parts[1]))
        tilt_err = i8(float(parts[2]))
        fire     = int(parts[3]) & 0xFF
        return bytes([ord("M"), pan_err, tilt_err, fire])
    if cmd == "STOP":
        return b"S\x00\x00\x00"
    raise ValueError(f"Unknown command: {command}")


class HubClient:
    def __init__(self, hub_name: str, scan_timeout: float = 15.0):
        self.hub_name = hub_name
        self.scan_timeout = scan_timeout
        self.client: Optional[BleakClient] = None
        self.ready = asyncio.Event()
        self.rx_buffer = ""

    async def connect(self):
        print(f"Scanning for BLE hub named '{self.hub_name}'...")
        device = await BleakScanner.find_device_by_name(self.hub_name, timeout=self.scan_timeout)
        if device is None:
            raise RuntimeError(f"Could not find hub named {self.hub_name!r}")
        self.client = BleakClient(device)
        await self.client.connect()
        await self.client.start_notify(PYBRICKS_COMMAND_EVENT_CHAR_UUID, self._rx)
        print("BLE connected. Now press the Hub center button once. Wait for [Hub] READY.")

    def _rx(self, _sender, data: bytearray):
        if not data or data[0] != 0x01:
            return
        payload = bytes(data[1:])
        if b"rdy" in payload:
            self.ready.set()
            payload = payload.replace(b"rdy", b"")
        text = payload.decode("utf-8", errors="replace")
        self.rx_buffer += text
        while "\n" in self.rx_buffer:
            line, self.rx_buffer = self.rx_buffer.split("\n", 1)
            line = line.strip()
            if line:
                print(f"[Hub] {line}")

    async def send(self, command: str, timeout: float = 5.0):
        await asyncio.wait_for(self.ready.wait(), timeout=timeout)
        self.ready.clear()
        packet = packet_for(command)
        print(f"[SEND] {command} -> {packet!r}")
        await self.client.write_gatt_char(
            PYBRICKS_COMMAND_EVENT_CHAR_UUID,
            b"\x06" + packet,
            response=True,
        )
        await asyncio.sleep(0.45)

    async def close(self):
        if self.client:
            try:
                await self.send("CENTER", timeout=0.5)
            except Exception:
                pass
            await self.client.disconnect()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub-name", default="Team5")
    args = parser.parse_args()

    hub = HubClient(args.hub_name)
    await hub.connect()

    try:
        await asyncio.wait_for(hub.ready.wait(), timeout=20.0)
        print("Hub rdy received. Starting fixed-packet motor test...")
        # Do NOT clear ready here — hub.send() consumes it for the first command.
        # Clearing here causes a deadlock: send() waits for rdy, but Hub waits for a packet.

        # V8 position-tracking test:
        #   pan/tilt errors drive target angle accumulation on the Hub.
        #   fire=1 latches one shot (Hub must be loaded to fire).
        commands = [
            "M,100,0,0",    # push pan target left
            "M,100,0,0",
            "M,100,0,0",
            "M,-100,0,0",   # push pan target right
            "M,-100,0,0",
            "M,-100,0,0",
            "M,0,0,0",      # return to roughly center
            "M,0,100,0",    # push tilt target down
            "M,0,100,0",
            "M,0,-100,0",   # push tilt target up
            "M,0,-100,0",
            "M,0,0,0",
            "M,0,0,1",      # fire 1 shot
            "M,0,0,0",
            "M,0,0,0",
            "M,0,0,0",
            "M,0,0,0",
            "STOP",
        ]
        for cmd in commands:
            await hub.send(cmd, timeout=10.0)
        print("Manual motor test done.")
    finally:
        await hub.close()


if __name__ == "__main__":
    asyncio.run(main())
