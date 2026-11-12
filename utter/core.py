"""Hardware-independent Utter logic: session state machine, level meter, silence.

Audio is always PCM s16le, 16 kHz, mono.
"""
import enum
import math

import numpy as np

RATE = 16000
FRAME = RATE // 10  # 100 ms
MIN_SECONDS = 0.3


class State(enum.Enum):
    IDLE = "idle"
    STARTING = "starting"          # recorder launched, no audio yet
    RECORDING = "recording"        # microphone is delivering audio: user may speak
    TRANSCRIBING = "transcribing"


class Session:
    """State machine for one dictation. `now` is injected to keep it testable."""

    def __init__(self, max_seconds: float):
        self.max_seconds = max_seconds
        self.state = State.IDLE
        self._chunks: list[bytes] = []
        self._t_first_audio: float | None = None

    def toggle(self, now: float) -> str:
        """Returns "start", "stop" or "ignore" (pressed while transcribing)."""
        if self.state is State.IDLE:
            self.state = State.STARTING
            self._chunks = []
            self._t_first_audio = None
            return "start"
        if self.state in (State.STARTING, State.RECORDING):
            self.state = State.TRANSCRIBING
            return "stop"
        return "ignore"

    def on_audio(self, chunk: bytes, now: float) -> None:
        if self.state is State.STARTING:
            self.state = State.RECORDING
            self._t_first_audio = now
        if self.state is State.RECORDING:
            self._chunks.append(chunk)

    def abort(self) -> bool:
        """Recorder died before delivering any audio. True if the session was reset."""
        if self.state is State.STARTING:
            self.state = State.IDLE
            return True
        return False

    def elapsed(self, now: float) -> float:
        return 0.0 if self._t_first_audio is None else now - self._t_first_audio

    def tick(self, now: float) -> str | None:
        if self.state is State.RECORDING and self.elapsed(now) >= self.max_seconds:
            self.state = State.TRANSCRIBING
            return "stop"
        return None

    def take_audio(self) -> bytes:
        audio, self._chunks = b"".join(self._chunks), []
        return audio

    def finish(self) -> None:
        self.state = State.IDLE


def _to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def level_from_pcm(pcm: bytes, floor_db: float = -60.0, ceil_db: float = -6.0) -> float:
    """Loudness 0..1 on a dB scale (like a VU meter), for the pill's bars."""
    a = _to_float(pcm)
    if a.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(a * a)))
    if rms <= 0.0:
        return 0.0
    db = 20 * math.log10(rms)
    return min(1.0, max(0.0, (db - floor_db) / (ceil_db - floor_db)))


def is_silence(pcm: bytes, threshold: float) -> bool:
    """True if too short, or if no 100 ms frame exceeds the RMS threshold.

    Whisper hallucinates text on silence ("Thank you.", "."), so we skip it.
    """
    a = _to_float(pcm)
    if a.size < RATE * MIN_SECONDS:
        return True
    n = a.size // FRAME * FRAME
    rms = np.sqrt((a[:n].reshape(-1, FRAME) ** 2).mean(axis=1))
    return float(rms.max()) < threshold


def clean_text(text: str) -> str:
    text = text.strip()
    return text if any(ch.isalnum() for ch in text) else ""
