"""Shared fire-mode policy helpers for voice-controlled interception demos.

The Hub protocol stays intentionally small: M,pan,tilt,fire. Voice recognition
or keyboard helpers write the desired high-level mode into a JSON file, and the
camera controller decides when to send fire=1.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_MODES = {"single", "burst", "safe", "guard"}


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
    **extra: Any,
) -> dict[str, Any]:
    """Build the JSON shape consumed by the camera controllers.

    Required field:
      - mode: one of single, burst, safe, guard

    Optional metadata is ignored by the real-time control loop but useful for
    debugging voice/LLM decisions and for presentation screenshots.
    """
    payload: dict[str, Any] = {
        "mode": normalize_mode(mode),
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
    }
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
    **extra: Any,
) -> str:
    """Persist a normalized control-mode payload and return the normalized mode."""
    payload = make_control_payload(
        mode,
        source=source,
        transcript=transcript,
        confidence=confidence,
        updated_at=updated_at,
        **extra,
    )
    mode_path = Path(path)
    mode_path.parent.mkdir(parents=True, exist_ok=True)
    mode_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload["mode"]


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
