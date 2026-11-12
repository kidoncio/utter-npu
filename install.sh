#!/usr/bin/env bash
# Utter installer for Bazzite / Fedora Atomic with an Intel Core Ultra NPU.
#
# Everything heavy goes into a Fedora distrobox; the host only gets a systemd
# user unit, a small toggle script and a .desktop entry. Safe to re-run.
#
#   ./install.sh [--container NAME] [--language CODE] [--shortcut KEYS] [--enable]
#
#   --container NAME   distrobox name                       (default: utter)
#   --language CODE    Whisper language, e.g. en, pt; "auto" to detect
#                      (default: from $LANG, e.g. pt_BR → pt; C/POSIX → auto)
#   --shortcut KEYS    register a KDE global shortcut, e.g. Meta+V
#   --enable           enable and start the service now and on every login
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER=utter
LANGUAGE=""
SHORTCUT=""
ENABLE=0
IMAGE=registry.fedoraproject.org/fedora:45
MODEL=whisper-large-v3-turbo-int8-ov

# Intel's Linux NPU driver. Fedora's intel-npu-driver package ships without the
# NPU compiler, so every model compile fails (ZE_RESULT_ERROR_UNSUPPORTED_FEATURE).
DRIVER_VERSION=1.38.0
DRIVER_URL="https://github.com/intel/linux-npu-driver/releases/download/v${DRIVER_VERSION}/linux-npu-driver-v1.38.0.20260910-34487311128-ubuntu2604.tar.gz"
DRIVER_SHA256=83685e6d92f4db1ca65e442846d487c7feb1335634b33994292ceb38f933bcc7

while [[ $# -gt 0 ]]; do
    case $1 in
        --container) CONTAINER=$2; shift 2 ;;
        --language) LANGUAGE=$2; shift 2 ;;
        --shortcut) SHORTCUT=$2; shift 2 ;;
        --enable) ENABLE=1; shift ;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
inbox() { distrobox enter "$CONTAINER" -- bash -c "$1"; }

if [[ -z $LANGUAGE ]]; then
    LANGUAGE=${LANG:-C}; LANGUAGE=${LANGUAGE:0:2}
    [[ $LANGUAGE =~ ^[a-z]{2}$ ]] || LANGUAGE=auto
fi
[[ $LANGUAGE == auto ]] && LANGUAGE=""

# --- 1. host checks ------------------------------------------------------------
step "Checking host"
command -v distrobox >/dev/null || die "distrobox not found (it ships with Bazzite)"
[[ -e /dev/accel/accel0 ]] || die "no NPU device at /dev/accel/accel0 — Intel Core Ultra with the intel_vpu kernel driver required"
[[ -w /dev/accel/accel0 ]] || warn "/dev/accel/accel0 is not writable by you; add yourself to the 'render' group"
[[ ${XDG_SESSION_TYPE:-} == wayland ]] || warn "not a Wayland session; the pill needs a compositor with wlr-layer-shell (KDE Plasma 6, Sway, Hyprland…)"
echo "NPU: $(cat /sys/class/accel/accel0/device/device 2>/dev/null || echo unknown) via $(basename "$(readlink -f /sys/class/accel/accel0/device/driver)")"

# --- 2. container --------------------------------------------------------------
step "Distrobox '$CONTAINER' ($IMAGE)"
if ! distrobox list 2>/dev/null | awk -F'|' '{gsub(/ /,"",$2); print $2}' | grep -qx "$CONTAINER"; then
    distrobox create --name "$CONTAINER" --image "$IMAGE" --yes
fi
inbox 'sudo dnf install -y -q oneapi-level-zero tbb gtk4 gtk4-layer-shell python3-gobject python3-cairo \
                               pipewire-utils wl-clipboard ffmpeg-free python3-pip binutils'
inbox 'rpm -q intel-npu-driver >/dev/null 2>&1 && sudo dnf remove -y -q intel-npu-driver || true'

# --- 3. Intel NPU user-space driver + compiler --------------------------------
step "Intel NPU driver $DRIVER_VERSION"
if inbox "test -e /usr/lib64/libze_intel_npu.so.$DRIVER_VERSION -a -e /usr/lib64/libopenvino_intel_npu_compiler.so"; then
    echo "already installed"
