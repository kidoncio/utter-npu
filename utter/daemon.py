#!/usr/bin/env python3
"""Utter: local voice dictation with Whisper on the Intel NPU.

Listens on a Unix socket at $XDG_RUNTIME_DIR/utter.sock; the command
"toggle\\n" starts or stops recording. On stop it transcribes, copies the text
with wl-copy and shows the result on the pill (pill.py, a separate process on
the system Python + GTK4).

Configuration (environment variables):
  UTTER_MODEL        model folder under models/   (whisper-large-v3-turbo-int8-ov)
  UTTER_DEVICE       OpenVINO device; falls back to CPU if it fails   (NPU)
  UTTER_LANGUAGE     Whisper language code, e.g. "en", "pt"; empty = auto-detect
  UTTER_THRESHOLD    RMS below which a recording counts as silence    (0.015)
  UTTER_MAX_SECONDS  recording auto-stops after this long             (300)
"""
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import openvino_genai as ov_genai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utter.core import FRAME, RATE, Session, State, clean_text, is_silence, level_from_pcm  # noqa: E402
from utter.i18n import strings_for  # noqa: E402
from utter.protocol import Done, Failed, Hide, Recording, Waiting, encode  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODEL = ROOT / "models" / os.environ.get("UTTER_MODEL", "whisper-large-v3-turbo-int8-ov")
DEVICE = os.environ.get("UTTER_DEVICE", "NPU")
LANGUAGE = os.environ.get("UTTER_LANGUAGE", "").strip()
THRESHOLD = float(os.environ.get("UTTER_THRESHOLD", "0.015"))
MAX_SECONDS = float(os.environ.get("UTTER_MAX_SECONDS", "300"))
SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "utter.sock"
LAYER_SHELL = "/usr/lib64/libgtk4-layer-shell.so.0"
T = strings_for(os.environ)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load_pipeline() -> ov_genai.WhisperPipeline:
    if not MODEL.is_dir():
        sys.exit(f"model not found: {MODEL} (run install.sh or see README)")
    cache = str(ROOT / "cache")
    for device in dict.fromkeys([DEVICE, "CPU"]):  # requested device, then CPU
        try:
            t0 = time.perf_counter()
            pipe = ov_genai.WhisperPipeline(str(MODEL), device, CACHE_DIR=cache)
            log(f"model {MODEL.name} loaded on {device} ({time.perf_counter() - t0:.1f}s)")
            return pipe
        except RuntimeError as e:
            log(f"could not load on {device}: {str(e).strip().splitlines()[-1]}")
    sys.exit("no usable OpenVINO device")


class PillClient:
    """The pill process; relaunched if it dies."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def send(self, msg) -> None:
        with self._lock:
            for _ in range(2):
                if self._proc is None or self._proc.poll() is not None:
                    env = dict(os.environ, LD_PRELOAD=LAYER_SHELL)
                    self._proc = subprocess.Popen(
                        ["/usr/bin/python3", str(HERE / "pill.py")],
                        stdin=subprocess.PIPE, text=True, env=env)
                try:
                    self._proc.stdin.write(encode(msg))
                    self._proc.stdin.flush()
                    return
                except BrokenPipeError:
                    self._proc = None


class Utter:
    def __init__(self, pipe):
        self.pipe = pipe
        self.pill = PillClient()
        self.session = Session(max_seconds=MAX_SECONDS)
        self.lock = threading.Lock()
        self.recorder: subprocess.Popen | None = None
        self.generation = 0  # invalidates "hide pill" timers from older sessions

    # --- commands -----------------------------------------------------------
    def toggle(self) -> str:
        with self.lock:
            action = self.session.toggle(time.monotonic())
            if action == "start":
                self.generation += 1
                self._start_recording()
            elif action == "stop":
                self._stop_recording()
        return action

    def _start_recording(self) -> None:
        self.recorder = subprocess.Popen(
            ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "--raw", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._read_audio, args=(self.recorder,), daemon=True).start()

    def _stop_recording(self) -> None:
        """Called with self.lock held. Stops pw-record and transcribes on another thread."""
        if self.recorder:
            self.recorder.terminate()
            self.recorder = None
        self.pill.send(Waiting())
        audio = self.session.take_audio()
        threading.Thread(target=self._transcribe, args=(audio, self.generation), daemon=True).start()

    # --- recording ----------------------------------------------------------
    def _read_audio(self, proc: subprocess.Popen) -> None:
        nbytes = FRAME * 2  # 100 ms of s16
        while chunk := proc.stdout.read(nbytes):
            now = time.monotonic()
            with self.lock:
                if self.recorder is not proc:
                    break
                self.session.on_audio(chunk, now)
                if self.session.state is State.RECORDING:
                    self.pill.send(Recording(level_from_pcm(chunk), self.session.elapsed(now)))
                if self.session.tick(now) == "stop":
                    log("time limit reached, stopping")
                    self._stop_recording()
                    break
        code = proc.wait()
        with self.lock:
            if self.recorder is proc and self.session.abort():
                self.recorder = None
                log(f"pw-record exited ({code}) before any audio")
                self._show_then_hide(Failed(T["no_mic"]), self.generation, hide_after=4)

    # --- transcription ------------------------------------------------------
    def _transcribe(self, audio: bytes, gen: int) -> None:
        secs = len(audio) / 2 / RATE
        try:
            if is_silence(audio, THRESHOLD):
                log(f"{secs:.1f}s of audio → silence, skipped")
                self._finish(gen, Failed(T["nothing"]), hide_after=3)
                return
            t0 = time.perf_counter()
            pcm = (np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0).tolist()
            kwargs = {"task": "transcribe"}
            if LANGUAGE:
                kwargs["language"] = f"<|{LANGUAGE}|>"
            text = clean_text(self.pipe.generate(pcm, **kwargs).texts[0])
            log(f"{secs:.1f}s of audio → {time.perf_counter() - t0:.1f}s")
            if not text:
                self._finish(gen, Failed(T["nothing"]), hide_after=3)
                return
            subprocess.run(["wl-copy", "--", text], check=True, timeout=5)
            self._finish(gen, Done(), hide_after=2)
        except Exception as e:  # noqa: BLE001 — shown on the pill and logged
            log(f"error: {e}")
            self._finish(gen, Failed(f"{T['error']}: {e}"), hide_after=5)

    def _finish(self, gen: int, msg, hide_after: float) -> None:
        with self.lock:
            self.session.finish()
            self._show_then_hide(msg, gen, hide_after)

    def _show_then_hide(self, msg, gen: int, hide_after: float) -> None:
        """Called with self.lock held."""
        self.pill.send(msg)

        def hide():
            with self.lock:
                if self.generation == gen and self.session.state is State.IDLE:
                    self.pill.send(Hide())
        threading.Timer(hide_after, hide).start()


def main() -> int:
    app = Utter(load_pipeline())

    SOCK.unlink(missing_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK))
    os.chmod(SOCK, 0o600)
    srv.listen(4)
    log(f"listening on {SOCK}")

    while True:
        conn, _ = srv.accept()
        with conn:
            cmd = conn.makefile("r", encoding="utf-8").readline().strip()
            reply = app.toggle() if cmd == "toggle" else f"unknown command: {cmd}"
            conn.sendall(reply.encode())


if __name__ == "__main__":
    sys.exit(main())
