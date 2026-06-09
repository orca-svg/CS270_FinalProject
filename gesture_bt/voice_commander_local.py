"""Local offline Voice-command helper that writes fire modes into control_mode.json using Vosk.

This process runs 100% locally and offline. It listens to user voice commands
using the microphone, matches the intent, and updates control_mode.json.
"""

from __future__ import annotations

import argparse
import sys
import os
import json
import urllib.request
import zipfile
import ssl
from pathlib import Path
from datetime import datetime, timezone

from fire_mode_control import VALID_MODES, normalize_mode, write_control_mode

DEFAULT_CONTROL_MODE_FILE = Path(__file__).parent / "control_mode.json"

DEFAULT_VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ko-0.22.zip"
DEFAULT_VOSK_MODEL_PATH = Path(__file__).resolve().parent / "models" / "vosk-model-small-ko-0.22"

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "guard": (
        "guard", "search", "patrol", "secure", "perimeter", "scan", "radar", "watch",
        "경계", "수색", "탐색", "순찰", "감시", "레이더"
    ),
    "single": (
        "single", "one", "target", "sniper", "precision", "semi",
        "단발", "한발", "한 발", "정밀", "저격"
    ),
    "burst": (
        "burst", "auto", "automatic", "many", "rapid", "fire at will", "continuous",
        "연발", "자동", "난사", "연사", "계속", "많이"
    ),
    "safe": (
        "safe", "stop", "hold", "cease", "down", "pause", "cancel",
        "안전", "중지", "정지", "멈춰", "멈추", "발사 금지", "사격 중지"
    ),
}

DEFAULT_WAKE_WORDS: tuple[str, ...] = (
    "hey you", "hey, you", "hey u", "hey-you", "헤이 유", "헤이유", "이유"
)


def analyze_intent(text: str, *, default: str | None = "safe") -> str | None:
    text_norm = str(text).casefold().strip()
    if not text_norm:
        return default

    for mode, keywords in INTENT_KEYWORDS.items():
        for keyword in sorted(keywords, key=len, reverse=True):
            if keyword.casefold() in text_norm:
                return mode
    return default


