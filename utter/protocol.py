"""Messages from the Utter daemon to the pill, one per line.

Standard library only: imported by both the daemon (venv Python 3.12 with
OpenVINO) and the pill (system Python with GTK4).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Recording:
    level: float    # 0..1, microphone loudness
    elapsed: float  # seconds recorded


@dataclass(frozen=True)
class Waiting:
    pass


@dataclass(frozen=True)
class Done:
    pass


@dataclass(frozen=True)
class Failed:
    message: str


@dataclass(frozen=True)
class Hide:
    pass


Message = Recording | Waiting | Done | Failed | Hide


def encode(msg: Message) -> str:
    match msg:
        case Recording(level, elapsed):
            body = f"rec {level:.3f} {elapsed:.2f}"
        case Waiting():
            body = "wait"
        case Done():
            body = "done"
        case Failed(message):
            body = "fail " + " ".join(message.split())
        case Hide():
            body = "hide"
    return body + "\n"


def decode(line: str) -> Message | None:
    kind, _, rest = line.strip().partition(" ")
    try:
        match kind:
            case "rec":
                level, elapsed = rest.split()
                return Recording(float(level), float(elapsed))
            case "wait":
                return Waiting()
            case "done":
                return Done()
            case "fail":
                return Failed(rest)
            case "hide":
                return Hide()
    except ValueError:
        return None
    return None


class LineBuffer:
    """Splits a byte stream into lines. The pill reads raw bytes, because a buffered
    readline() would swallow a second waiting line without waking GLib again."""

    def __init__(self):
        self._pending = b""

    def feed(self, data: bytes) -> list[str]:
        *lines, self._pending = (self._pending + data).split(b"\n")
        return [line.decode("utf-8", "replace") for line in lines]
