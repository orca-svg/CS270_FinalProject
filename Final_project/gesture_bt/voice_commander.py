"""Voice-command helper that writes fire modes into control_mode.json.

This process is intentionally separate from the real-time camera loop. It listens
for a wake phrase plus a short voice command, maps the command to one of the
supported presentation modes, and writes the existing JSON schema consumed by
balloon_intercept.py:

    {"mode": "single|burst|safe|guard", "source": "voice", ...}

Run this in a second terminal while the interceptor is running. Use
``--dry-run-text`` for hardware-free verification, or ``--no-wake-word`` when a
presenter wants every recognized phrase to be treated as a command.
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from pathlib import Path

from fire_mode_control import (
    DEFAULT_FIRE_CONFIDENCE,
    DEFAULT_HEARTBEAT_INTERVAL,
    VALID_MODES,
    VoiceControlSession,
    accepts_voice_mode,
    normalize_mode,
    write_control_mode,
)

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
        "shoot the target",
        "fire target",
        "take the shot",
        "shoot",
        "fire",
        "shot",
        "launch",
        "single",
        "one",
        "target",
        "sniper",
        "precision",
        "semi",
        "발사해",
        "발사",
        "쏴줘",
        "쏴",
        "사격",
        "단발",
        "한발",
        "한 발",
        "정밀",
        "저격",
    ),
    "burst": (
        "fire at will",
        "open fire",
        "rapid fire",
        "burst",
        "auto",
        "automatic",
        "many",
        "rapid",
        "continuous",
        "연발",
        "자동",
        "난사",
        "연사",
        "계속",
        "많이",
    ),
    "safe": (
        "do not fire",
        "do not shoot",
        "don't fire",
        "don't shoot",
        "never fire",
        "never shoot",
        "no fire",
        "no shooting",
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

DEFAULT_WAKE_WORDS: tuple[str, ...] = (
    "옵티머스",
    "옵티 머스",
    "optimus",
)


def _match_intent(text: str) -> str | None:
    text_norm = str(text).casefold().strip()
    if not text_norm:
        return None

    candidates: list[tuple[int, str, str]] = []
    for mode, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            keyword_norm = keyword.casefold()
            if keyword_norm in text_norm:
                candidates.append((len(keyword_norm), keyword_norm, mode))
    if candidates:
        # A recognized stop/cancel phrase must always override a fire phrase.
        # This prevents transcripts such as "cancel rapid fire" from firing.
        if any(mode == "safe" for _, _, mode in candidates):
            return "safe"

        # Prefer the most specific phrase across all modes. This keeps natural
        # commands like "open fire" / "fire at will" in burst mode while still
        # allowing a bare "fire" to mean one precision shot.
        candidates.sort(reverse=True)
        return candidates[0][2]
    return None


def match_intent(text: str) -> str | None:
    """Return a recognized mode, or None without applying a fallback."""
    return _match_intent(text)


def analyze_intent(text: str, *, default: str = "safe") -> str:
    """Map a voice transcript to one supported fire mode.

    Safety phrases override firing phrases. Otherwise, the longest matching
    phrase wins so expressions like "fire at will" remain predictable.
    Returning safe by default keeps the robot conservative when a transcript is
    unclear.
    """
    mode = _match_intent(text)
    if mode is not None:
        return mode
    return normalize_mode(default, default="safe")


def parse_wake_words(value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated wake-word CLI value.

    Empty input disables wake-word gating only when the caller also passes
    ``--no-wake-word``; otherwise we keep the demo default conservative.
    """
    if value is None:
        return DEFAULT_WAKE_WORDS
    words = tuple(word.casefold().strip() for word in value.split(",") if word.strip())
    return words or DEFAULT_WAKE_WORDS


def is_wake_phrase(text: str, wake_words: tuple[str, ...] = DEFAULT_WAKE_WORDS) -> bool:
    """Return True when a recognized phrase should wake the commander.

    Speech-to-text punctuation, whitespace, and casing vary, so matching uses
    word boundaries with flexible separators between wake-word parts.
    """
    text_norm = str(text).casefold()
    for wake_word in wake_words:
        parts = re.findall(r"\w+", wake_word.casefold(), flags=re.UNICODE)
        if not parts:
            continue
        pattern = r"(?<!\w)" + r"[\W_]*".join(re.escape(part) for part in parts) + r"(?!\w)"
        if re.search(pattern, text_norm, flags=re.UNICODE):
            return True
    return False


