"""Cross-platform microphone VAD and local Whisper backends."""

from __future__ import annotations

import importlib
import math
import platform
from collections import deque
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np


DEFAULT_MLX_MODEL = "mlx-community/whisper-base-mlx"
DEFAULT_FASTER_MODEL = "base"
DEFAULT_PROMPT = (
    "옵티머스, 발사, 단발, 연발, 연사, 멈춰, 안전, 경계, "
    "Optimus, fire, single, burst, stop, safe, guard"
)


class LocalTranscriber(Protocol):
    name: str

    def prepare(self, language: str) -> None:
        """Load model resources before the first real utterance."""

    def transcribe(self, audio: np.ndarray, language: str) -> tuple[str, float | None]:
        """Return transcript text and optional confidence."""


@dataclass(frozen=True)
class VadConfig:
    sample_rate: int = 16000
    block_ms: int = 30
    silence_ms: int = 420
    pre_roll_ms: int = 240
    start_confirm_ms: int = 90
    max_phrase_seconds: float = 4.0
    min_rms: float = 260.0
    ambient_multiplier: float = 3.0

    @property
    def block_frames(self) -> int:
        return max(1, int(self.sample_rate * self.block_ms / 1000))

    @property
    def silence_blocks(self) -> int:
        return max(1, math.ceil(self.silence_ms / self.block_ms))

    @property
    def pre_roll_blocks(self) -> int:
        return max(1, math.ceil(self.pre_roll_ms / self.block_ms))

    @property
    def start_confirm_blocks(self) -> int:
        return max(1, math.ceil(self.start_confirm_ms / self.block_ms))

    @property
    def max_blocks(self) -> int:
        return max(1, math.ceil(self.max_phrase_seconds * 1000 / self.block_ms))


def pcm_rms(block: bytes | np.ndarray) -> float:
    samples = (
        np.frombuffer(block, dtype=np.int16)
        if isinstance(block, bytes)
        else np.asarray(block, dtype=np.int16).reshape(-1)
    )
    if samples.size == 0:
        return 0.0
    values = samples.astype(np.float32)
    return float(np.sqrt(np.mean(values * values)))


class RmsVadRecorder:
    def __init__(self, config: VadConfig) -> None:
        self.config = config

    def calibrate(self, stream, duration: float) -> float:
        block_count = max(1, math.ceil(duration * 1000 / self.config.block_ms))
        levels = [pcm_rms(self._read(stream)) for _ in range(block_count)]
        ambient = float(np.median(levels))
        return max(self.config.min_rms, ambient * self.config.ambient_multiplier)

    def capture(self, stream, threshold: float) -> np.ndarray:
        pre_roll: deque[bytes] = deque(maxlen=self.config.pre_roll_blocks)
        recorded: list[bytes] = []
        speech_run = 0
        silence_run = 0
        started = False

        while True:
            block = self._read(stream)
            level = pcm_rms(block)

            if not started:
                pre_roll.append(block)
                speech_run = speech_run + 1 if level >= threshold else 0
                if speech_run >= self.config.start_confirm_blocks:
                    started = True
                    recorded.extend(pre_roll)
                continue

            recorded.append(block)
            silence_run = silence_run + 1 if level < threshold else 0
            if silence_run >= self.config.silence_blocks:
                break
            if len(recorded) >= self.config.max_blocks:
                break

        pcm = np.frombuffer(b"".join(recorded), dtype=np.int16)
        return pcm.astype(np.float32) / 32768.0

    @staticmethod
    def _read(stream) -> bytes:
        data, overflowed = stream.read(stream.blocksize)
        if overflowed:
            print("[AUDIO] input overflow; continuing with the newest samples")
        return bytes(data)


def open_microphone(device_index: int | None, config: VadConfig):
    try:
        sounddevice = importlib.import_module("sounddevice")
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency: sounddevice. Install the local voice requirements."
        ) from exc

    return sounddevice.RawInputStream(
        samplerate=config.sample_rate,
        blocksize=config.block_frames,
        device=device_index,
        channels=1,
        dtype="int16",
    )


def list_input_devices() -> list[tuple[int, str, float]]:
    sounddevice = importlib.import_module("sounddevice")
    devices = []
    for index, device in enumerate(sounddevice.query_devices()):
        if device["max_input_channels"] > 0:
            devices.append((index, str(device["name"]), float(device["default_samplerate"])))
    return devices


