#!/usr/bin/env python3
"""Offline voice commander using MLX Whisper or faster-whisper."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from fire_mode_control import (
    DEFAULT_FIRE_CONFIDENCE,
    VALID_MODES,
    VoiceControlSession,
    accepts_voice_mode,
)
from local_speech import (
    DEFAULT_FASTER_MODEL,
    DEFAULT_MLX_MODEL,
    RmsVadRecorder,
    VadConfig,
    list_input_devices,
    open_microphone,
    process_transcript,
    select_backend,
)
from voice_commander import (
    DEFAULT_CONTROL_MODE_FILE,
    command_from_wake_phrase,
    is_wake_phrase,
    match_intent,
    parse_wake_words,
)


def run(args: argparse.Namespace) -> None:
    control_mode_file = Path(args.control_mode_file)
    wake_words = parse_wake_words(args.wake_words)
    config = VadConfig(
        sample_rate=args.sample_rate,
        block_ms=args.block_ms,
        silence_ms=args.silence_ms,
        pre_roll_ms=args.pre_roll_ms,
        start_confirm_ms=args.start_confirm_ms,
        max_phrase_seconds=args.max_phrase_seconds,
        min_rms=args.min_rms,
        ambient_multiplier=args.ambient_multiplier,
    )

    with VoiceControlSession(
        control_mode_file,
        source=f"voice-local-{args.backend}",
        heartbeat_interval=args.heartbeat_interval,
    ) as control_session:
        transcriber = select_backend(
            args.backend,
            model=args.model,
            device=args.compute_device,
            compute_type=args.compute_type,
        )
        control_session.source = f"voice-local-{transcriber.name}"
        print(f"[LOCAL-STT] backend={transcriber.name} model={args.model or 'default'}")
        if not args.skip_warmup:
            print("[LOCAL-STT] preparing model (first run may download model files)")
            started = time.perf_counter()
            transcriber.prepare(args.language)
            print(f"[LOCAL-STT] model ready ({time.perf_counter() - started:.2f}s)")

        recorder = RmsVadRecorder(config)
        is_awake = not args.require_wake_word

        with open_microphone(args.device_index, config) as stream:
            print(f"[AUDIO] calibrating ambient noise for {args.ambient_duration:.1f}s")
            threshold = recorder.calibrate(stream, args.ambient_duration)
            print(f"[AUDIO] ready threshold={threshold:.0f}; Ctrl+C to stop")
            if args.require_wake_word:
                print(f"[WAKE] {', '.join(wake_words)}")

            while True:
                try:
                    audio = recorder.capture(stream, threshold)
                    started = time.perf_counter()
                    transcript, confidence = transcriber.transcribe(audio, args.language)
                    elapsed = time.perf_counter() - started
                    if not transcript:
                        if args.verbose:
                            print(f"[STT] empty ({elapsed:.2f}s)")
                        continue

                    print(f'🗣️ "{transcript}" ({elapsed:.2f}s)')
                    mode, is_awake = process_transcript(
                        transcript,
                        require_wake_word=args.require_wake_word,
                        is_awake=is_awake,
                        wake_words=wake_words,
                        match_intent=match_intent,
                        is_wake_phrase=is_wake_phrase,
                        command_from_wake_phrase=command_from_wake_phrase,
                    )
                    if mode is None:
                        if args.require_wake_word and is_awake:
                            print("[WAKE] activated; speak a command")
                        elif args.verbose:
                            print("[MODE] no supported command; ignored")
                        continue

                    if not accepts_voice_mode(
                        mode,
                        confidence,
                        fire_threshold=args.fire_confidence,
                    ):
                        is_awake = True
                        confidence_text = "unknown" if confidence is None else f"{confidence:.2f}"
                        print(
                            f"[MODE] rejected {mode}: confidence={confidence_text} "
                            f"< {args.fire_confidence:.2f}; repeat command"
                        )
                        continue

                    control_session.write_mode(
                        mode,
                        transcript=transcript,
                        confidence=confidence,
                    )
                    print(f"[MODE] {mode.upper()}")
                except KeyboardInterrupt:
                    print("\nLocal voice commander 종료")
                    return
                except Exception as exc:
                    print(f"[LOCAL-STT] error: {exc}")
                    if not args.keep_running:
                        raise
                    time.sleep(0.5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline microphone -> local Whisper -> control_mode.json"
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "mlx", "faster-whisper"),
        default="auto",
        help="auto selects MLX on Apple Silicon macOS and faster-whisper elsewhere.",
    )
    parser.add_argument(
        "--model",
        help=(
            f"Model name/path. Defaults: MLX={DEFAULT_MLX_MODEL}, "
            f"faster-whisper={DEFAULT_FASTER_MODEL}."
        ),
    )
    parser.add_argument("--language", default="ko", help="Whisper language code.")
    parser.add_argument("--device-index", type=int, default=None)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--compute-device", default="auto", help="faster-whisper device: auto/cpu/cuda.")
    parser.add_argument("--compute-type", default="auto", help="faster-whisper compute type.")
    parser.add_argument(
        "--skip-warmup",
        action="store_true",
        help="Skip startup warmup. The first recognized command may be slower.",
    )
    parser.add_argument("--control-mode-file", default=str(DEFAULT_CONTROL_MODE_FILE))
    parser.add_argument("--initial-mode", choices=sorted(VALID_MODES), default="safe")
    parser.add_argument("--heartbeat-interval", type=float, default=2.0)
    parser.add_argument("--fire-confidence", type=float, default=DEFAULT_FIRE_CONFIDENCE)
    parser.add_argument("--wake-words", default=None)
    parser.add_argument("--no-wake-word", dest="require_wake_word", action="store_false")
    parser.set_defaults(require_wake_word=True)

    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--block-ms", type=int, default=30)
    parser.add_argument("--silence-ms", type=int, default=420)
    parser.add_argument("--pre-roll-ms", type=int, default=240)
    parser.add_argument("--start-confirm-ms", type=int, default=90)
    parser.add_argument("--max-phrase-seconds", type=float, default=4.0)
    parser.add_argument("--ambient-duration", type=float, default=1.0)
    parser.add_argument("--min-rms", type=float, default=260.0)
    parser.add_argument("--ambient-multiplier", type=float, default=3.0)
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_devices:
        for index, name, sample_rate in list_input_devices():
            print(f"{index}: {name} ({sample_rate:.0f} Hz)")
        return 0
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
