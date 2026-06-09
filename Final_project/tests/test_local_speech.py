import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gesture_bt"))

from local_speech import (
    MlxWhisperTranscriber,
    RmsVadRecorder,
    VadConfig,
    pcm_rms,
    process_transcript,
    select_backend,
)
from voice_commander import command_from_wake_phrase, is_wake_phrase, match_intent


class FakeStream:
    def __init__(self, blocks, blocksize):
        self.blocks = iter(blocks)
        self.blocksize = blocksize

    def read(self, _frames):
        return next(self.blocks), False


def pcm_block(value, frames):
    return np.full(frames, value, dtype=np.int16).tobytes()


class LocalSpeechTests(unittest.TestCase):
    def test_pcm_rms_distinguishes_silence_and_speech(self):
        self.assertEqual(pcm_rms(pcm_block(0, 10)), 0.0)
        self.assertAlmostEqual(pcm_rms(pcm_block(1000, 10)), 1000.0, delta=1.0)

    def test_vad_keeps_pre_roll_and_stops_after_silence(self):
        config = VadConfig(
            sample_rate=1000,
            block_ms=100,
            pre_roll_ms=200,
            start_confirm_ms=200,
            silence_ms=200,
            max_phrase_seconds=3,
        )
        blocks = [
            pcm_block(0, config.block_frames),
            pcm_block(0, config.block_frames),
            pcm_block(1000, config.block_frames),
            pcm_block(1000, config.block_frames),
            pcm_block(1000, config.block_frames),
            pcm_block(0, config.block_frames),
            pcm_block(0, config.block_frames),
        ]
        audio = RmsVadRecorder(config).capture(
            FakeStream(blocks, config.block_frames),
            threshold=500,
        )

        self.assertGreater(len(audio), config.block_frames * 4)
        self.assertAlmostEqual(float(np.max(audio)), 1000 / 32768, places=4)

    def test_unknown_local_transcript_does_not_change_mode(self):
        mode, awake = process_transcript(
            "오늘 날씨가 좋다",
            require_wake_word=False,
            is_awake=True,
            wake_words=("옵티머스",),
            match_intent=match_intent,
            is_wake_phrase=is_wake_phrase,
            command_from_wake_phrase=command_from_wake_phrase,
        )
        self.assertIsNone(mode)
        self.assertTrue(awake)

    def test_wake_and_command_state_matches_online_commander(self):
        kwargs = {
            "require_wake_word": True,
            "wake_words": ("옵티머스", "옵티 머스", "optimus"),
            "match_intent": match_intent,
            "is_wake_phrase": is_wake_phrase,
            "command_from_wake_phrase": command_from_wake_phrase,
        }
        self.assertEqual(
            process_transcript("옵티머스 발사", is_awake=False, **kwargs),
            ("single", False),
        )
        self.assertEqual(
            process_transcript("옵티머스", is_awake=False, **kwargs),
            (None, True),
        )
        self.assertEqual(
            process_transcript("Optimus, 발사", is_awake=False, **kwargs),
            ("single", False),
        )
        self.assertEqual(
            process_transcript("연발", is_awake=True, **kwargs),
            ("burst", False),
        )

    def test_auto_backend_selects_mlx_on_apple_silicon(self):
        fake_mlx = types.SimpleNamespace(transcribe=lambda *args, **kwargs: {"text": ""})
        with (
            mock.patch("local_speech.platform.system", return_value="Darwin"),
            mock.patch("local_speech.platform.machine", return_value="arm64"),
            mock.patch("local_speech.importlib.import_module", return_value=fake_mlx),
        ):
            backend = select_backend("auto")
        self.assertEqual(backend.name, "mlx-whisper")

    def test_mlx_prepare_warms_model_with_short_silence(self):
        fake_mlx = types.SimpleNamespace(
            transcribe=mock.Mock(return_value={"text": "", "segments": []})
        )
        with (
            mock.patch("local_speech.platform.system", return_value="Darwin"),
            mock.patch("local_speech.platform.machine", return_value="arm64"),
            mock.patch("local_speech.importlib.import_module", return_value=fake_mlx),
        ):
            backend = MlxWhisperTranscriber()
            backend.prepare("ko")

        audio = fake_mlx.transcribe.call_args.args[0]
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.shape, (1600,))
        self.assertEqual(fake_mlx.transcribe.call_args.kwargs["language"], "ko")

    def test_auto_backend_selects_faster_whisper_on_windows(self):
        fake_model = mock.Mock()
        fake_module = types.SimpleNamespace(WhisperModel=mock.Mock(return_value=fake_model))
        with (
            mock.patch("local_speech.platform.system", return_value="Windows"),
            mock.patch("local_speech.platform.machine", return_value="AMD64"),
            mock.patch("local_speech.importlib.import_module", return_value=fake_module),
        ):
            backend = select_backend("auto", model="base", device="cpu", compute_type="int8")

        self.assertEqual(backend.name, "faster-whisper")
        fake_module.WhisperModel.assert_called_once_with(
            "base",
            device="cpu",
            compute_type="int8",
        )


if __name__ == "__main__":
    unittest.main()
