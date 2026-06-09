"""Shared fire-mode policy helpers for voice-controlled interception demos.

The Hub protocol stays intentionally small: M,pan,tilt,fire. Voice recognition
or keyboard helpers write the desired high-level mode into a JSON file, and the
camera controller decides when to send fire=1.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

VALID_MODES = {"single", "burst", "safe", "guard"}
DEFAULT_MODE_TTL_SECONDS = 10.0
DEFAULT_HEARTBEAT_INTERVAL = 2.0
DEFAULT_FIRE_CONFIDENCE = 0.60


def normalize_mode(mode: str, default: str = "single") -> str:
    """Return a supported fire mode, falling back to default when invalid."""
    mode_norm = str(mode).strip().lower()
    if mode_norm in VALID_MODES:
        return mode_norm
    default_norm = str(default).strip().lower()
    if default_norm in VALID_MODES:
        return default_norm
    return "single"


def make_control_payload(
    mode: str,
    *,
    source: str | None = None,
    transcript: str | None = None,
    confidence: float | None = None,
    updated_at: str | None = None,
    heartbeat_at: str | None = None,
    session_id: str | None = None,
    command_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the JSON shape consumed by the camera controllers.

    Required field:
      - mode: one of single, burst, safe, guard

    Optional metadata is ignored by the real-time control loop but useful for
    debugging voice/LLM decisions and for presentation screenshots.
    """
    command_time = updated_at or datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "mode": normalize_mode(mode),
        "updated_at": command_time,
    }
    if heartbeat_at is not None:
        payload["heartbeat_at"] = heartbeat_at
    if session_id is not None:
        payload["session_id"] = session_id
    if command_id is not None:
        payload["command_id"] = command_id
    if source is not None:
        payload["source"] = source
    if transcript is not None:
        payload["transcript"] = transcript
    if confidence is not None:
        payload["confidence"] = confidence
    payload.update(extra)
    return payload


def read_control_mode(path: str | Path, default: str = "single") -> str:
    """Read the current fire mode from a small JSON file.

    Expected minimal schema: {"mode": "single|burst|safe|guard"}.
    Voice integrations may add metadata such as source/transcript/confidence;
    those fields are ignored by the control loop. Missing, malformed, or invalid
    files deliberately fall back so the real-time camera loop keeps running even
    if the voice-recognition process crashes.
    """
    default = normalize_mode(default)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return normalize_mode(data.get("mode", default), default=default)
    except Exception:
        return default


def write_control_mode(
    path: str | Path,
    mode: str,
    *,
    source: str | None = None,
    transcript: str | None = None,
    confidence: float | None = None,
    updated_at: str | None = None,
    heartbeat_at: str | None = None,
    session_id: str | None = None,
    command_id: str | None = None,
    **extra: Any,
) -> str:
    """Persist a normalized control-mode payload and return the normalized mode."""
    payload = make_control_payload(
        mode,
        source=source,
        transcript=transcript,
        confidence=confidence,
        updated_at=updated_at,
        heartbeat_at=heartbeat_at,
        session_id=session_id,
        command_id=command_id,
        **extra,
    )
    mode_path = Path(path)
    mode_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=mode_path.parent,
            prefix=f".{mode_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, mode_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return payload["mode"]


def accepts_voice_mode(
    mode: str,
    confidence: float | None,
    *,
    fire_threshold: float = DEFAULT_FIRE_CONFIDENCE,
) -> bool:
    """Allow safety/non-firing modes, but require confidence for fire modes."""
    normalized = normalize_mode(mode, default="safe")
    if normalized not in {"single", "burst"}:
        return True
    return confidence is not None and float(confidence) >= float(fire_threshold)


def _parse_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


@dataclass(frozen=True)
class ControlModeSnapshot:
    mode: str
    token: str
    freshness: float


class ControlModeMonitor:
    """Read voice mode safely, expiring stale or malformed state to SAFE."""

    def __init__(self, path: str | Path, *, ttl_seconds: float = DEFAULT_MODE_TTL_SECONDS):
        self.path = Path(path)
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.mode = "safe"
        self._last_snapshot: ControlModeSnapshot | None = None
        self._blocked_tokens: set[str] = set()

    def _read_snapshot(self) -> ControlModeSnapshot:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        raw_mode = str(data.get("mode", "")).strip().lower()
        if raw_mode not in VALID_MODES:
            raise ValueError(f"invalid control mode: {raw_mode!r}")
        freshness = (
            _parse_timestamp(data.get("heartbeat_at"))
            or _parse_timestamp(data.get("updated_at"))
            or self.path.stat().st_mtime
        )
        token = str(
            data.get("command_id")
            or data.get("updated_at")
            or f"legacy:{self.path.stat().st_mtime_ns}"
        )
        return ControlModeSnapshot(raw_mode, token, freshness)

    def poll(self, *, now: float | None = None) -> str:
        current_time = time.time() if now is None else float(now)
        try:
            snapshot = self._read_snapshot()
            self._last_snapshot = snapshot
        except Exception:
            snapshot = self._last_snapshot

        if snapshot is None:
            self.mode = "safe"
            return self.mode

        if current_time - snapshot.freshness > self.ttl_seconds:
            self._blocked_tokens.add(snapshot.token)
            self.mode = "safe"
            return self.mode

        if snapshot.token in self._blocked_tokens:
            self.mode = "safe"
            return self.mode

        self.mode = snapshot.mode
        return self.mode


