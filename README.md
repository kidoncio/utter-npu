# Utter

**Local push-to-talk voice dictation for Linux, running Whisper on the Intel NPU.**

Press a shortcut, speak, press it again. The text lands in your clipboard, ready
to paste into a chat box, an editor or a terminal. Nothing leaves your machine,
and neither your GPU nor your CPU is busy while you work.

```
 Meta+V  ──►  ● Speak now  ▌▌▐▌▌  0:04      (red: the mic is live)
 Meta+V  ──►  ◌ Transcribing…               (amber: wait)
         ──►  ✓ Copied — Ctrl+V             (green: paste it)
```

The status pill sits at the top of the screen, above every window. It never takes
keyboard focus, and clicks pass through it.

## Why

I wanted to dictate long prompts to AI assistants such as claude.ai and Claude Code in
the terminal, without typing them, without sending audio to a third party, and
without slowing down the machine I'm developing on.

On a laptop with an **Intel Core Ultra** (Meteor Lake, Lunar Lake, Arrow Lake), there
are three places to run speech-to-text:

| | Speed (13 s of speech, Whisper large-v3-turbo int8) | Cost while you work |
|---|---|---|
| dGPU (RTX 5070 Laptop, 8 GB) | not measured | competes with local LLMs and games for VRAM, spins up fans |
| CPU | 2.5 s | competes with compilers, tests and the IDE |
| **NPU** (Intel AI Boost) | **2.5 s** (5.4× real time) | **idle otherwise; low power; leaves CPU and GPU free** |

The NPU matches the CPU on speed and costs nothing in contention. That is exactly
what you want from something that runs in the background all day.

## Requirements

Tested on:

| Component | Version |
|---|---|
| Distro | Bazzite 45 (Fedora Kinoite, `bazzite-dx-nvidia` image) |
| Kernel | 7.3 (`intel_vpu` driver + `intel-npu-firmware`, both shipped by Bazzite) |
| CPU / NPU | Intel Core Ultra 9 275HX (Arrow Lake-HX), NPU 3720, PCI ID `0xad1d` |
| Desktop | KDE Plasma 6.8, Wayland |
| Audio | PipeWire 1.6 |

Any Intel Core Ultra on a recent Fedora Atomic desktop (Bazzite, Aurora, Bluefin,
Kinoite or Silverblue) should work. The status pill needs a Wayland compositor with
`wlr-layer-shell`, which KDE Plasma 6, Sway, Hyprland and others provide. GNOME does
not, so there the pill won't show, but dictation still works.

### What gets installed