def command_from_wake_phrase(
    text: str,
    wake_words: tuple[str, ...] = DEFAULT_WAKE_WORDS,
) -> str | None:
    """Return a command embedded in a wake-phrase transcript, if present."""
    if not is_wake_phrase(text, wake_words):
        return None
    return _match_intent(text)


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
    control_mode_file = Path(args.control_mode_file)
    wake_words = parse_wake_words(args.wake_words)

    with VoiceControlSession(
        control_mode_file,
        source="voice-online",
        heartbeat_interval=args.heartbeat_interval,
    ) as control_session:
        try:
            sr = importlib.import_module("speech_recognition")
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "Missing dependency: speech_recognition. Install with "
                "`python -m pip install SpeechRecognition pyaudio` or run with --dry-run-text."
            ) from exc

        print("==================================================")
        print("🎙️ [AI Voice Commander] 음성 -> JSON 변환기 가동")
        print("==================================================")
        print(f"JSON output: {control_mode_file}")
        if args.require_wake_word:
            print(f"호출어 대기: {', '.join(wake_words)}")
        print("초기 모드 -> [SAFE]")

        recognizer = sr.Recognizer()
        with sr.Microphone(device_index=args.device_index) as source:
            print("소음 적응 중...")
            recognizer.adjust_for_ambient_noise(source, duration=args.ambient_duration)
            if args.require_wake_word:
                print("✅ 마이크 준비 완료! 호출어를 먼저 말해주세요. 예: '옵티머스'")
            else:
                print("✅ 마이크 준비 완료! 명령어 대기 중")
            print("예: 'single', 'burst', 'safe', 'guard' / '단발', '연발', '안전', '경계'")

            is_awake = not args.require_wake_word

            while True:
                try:
                    audio = recognizer.listen(
                        source,
                        timeout=args.listen_timeout,
                        phrase_time_limit=args.phrase_time_limit,
                    )
                    response = recognizer.recognize_google(audio, language=args.language, show_all=True)
                    if not isinstance(response, dict) or "alternative" not in response or not response["alternative"]:
                        if args.verbose:
                            print("음성을 인식하지 못했습니다 (응답 비어있음).")
                        continue

                    best_alt = response["alternative"][0]
                    text = best_alt.get("transcript", "").strip()
                    confidence = best_alt.get("confidence", None)
                    if confidence is None:
                        confidence = 0.99
                    else:
                        confidence = float(confidence)

                    if not is_awake:
                        if not is_wake_phrase(text, wake_words):
                            if args.verbose:
                                print(f'호출어 아님: "{text}"')
                            continue
                        mode = command_from_wake_phrase(text, wake_words)
                        if mode is None:
                            print("\n🔔 [활성화] 네, 명령을 말씀하세요!")
                            is_awake = True
                            continue
                    else:
                        mode = match_intent(text)
                        if mode is None:
                            if args.verbose:
                                print(f'지원 명령 아님: "{text}"')
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

                    control_session.write_mode(mode, transcript=text, confidence=confidence)
                    print(f'🗣️ "{text}" -> [{mode.upper()}]')
                    if args.require_wake_word:
                        print("💤 명령 수행 완료. 다시 호출어 대기 모드로 돌아갑니다.\n")
                        is_awake = False
                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    if args.verbose:
                        print("음성을 명령어로 인식하지 못했습니다.")
                except KeyboardInterrupt:
                    print("\nVoice commander 종료")
                    return
                except Exception as exc:
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
    parser.add_argument("--heartbeat-interval", type=float, default=DEFAULT_HEARTBEAT_INTERVAL)
    parser.add_argument("--fire-confidence", type=float, default=DEFAULT_FIRE_CONFIDENCE)
    parser.add_argument("--verbose", action="store_true", help="Print recognition errors instead of staying quiet.")
    parser.add_argument(
        "--wake-words",
        default=None,
        help="Comma-separated wake phrases recognized before accepting a command.",
    )
    parser.add_argument(
        "--no-wake-word",
        dest="require_wake_word",
        action="store_false",
        help="Treat every recognized phrase as a command without waiting for '옵티머스'.",
    )
    parser.set_defaults(require_wake_word=True)
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
