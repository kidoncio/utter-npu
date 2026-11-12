#!/usr/bin/env python3
"""Transcribe an audio file with Whisper (OpenVINO) and report timing.

Useful to benchmark NPU vs CPU or to try another model.

  tools/transcribe.py AUDIO [--model whisper-small-int8-ov] [--device NPU|CPU] [--language pt]
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import openvino_genai as ov_genai

ROOT = Path(__file__).resolve().parent.parent


def load_audio(path: str) -> list[float]:
    """Decode any format to 16 kHz mono float PCM via ffmpeg."""
    pcm = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path,
         "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(pcm, dtype=np.float32).tolist()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("audio")
    p.add_argument("--model", default="whisper-large-v3-turbo-int8-ov",
                   help="folder name under models/")
    p.add_argument("--device", default="NPU")
    p.add_argument("--language", default="", help='e.g. "en", "pt"; empty = auto-detect')
    a = p.parse_args()

    t0 = time.perf_counter()
    pipe = ov_genai.WhisperPipeline(str(ROOT / "models" / a.model), a.device,
                                    CACHE_DIR=str(ROOT / "cache"))
    t_load = time.perf_counter() - t0

    audio = load_audio(a.audio)
    duration = len(audio) / 16000

    kwargs = {"task": "transcribe", "return_timestamps": True}
    if a.language:
        kwargs["language"] = f"<|{a.language}|>"
    t0 = time.perf_counter()
    res = pipe.generate(audio, **kwargs)
    t_infer = time.perf_counter() - t0

    for c in res.chunks or []:
        print(f"[{c.start_ts:6.1f}s → {c.end_ts:6.1f}s] {c.text.strip()}")
    if not res.chunks:
        print(res.texts[0].strip())

    print(f"\n# {a.model} on {a.device}: load {t_load:.1f}s, audio {duration:.1f}s, "
          f"inference {t_infer:.1f}s ({duration / t_infer:.1f}x real time)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