def ensure_vosk_model(model_path: Path, model_url: str) -> Path:
    model_path = model_path.expanduser().resolve()
    if model_path.exists():
        if any(model_path.iterdir()):
            return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path = model_path.parent / "vosk_model.zip"
    print(f"Vosk Korean model not found. Downloading to: {zip_path}")
    try:
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(model_url, context=context) as response, open(zip_path, 'wb') as out_file:
            out_file.write(response.read())
        
        print("Extracting model zip file...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(model_path.parent)
        
        # Delete the zip file after extraction
        zip_path.unlink()
    except Exception as exc:
        if zip_path.exists():
            try:
                zip_path.unlink()
            except Exception:
                pass
        print("\n" + "="*80)
        print("❌ [오류] Vosk 모델 파일을 자동 다운로드하지 못했습니다.")
        print("아래 링크를 브라우저에서 다운로드해 주세요:")
        print(f"🔗 {model_url}")
        print(f"다운로드 후 압축을 풀고 폴더명을 '{model_path.name}'으로 변경하여 다음 위치에 놓아주세요: {model_path}")
        print("="*80 + "\n")
        raise RuntimeError("Could not download the Vosk model.") from exc
    return model_path


def is_wake_phrase(text: str, wake_words: tuple[str, ...] = DEFAULT_WAKE_WORDS) -> bool:
    text_norm = str(text).casefold().strip()
    return any(wake_word.casefold() in text_norm for wake_word in wake_words)


def write_mode_from_transcript(path: str | Path, transcript: str, *, confidence: float | None = 0.99) -> str | None:
    mode = analyze_intent(transcript, default=None)
    if mode is None:
        return None
    write_control_mode(
        path,
        mode,
        source="voice",
        transcript=transcript,
        confidence=confidence,
    )
    return mode


def run_commander(args: argparse.Namespace) -> None:
    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        import pyaudio
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependencies: vosk or pyaudio. Install with "
            "`python -m pip install vosk pyaudio`"
        ) from exc

    model_path = ensure_vosk_model(Path(args.model_path), args.model_url)
    control_mode_file = Path(args.control_mode_file)
    wake_words = tuple(w.strip().casefold() for w in args.wake_words.split(",") if w.strip())

    print("==================================================")
    print("🎙️ [AI Local Voice Commander] 로컬 오프라인 음성 인식기 가동")
    print("==================================================")
    print(f"JSON output: {control_mode_file}")
    if args.require_wake_word:
        print(f"호출어 대기: {', '.join(wake_words)}")

    if args.initial_mode:
        initial_mode = write_control_mode(
            control_mode_file,
            args.initial_mode,
            source="voice",
            transcript="시스템 시작",
            confidence=1.0,
        )
        print(f"초기 모드 -> [{initial_mode.upper()}]")

    SetLogLevel(-2)
    model = Model(str(model_path))
    
    # 조준 명령어 및 호출어들로만 검색 범위를 한정(Grammar)하여 오프라인 인식률을 100%에 가깝게 끌어올립니다.
    grammar_words = []
    for keywords in INTENT_KEYWORDS.values():
        for kw in keywords:
            grammar_words.append(kw)
    for w in wake_words:
        grammar_words.append(w)
    grammar_words.append("[unk]")  # 알 수 없는 단어 처리용
    
    grammar_json = json.dumps(grammar_words, ensure_ascii=False)
    rec = KaldiRecognizer(model, 16000, grammar_json)

    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=4000
    )
    stream.start_stream()

    if args.require_wake_word:
        print("✅ 마이크 준비 완료! 호출어를 먼저 말해주세요. 예: 'Hey you' 또는 '헤이 유'")
    else:
        print("✅ 마이크 준비 완료! 명령어 대기 중")
    print("예: 'single', 'burst', 'safe', 'guard' / '단발', '연발', '안전', '경계'")

    is_awake = not args.require_wake_word

    try:
        while True:
            data = stream.read(4000, exception_on_overflow=False)
            if len(data) == 0:
                continue

            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                text = res.get("text", "").strip()
                if not text:
                    continue

                # Clear the partial progress line
                sys.stdout.write("\r" + " " * 80 + "\r")
                sys.stdout.flush()

                if not is_awake:
                    if is_wake_phrase(text, wake_words):
                        print(f'\r🔔 [활성화] 네, 명령을 말씀하세요! (인식: "{text}")')
                        is_awake = True
                    elif args.verbose:
                        print(f'\r호출어 아님: "{text}"')
                else:
                    mode = write_mode_from_transcript(control_mode_file, text)
                    if mode is not None:
                        print(f'🗣️ 최종 인식: "{text}" -> [{mode.upper()}]')
                        if args.require_wake_word:
                            print("💤 명령 수행 완료. 다시 호출어 대기 모드로 돌아갑니다.\n")
                            is_awake = False
                    else:
                        print(f'🗣️ 최종 인식: "{text}" -> [일치하는 명령어 없음, 무시]')
            else:
                partial = json.loads(rec.PartialResult())
                p_text = partial.get("partial", "").strip()
                if p_text:
                    # Print partial transcription in real-time on the same line
                    sys.stdout.write(f'\r🎙️ [듣는 중...]: "{p_text}"')
                    sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nVoice commander 종료")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Voice command to control_mode.json bridge")
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
    parser.add_argument(
        "--model-path",
        default=str(DEFAULT_VOSK_MODEL_PATH),
        help="Path to Vosk model folder."
    )
    parser.add_argument(
        "--model-url",
        default=DEFAULT_VOSK_MODEL_URL,
        help="URL to download Vosk model if missing."
    )
    parser.add_argument("--verbose", action="store_true", help="Print recognition details.")
    parser.add_argument(
        "--wake-words",
        default=",".join(DEFAULT_WAKE_WORDS),
        help="Comma-separated wake phrases recognized before accepting a command.",
    )
    parser.add_argument(
        "--no-wake-word",
        dest="require_wake_word",
        action="store_false",
        help="Treat every recognized phrase as a command without waiting for 'Hey you'.",
    )
    parser.set_defaults(require_wake_word=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.initial_mode == "":
        args.initial_mode = None

    run_commander(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
