"""Pill strings, picked from the desktop locale (Portuguese for pt*, else English).

Standard library only: imported by both the daemon and the pill.
"""
from collections.abc import Mapping

STRINGS = {
    "en": {
        "speak": "Speak now",
        "transcribing": "Transcribing…",
        "copied": "Copied — Ctrl+V",
        "nothing": "Nothing recognized",
        "no_mic": "Microphone unavailable",
        "error": "Error",
    },
    "pt": {
        "speak": "Fale agora",
        "transcribing": "Transcrevendo…",
        "copied": "Copiado — Ctrl+V",
        "nothing": "Nada reconhecido",
        "no_mic": "Microfone indisponível",
        "error": "Erro",
    },
}


def strings_for(env: Mapping[str, str]) -> dict[str, str]:
    # Same precedence as gettext: LC_ALL > LC_MESSAGES > LANG.
    locale = env.get("LC_ALL") or env.get("LC_MESSAGES") or env.get("LANG") or ""
    return STRINGS.get(locale[:2].lower(), STRINGS["en"])