class VoiceWriterLock:
    """Single-writer OS lock shared by online and local voice processes."""

    def __init__(self, control_path: str | Path):
        self.path = Path(f"{Path(control_path)}.lock")
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            handle.close()
            raise RuntimeError(
                f"Another voice process already owns {self.path}."
            ) from exc
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.release()


class VoiceControlSession:
    """Own the voice JSON writer, lifecycle SAFE state, and heartbeat."""

    def __init__(
        self,
        path: str | Path,
        *,
        source: str,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
        clock: Callable[[], datetime] | None = None,
    ):
        self.path = Path(path)
        self.source = source
        self.heartbeat_interval = max(0.1, float(heartbeat_interval))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.session_id = str(uuid.uuid4())
        self._lock = VoiceWriterLock(self.path)
        self._write_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._payload: dict[str, Any] | None = None

    def _now(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat()

    def __enter__(self):
        self._lock.acquire()
        try:
            self.write_mode(
                "safe",
                transcript="voice process startup",
                confidence=1.0,
            )
            self._thread = threading.Thread(
                target=self._heartbeat_loop,
                name="voice-control-heartbeat",
                daemon=True,
            )
            self._thread.start()
        except Exception:
            self._lock.release()
            raise
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.heartbeat_interval + 0.5)
        try:
            self.write_mode(
                "safe",
                transcript="voice process shutdown",
                confidence=1.0,
            )
        finally:
            self._lock.release()

    def write_mode(
        self,
        mode: str,
        *,
        transcript: str | None = None,
        confidence: float | None = None,
    ) -> str:
        now = self._now()
        payload = make_control_payload(
            mode,
            source=self.source,
            transcript=transcript,
            confidence=confidence,
            updated_at=now,
            heartbeat_at=now,
            session_id=self.session_id,
            command_id=str(uuid.uuid4()),
        )
        with self._write_lock:
            self._payload = payload
            return write_control_mode(self.path, **payload)

    def heartbeat_once(self) -> None:
        with self._write_lock:
            if self._payload is None:
                return
            self._payload = {**self._payload, "heartbeat_at": self._now()}
            write_control_mode(self.path, **self._payload)

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self.heartbeat_interval):
            try:
                self.heartbeat_once()
            except Exception as exc:
                print(f"[VOICE] heartbeat write failed: {exc}")


def describe_burst_decision(
    *,
    current_time: float,
    last_burst_fire_time: float,
    burst_interval: float,
    target_visible: bool,
    no_fire: bool,
    hub_program_running: bool | None,
) -> dict[str, Any]:
    """Explain whether burst mode should request fire=1 this frame.

    Burst mode now starts after a target has already passed the visibility warmup.
    After that, it repeats by cooldown while the target remains visible; aiming
    lock is no longer required for the burst fire request itself.
    """
    elapsed = max(0.0, float(current_time) - float(last_burst_fire_time))
    interval = max(0.0, float(burst_interval))
    cooldown_remaining = max(0.0, interval - elapsed)

    if no_fire:
        reason = "no_fire_flag"
    elif hub_program_running is False:
        reason = "hub_program_stopped"
    elif not target_visible:
        reason = "target_not_visible"
    elif cooldown_remaining > 0:
        reason = "cooldown"
    else:
        reason = "ready"

    return {
        "should_request_fire": reason == "ready",
        "reason": reason,
        "elapsed_since_last_fire": elapsed,
        "cooldown_remaining": cooldown_remaining,
    }


def describe_visibility_fire_decision(
    *,
    current_time: float,
    target_first_seen_time: float | None,
    required_visible_seconds: float,
    target_visible: bool,
    no_fire: bool,
    hub_program_running: bool | None,
) -> dict[str, Any]:
    """Explain whether a visible target has been stable long enough to fire."""
    required = max(0.0, float(required_visible_seconds))
    if not target_visible or target_first_seen_time is None:
        visible_elapsed = 0.0
    else:
        visible_elapsed = max(0.0, float(current_time) - float(target_first_seen_time))
    remaining = max(0.0, required - visible_elapsed)

    if no_fire:
        reason = "no_fire_flag"
    elif hub_program_running is False:
        reason = "hub_program_stopped"
    elif not target_visible or target_first_seen_time is None:
        reason = "target_not_visible"
    elif remaining > 0:
        reason = "visible_warmup"
    else:
        reason = "ready"

    return {
        "should_request_fire": reason == "ready",
        "reason": reason,
        "visible_elapsed": visible_elapsed,
        "remaining_visible_seconds": remaining,
    }