The host stays untouched apart from three small files. Everything else lives in a
[distrobox](https://distrobox.it/) running Fedora 45.

**Host** (already on Bazzite): `distrobox`, `podman`, `systemd`, `python3`,
`notify-send`, `gdbus`, and the kernel's `intel_vpu` driver exposing `/dev/accel/accel0`.

**Container** (`dnf`):

| Package | Why |
|---|---|
| `oneapi-level-zero` | Level Zero loader that OpenVINO uses to reach the NPU |
| `tbb` | runtime dependency of the NPU compiler |
| **Intel `linux-npu-driver` 1.38.0** (from GitHub, not dnf) | NPU user-space driver **and compiler**; see below |
| `gtk4`, `gtk4-layer-shell`, `python3-gobject`, `python3-cairo` | the status pill |
| `pipewire-utils` | `pw-record` for microphone capture |
| `wl-clipboard` | `wl-copy` |
| `ffmpeg-free` | only for `tools/transcribe.py` |
| `python3-pip`, `binutils` | bootstrap `uv`; unpack Intel's `.deb` files |

**Python 3.12 venv** (`requirements.txt`): `openvino` 2026.4.1, `openvino-genai`
2026.4.1, `numpy`, `huggingface_hub`, `pytest`. Python 3.12 is used because Fedora 45
ships 3.15, which OpenVINO wheels don't support yet.

**Model:** [`OpenVINO/whisper-large-v3-turbo-int8-ov`](https://huggingface.co/OpenVINO/whisper-large-v3-turbo-int8-ov), about 800 MB.

### The one non-obvious part: the NPU compiler

Fedora packages Intel's NPU user-space driver as `intel-npu-driver`, but **without
the NPU compiler** (`libopenvino_intel_npu_compiler.so`). OpenVINO still lists
`NPU` as a device, yet every model fails to compile:

```
Compilation failed. Level0 pfnCreate2 result: ZE_RESULT_ERROR_UNSUPPORTED_FEATURE
```

A telltale sign is `core.get_property("NPU", "NPU_COMPILER_VERSION")` returning `0`.
The fix is to use the libraries from
[Intel's GitHub release](https://github.com/intel/linux-npu-driver/releases)
(`intel-level-zero-npu` + `intel-driver-compiler-npu`) instead. `install.sh` does
this inside the container and pins the tarball's SHA-256.

## Install

```bash
git clone https://github.com/kidoncio/utter-npu.git ~/utter-npu
cd ~/utter-npu
./install.sh --enable --shortcut Meta+V
```

The installer is idempotent, so it is safe to re-run. It:

1. checks for `/dev/accel/accel0` and a Wayland session;
2. creates a distrobox called `utter` (Fedora 45) and installs the packages above;
3. installs Intel's NPU driver and compiler, after verifying the checksum;
4. creates `.venv` with Python 3.12 and OpenVINO;
5. downloads the Whisper model into `models/`;
6. runs an **NPU self-test**, compiling a tiny model on the NPU;
7. installs `~/.local/bin/utter-toggle`, a `.desktop` entry and the
   `utter.service` systemd user unit;
8. with `--enable`, starts the service now and on every login;
9. with `--shortcut`, binds a KDE global shortcut. It refuses keys that are
   already taken. On Plasma, `Meta+V` usually opens the clipboard history, so
   either move that one in System Settings → Keyboard → Shortcuts or pick another key.

Options: `--container NAME`, `--language CODE` (`en`, `pt`, … or `auto`; the default
comes from `$LANG`), `--shortcut KEYS`, `--enable`. Run `./install.sh --help` for details.

On another desktop, bind any global shortcut to `~/.local/bin/utter-toggle`.

## Use

1. Press the shortcut. Wait for the red **● Speak now** pill. It only appears once
   the microphone is actually delivering audio, and the bars show your voice level.
2. Speak.
3. Press the shortcut again. The pill turns amber while Whisper runs, then green.
4. Paste with **Ctrl+V**, or **Ctrl+Shift+V** in most terminals.

If you press the shortcut while it is transcribing, nothing happens. Recording stops
by itself after 5 minutes. Silence is detected and skipped, because Whisper tends to
invent text such as "Thank you." on empty audio. The pill speaks Portuguese on `pt_*`
locales and English otherwise.

## Configure

Set these with `systemctl --user edit utter` (`[Service]` → `Environment=...`):

| Variable | Default | Meaning |
|---|---|---|
| `UTTER_LANGUAGE` | from `$LANG` at install | Whisper language code. Empty means auto-detect, which is less reliable on short clips. |
| `UTTER_DEVICE` | `NPU` | OpenVINO device. Falls back to `CPU` automatically if it fails. |
| `UTTER_MODEL` | `whisper-large-v3-turbo-int8-ov` | folder under `models/` |
| `UTTER_THRESHOLD` | `0.015` | RMS below which a recording counts as silence. Raise it in noisy rooms. |
| `UTTER_MAX_SECONDS` | `300` | recording auto-stop |

Other models from the [OpenVINO Whisper collection](https://huggingface.co/OpenVINO)
work too. For example, `whisper-small-int8-ov` is faster, but much worse at non-English:

```bash
distrobox enter utter -- ~/utter-npu/.venv/bin/hf download \
    OpenVINO/whisper-small-int8-ov --local-dir ~/utter-npu/models/whisper-small-int8-ov
```

## Benchmarks

13.3 s of Brazilian Portuguese speech, on a Core Ultra 9 275HX:

| Model | NPU | CPU | Quality |
|---|---|---|---|
| whisper-small int8 | 1.4 s | 1.2 s | poor in Portuguese |
| **whisper-large-v3-turbo int8** | **2.5 s** | 2.5 s | near perfect |

The first load on the NPU compiles the model, which takes about 100 s for turbo.
The compiled blob is cached in `cache/` (about 2 GB), so later starts take about 3 s.

To reproduce, or to try your own audio:

```bash
distrobox enter utter -- ~/utter-npu/.venv/bin/python ~/utter-npu/tools/transcribe.py \
    some.mp3 --device NPU --language pt
```

## How it works

```
 KDE shortcut ──► utter-toggle (host) ──"toggle"──► utter.sock
                                                       │
            ┌──────────────── utter.service (distrobox) ┴────────────────┐
            │ daemon.py                                                  │
            │   pw-record ──PCM──► level meter ──► pill.py (GTK4 layer   │
            │       │                               shell, system Python)│
            │       └──► Whisper (OpenVINO GenAI, NPU) ──► wl-copy       │
            └────────────────────────────────────────────────────────────┘
```

- `utter/core.py` is the state machine (idle → starting → recording →
  transcribing), the level meter and silence detection. It is pure logic and unit-tested.
- `utter/protocol.py` holds the line-based messages from the daemon to the pill.
- `utter/daemon.py` holds the socket server, recording, transcription and clipboard.
- `utter/pill.py` is the overlay. It runs on the container's system Python, because
  PyGObject is built for Fedora's Python 3.15, while OpenVINO needs 3.12.
- `contrib/` holds the systemd unit template, the toggle script, the `.desktop`
  entry and the KDE shortcut helper.

Two lessons learned the hard way:

- **KDE runs shortcut commands in transient systemd units, which kill child
  processes when the command exits.** Anything long-lived, such as the recorder or
  `wl-copy` serving the clipboard, must therefore live in the daemon, not in the
  toggle script.
- **Stopping `distrobox enter` does not stop the process inside the container.**
  The unit's `ExecStopPost` cleans up.

## Troubleshooting

| Symptom | Check |
|---|---|
| "Utter is not running" notification | `systemctl --user status utter`, `journalctl --user -u utter -n 50` |
| Log says `could not load on NPU … UNSUPPORTED_FEATURE` | NPU compiler missing; re-run `./install.sh` |
| Log says `loaded on CPU` | NPU failed; see the line above it. Utter still works on the CPU. |
| Pill shows "Microphone unavailable" | `pw-record --list-targets`; check the default source in your sound settings |
| "Nothing recognized" while you spoke | lower `UTTER_THRESHOLD` (e.g. `0.008`) |
| Text appears when you didn't speak | raise `UTTER_THRESHOLD` (e.g. `0.03`) |
| No pill at all | your compositor lacks `wlr-layer-shell` (GNOME); dictation still works |

## Development

```bash
distrobox enter utter -- bash -c 'cd ~/utter-npu && .venv/bin/pytest -q'
```

## Privacy note

`distrobox enter` passes your whole environment to `podman exec` as command-line
arguments, so any local process can read it through `ps`. If you keep secrets in
environment variables, be aware that this applies to every distrobox command, not
just Utter.

## License

[MIT](LICENSE)
