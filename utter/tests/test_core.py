"""Lógica do Utter que não depende de hardware."""
import numpy as np

from utter.core import Session, State, level_from_pcm, is_silence, clean_text


def pcm(amplitude: float, seconds: float = 0.1) -> bytes:
    n = int(16000 * seconds)
    t = np.arange(n) / 16000
    return (np.sin(2 * np.pi * 440 * t) * amplitude * 32767).astype(np.int16).tobytes()


# --- Sessão: idle → starting → recording → transcribing → idle -------------

def test_first_toggle_starts_recording_but_pill_waits_for_audio():
    s = Session(max_seconds=300)
    assert s.toggle(now=0.0) == "start"
    assert s.state is State.STARTING


def test_first_audio_chunk_means_mic_is_live():
    s = Session(max_seconds=300)
    s.toggle(now=0.0)
    s.on_audio(pcm(0.1), now=0.2)
    assert s.state is State.RECORDING


def test_second_toggle_stops_and_returns_all_audio():
    s = Session(max_seconds=300)
    s.toggle(now=0.0)
    s.on_audio(pcm(0.1), now=0.2)
    s.on_audio(pcm(0.1), now=0.3)
    assert s.toggle(now=1.0) == "stop"
    assert s.state is State.TRANSCRIBING
    assert len(s.take_audio()) == 2 * 1600 * 2  # 2 chunks × 1600 amostras × 2 bytes


def test_toggle_while_transcribing_is_ignored():
    s = Session(max_seconds=300)
    s.toggle(now=0.0)
    s.toggle(now=1.0)
    assert s.toggle(now=1.5) == "ignore"
    assert s.state is State.TRANSCRIBING


def test_finish_returns_to_idle_and_next_toggle_starts_fresh():
    s = Session(max_seconds=300)
    s.toggle(now=0.0)
    s.on_audio(pcm(0.1), now=0.2)
    s.toggle(now=1.0)
    s.take_audio()
    s.finish()
    assert s.state is State.IDLE
    assert s.toggle(now=5.0) == "start"
    assert s.take_audio() == b""


def test_elapsed_counts_from_first_audio_not_from_keypress():
    s = Session(max_seconds=300)
    s.toggle(now=10.0)
    s.on_audio(pcm(0.1), now=10.5)
    assert s.elapsed(now=12.5) == 2.0


def test_tick_auto_stops_after_max_seconds():
    s = Session(max_seconds=5)
    s.toggle(now=0.0)
    s.on_audio(pcm(0.1), now=0.0)
    assert s.tick(now=4.9) is None
    assert s.tick(now=5.0) == "stop"
    assert s.state is State.TRANSCRIBING


def test_audio_after_stop_is_dropped():
    s = Session(max_seconds=300)
    s.toggle(now=0.0)
    s.on_audio(pcm(0.1), now=0.1)
    s.toggle(now=1.0)
    s.on_audio(pcm(0.1), now=1.1)  # resto que chega do pw-record
    assert len(s.take_audio()) == 1600 * 2


# --- Medidor de nível -------------------------------------------------------

def test_level_is_zero_for_digital_silence():
    assert level_from_pcm(b"\x00\x00" * 1600) == 0.0


def test_level_is_one_for_full_scale():
    assert level_from_pcm(pcm(1.0)) == 1.0


def test_level_for_measured_room_noise_is_low_and_speech_is_high():
    # Valores medidos neste notebook: ruído ambiente RMS≈0,004; fala RMS≈0,09.
    noise = (np.random.default_rng(0).normal(0, 0.004, 1600) * 32767).astype(np.int16)
    speech = pcm(0.09 * np.sqrt(2))  # senoide com RMS 0,09
    assert level_from_pcm(noise.tobytes()) < 0.25
    assert level_from_pcm(speech) > 0.6


def test_level_handles_empty_chunk():
    assert level_from_pcm(b"") == 0.0


# --- Silêncio e limpeza de texto -------------------------------------------

def test_quiet_recording_is_silence():
    assert is_silence(pcm(0.004 * np.sqrt(2), seconds=3), threshold=0.015)


def test_one_loud_word_in_quiet_recording_is_not_silence():
    audio = pcm(0.004, seconds=2) + pcm(0.1, seconds=0.2) + pcm(0.004, seconds=1)
    assert not is_silence(audio, threshold=0.015)


def test_too_short_recording_is_silence():
    assert is_silence(pcm(0.5, seconds=0.2), threshold=0.015)


def test_clean_text_strips_and_drops_punctuation_only():
    assert clean_text("  Olá, mundo. ") == "Olá, mundo."
    assert clean_text(" . ") == ""
    assert clean_text("…!") == ""


def test_abort_when_mic_never_delivered_audio_returns_to_idle():
    s = Session(max_seconds=300)
    s.toggle(now=0.0)
    assert s.abort() is True  # pw-record died before any audio
    assert s.state is State.IDLE


def test_abort_is_noop_once_recording():
    s = Session(max_seconds=300)
    s.toggle(now=0.0)
    s.on_audio(pcm(0.1), now=0.1)
    assert s.abort() is False
    assert s.state is State.RECORDING
