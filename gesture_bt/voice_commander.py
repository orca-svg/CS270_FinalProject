"""Voice-command helper that writes fire modes into control_mode.json.

This process is intentionally separate from the real-time camera loop. It listens
for short voice commands, maps them to one of the supported presentation modes,
and writes the existing JSON schema consumed by balloon_intercept.py:

    {"mode": "single|burst|safe|guard", "source": "voice", ...}

Run this in a second terminal while the interceptor is running.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from fire_mode_control import VALID_MODES, normalize_mode, write_control_mode

DEFAULT_CONTROL_MODE_FILE = Path(__file__).with_name("control_mode.json")

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "guard": (
        "guard",
        "search",
        "patrol",
        "secure",
        "perimeter",
        "scan",
        "radar",
        "watch",
        "경계",
        "수색",
        "탐색",
        "순찰",
        "감시",
        "레이더",
    ),
    "single": (
        "single",
        "one",
        "target",
        "sniper",
        "precision",
        "semi",
        "단발",
        "한발",
        "한 발",
        "정밀",
        "저격",
    ),
    "burst": (
        "burst",
        "auto",
        "automatic",
        "many",
        "rapid",
        "fire at will",
        "continuous",
        "연발",
        "자동",
        "난사",
        "연사",
        "계속",
        "많이",
    ),
    "safe": (
        "safe",
        "stop",
        "hold",
        "cease",
        "down",
        "pause",
        "cancel",
        "안전",
        "중지",
        "정지",
        "멈춰",
        "멈추",
        "발사 금지",
        "사격 중지",
    ),
}


def analyze_intent(text: str, *, default: str = "safe") -> str:
    """Map a voice transcript to one supported fire mode.

    Long phrases are checked before short phrases so expressions like
    "fire at will" or "한 발" are handled predictably. Returning safe by
    default keeps the robot conservative when a transcript is unclear.
    """
    text_norm = str(text).casefold().strip()
    if not text_norm:
        return normalize_mode(default, default="safe")

    for mode, keywords in INTENT_KEYWORDS.items():
        for keyword in sorted(keywords, key=len, reverse=True):
            if keyword.casefold() in text_norm:
                return mode
    return normalize_mode(default, default="safe")


def write_mode_from_transcript(path: str | Path, transcript: str, *, confidence: float | None = 0.99) -> str:
    """Analyze one transcript, write control JSON, and return the selected mode."""
    mode = analyze_intent(transcript)
    return write_control_mode(
        path,
        mode,
        source="voice",
        transcript=transcript,
        confidence=confidence,
    )


def run_commander(args: argparse.Namespace) -> None:
    try:
        sr = importlib.import_module("speech_recognition")
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency: speech_recognition. Install with "
            "`python -m pip install SpeechRecognition pyaudio` or run with --dry-run-text."
        ) from exc

    control_mode_file = Path(args.control_mode_file)

    print("==================================================")
    print("🎙️ [AI Voice Commander] 음성 -> JSON 변환기 가동")
    print("==================================================")
    print(f"JSON output: {control_mode_file}")

    if args.initial_mode:
        initial_mode = write_control_mode(
            control_mode_file,
            args.initial_mode,
            source="voice",
            transcript="시스템 시작",
            confidence=1.0,
        )
        print(f"초기 모드 -> [{initial_mode.upper()}]")

    recognizer = sr.Recognizer()
    with sr.Microphone(device_index=args.device_index) as source:
        print("소음 적응 중...")
        recognizer.adjust_for_ambient_noise(source, duration=args.ambient_duration)
        print("✅ 마이크 준비 완료! 명령어 대기 중")
        print("예: 'single', 'burst', 'safe', 'guard' / '단발', '연발', '안전', '경계'")

        while True:
            try:
                audio = recognizer.listen(
                    source,
                    timeout=args.listen_timeout,
                    phrase_time_limit=args.phrase_time_limit,
                )
                text = recognizer.recognize_google(audio, language=args.language)
                mode = write_mode_from_transcript(control_mode_file, text)
                print(f'🗣️ "{text}" -> [{mode.upper()}]')
            except sr.WaitTimeoutError:
                continue
            except sr.UnknownValueError:
                if args.verbose:
                    print("음성을 명령어로 인식하지 못했습니다.")
            except KeyboardInterrupt:
                print("\nVoice commander 종료")
                return
            except Exception as exc:  # Keep voice process from killing the demo loop.
                if args.verbose:
                    print(f"⚠️ 음성 처리 에러: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Voice command to control_mode.json bridge")
    parser.add_argument(
        "--control-mode-file",
        default=str(DEFAULT_CONTROL_MODE_FILE),
        help="JSON file consumed by balloon_intercept.py / balloon_intercept_win.py.",
    )
    parser.add_argument(
        "--initial-mode",
        choices=sorted(VALID_MODES),
        default="safe",
        help="Mode written once on startup. Use empty string to skip.",
    )
    parser.add_argument("--language", default="en-US", help="Google speech recognition language, e.g. en-US or ko-KR.")
    parser.add_argument("--device-index", type=int, default=None, help="Optional microphone device index.")
    parser.add_argument("--listen-timeout", type=float, default=2.0, help="Seconds to wait for speech before retrying.")
    parser.add_argument("--phrase-time-limit", type=float, default=3.0, help="Maximum seconds per command phrase.")
    parser.add_argument("--ambient-duration", type=float, default=1.0, help="Seconds used for ambient noise calibration.")
    parser.add_argument("--verbose", action="store_true", help="Print recognition errors instead of staying quiet.")
    parser.add_argument(
        "--dry-run-text",
        help="Do not open the microphone. Analyze this text once, write JSON, and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.initial_mode == "":
        args.initial_mode = None

    if args.dry_run_text is not None:
        mode = write_mode_from_transcript(args.control_mode_file, args.dry_run_text)
        print(f'🗣️ "{args.dry_run_text}" -> [{mode.upper()}]')
        return 0

    run_commander(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