else
    # Under $HOME: always shared with the container (/tmp may not be).
    mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}"
    tmp=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" utter-driver.XXXX); trap 'rm -rf "$tmp"' EXIT
    curl -fL --progress-bar -o "$tmp/driver.tgz" "$DRIVER_URL"
    echo "$DRIVER_SHA256  $tmp/driver.tgz" | sha256sum -c --quiet || die "driver checksum mismatch"
    tar -xzf "$tmp/driver.tgz" -C "$tmp"
    inbox "set -e; cd '$tmp'; mkdir -p x
           for deb in intel-level-zero-npu_*.deb intel-driver-compiler-npu_*.deb; do
               ar x \"\$deb\" && tar -xf data.tar.* -C x && rm -f data.tar.* control.tar.* debian-binary
           done
           sudo install -m 0644 x/usr/lib/x86_64-linux-gnu/lib* /usr/lib64/
           sudo ln -sf libze_intel_npu.so.$DRIVER_VERSION /usr/lib64/libze_intel_npu.so.1
           sudo ldconfig"
fi

# --- 4. Python environment -----------------------------------------------------
step "Python 3.12 venv with OpenVINO"
inbox "set -e; export PATH=\$HOME/.local/bin:\$PATH
       command -v uv >/dev/null || python3 -m pip install -q --user uv
       cd '$ROOT'
       [[ -x .venv/bin/python ]] || uv venv -q -p 3.12 .venv
       uv pip install -q -p .venv -r requirements.txt"

# --- 5. model ------------------------------------------------------------------
step "Whisper model ($MODEL, ~800 MB)"
inbox "cd '$ROOT' && [[ -d models/$MODEL ]] || .venv/bin/hf download OpenVINO/$MODEL --local-dir models/$MODEL"

# --- 6. NPU self-test ----------------------------------------------------------
step "NPU self-test"
inbox "cd '$ROOT' && .venv/bin/python - <<'EOF'
import numpy as np, openvino as ov
from openvino import opset13 as o
core = ov.Core()
if 'NPU' not in core.available_devices:
    raise SystemExit('NPU not visible to OpenVINO (devices: %s)' % core.available_devices)
x = o.parameter([1, 64], np.float32)
m = ov.Model([o.relu(o.matmul(x, o.constant(np.ones((64, 64), np.float32)), False, False))], [x])
core.compile_model(m, 'NPU')(np.ones((1, 64), np.float32))
print('OK:', core.get_property('NPU', 'FULL_DEVICE_NAME'))
EOF" || warn "NPU self-test failed; Utter will fall back to the CPU"

# --- 7. host integration -------------------------------------------------------
step "Installing service, toggle and launcher"
install -Dm755 "$ROOT/contrib/utter-toggle" "$HOME/.local/bin/utter-toggle"
install -Dm644 "$ROOT/contrib/io.github.kidoncio.utter.desktop" \
    "$HOME/.local/share/applications/io.github.kidoncio.utter.desktop"
mkdir -p "$HOME/.config/systemd/user"
sed -e "s|@ROOT@|$ROOT|g" -e "s|@CONTAINER@|$CONTAINER|g" -e "s|@LANGUAGE@|$LANGUAGE|g" \
    "$ROOT/contrib/utter.service" | grep -v '^# Template' > "$HOME/.config/systemd/user/utter.service"
systemctl --user daemon-reload
echo "language: ${LANGUAGE:-auto-detect}"

if [[ $ENABLE == 1 ]]; then
    systemctl --user enable --now utter
    systemctl --user restart utter  # pick up a changed unit on re-runs
fi

# --- 8. KDE shortcut (optional) -----------------------------------------------
if [[ -n $SHORTCUT ]]; then
    step "KDE global shortcut $SHORTCUT"
    "$ROOT/contrib/kde-shortcut.sh" "$SHORTCUT"
fi

step "Done"
[[ $ENABLE == 1 ]] || echo "Start it now and on every login:  systemctl --user enable --now utter"
[[ -n $SHORTCUT ]] || echo "Bind a shortcut to 'utter-toggle' (e.g. ./install.sh --shortcut Meta+V on KDE)"
echo "Logs:  journalctl --user -u utter -f"