class MlxWhisperTranscriber:
    name = "mlx-whisper"

    def __init__(self, model: str = DEFAULT_MLX_MODEL, prompt: str = DEFAULT_PROMPT) -> None:
        if platform.system() != "Darwin" or platform.machine() not in ("arm64", "aarch64"):
            raise SystemExit("MLX Whisper requires Apple Silicon macOS.")
        try:
            self._mlx_whisper = importlib.import_module("mlx_whisper")
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "Missing dependency: mlx-whisper. Install requirements_voice_mlx.txt."
            ) from exc
        self.model = model
        self.prompt = prompt

    def prepare(self, language: str) -> None:
        # The public transcribe API uses an in-process ModelHolder cache. Running
        # a short silent clip moves model download/load cost ahead of the first
        # user command without depending on mlx-whisper internals.
        self.transcribe(np.zeros(1600, dtype=np.float32), language)

    def transcribe(self, audio: np.ndarray, language: str) -> tuple[str, float | None]:
        result = self._mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.model,
            language=language,
            initial_prompt=self.prompt,
            temperature=0.0,
            condition_on_previous_text=False,
            verbose=None,
        )
        return str(result.get("text", "")).strip(), _result_confidence(result)


class FasterWhisperTranscriber:
    name = "faster-whisper"

    def __init__(
        self,
        model: str = DEFAULT_FASTER_MODEL,
        *,
        device: str = "auto",
        compute_type: str = "auto",
        prompt: str = DEFAULT_PROMPT,
    ) -> None:
        try:
            faster_whisper = importlib.import_module("faster_whisper")
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "Missing dependency: faster-whisper. Install requirements_voice_windows.txt."
            ) from exc
        self.model = faster_whisper.WhisperModel(
            model,
            device=device,
            compute_type=compute_type,
        )
        self.prompt = prompt

    def prepare(self, language: str) -> None:
        # WhisperModel loads the model in __init__; this method keeps the common
        # startup interface explicit across platforms.
        return None

    def transcribe(self, audio: np.ndarray, language: str) -> tuple[str, float | None]:
        segments, _ = self.model.transcribe(
            audio,
            language=language,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=self.prompt,
            vad_filter=False,
        )
        segment_list = list(segments)
        text = " ".join(segment.text.strip() for segment in segment_list).strip()
        logprobs = [
            float(segment.avg_logprob)
            for segment in segment_list
            if getattr(segment, "avg_logprob", None) is not None
        ]
        confidence = math.exp(sum(logprobs) / len(logprobs)) if logprobs else None
        return text, confidence


def select_backend(
    backend: str,
    *,
    model: str | None = None,
    device: str = "auto",
    compute_type: str = "auto",
) -> LocalTranscriber:
    selected = backend
    if selected == "auto":
        selected = (
            "mlx"
            if platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64")
            else "faster-whisper"
        )

    if selected == "mlx":
        return MlxWhisperTranscriber(model or DEFAULT_MLX_MODEL)
    if selected == "faster-whisper":
        return FasterWhisperTranscriber(
            model or DEFAULT_FASTER_MODEL,
            device=device,
            compute_type=compute_type,
        )
    raise ValueError(f"Unsupported backend: {backend}")


def _result_confidence(result: dict) -> float | None:
    logprobs = [
        float(segment["avg_logprob"])
        for segment in result.get("segments", ())
        if segment.get("avg_logprob") is not None
    ]
    if not logprobs:
        return None
    return math.exp(sum(logprobs) / len(logprobs))


def process_transcript(
    transcript: str,
    *,
    require_wake_word: bool,
    is_awake: bool,
    wake_words: tuple[str, ...],
    match_intent: Callable[[str], str | None],
    is_wake_phrase: Callable[[str, tuple[str, ...]], bool],
    command_from_wake_phrase: Callable[[str, tuple[str, ...]], str | None],
) -> tuple[str | None, bool]:
    """Return a mode to write and the next wake state."""
    if require_wake_word and not is_awake:
        if not is_wake_phrase(transcript, wake_words):
            return None, False
        mode = command_from_wake_phrase(transcript, wake_words)
        return (mode, False) if mode is not None else (None, True)

    mode = match_intent(transcript)
    if require_wake_word:
        return mode, mode is None
    return mode, True
