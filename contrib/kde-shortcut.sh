#!/usr/bin/env bash
# Bind a KDE Plasma 6 global shortcut to Utter, live (no re-login needed).
#   contrib/kde-shortcut.sh Meta+V
# Supports Meta/Ctrl/Alt/Shift + one letter, digit or F1–F35. Refuses keys already taken.
set -euo pipefail
keys=${1:?usage: $0 Meta+V}
G="gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel --method org.kde.KGlobalAccel"
ACTION="['io.github.kidoncio.utter.desktop','_launch','Utter','Utter']"

code=0
IFS=+ read -ra parts <<<"$keys"
for p in "${parts[@]}"; do
    case ${p,,} in
        meta|super) code=$((code | 0x10000000)) ;;
        ctrl|control) code=$((code | 0x04000000)) ;;
        alt) code=$((code | 0x08000000)) ;;
        shift) code=$((code | 0x02000000)) ;;
        [a-z0-9]) code=$((code | $(printf '%d' "'${p^^}"))) ;;
        f[1-9]|f[1-2][0-9]|f3[0-5]) code=$((code | (0x01000030 + ${p:1} - 1))) ;;  # Qt::Key_F1..F35
        *) echo "unsupported key: $p" >&2; exit 2 ;;
    esac
done

owner=$($G.globalShortcutsByKey "([$code,0,0,0],)" "(0,)" 2>/dev/null || true)
if [[ $owner == *"'"* && $owner != *io.github.kidoncio.utter* ]]; then
    echo "$keys is already used by another action:" >&2
    echo "  $owner" >&2
    echo "Free it in System Settings → Keyboard → Shortcuts, or pick another key." >&2
    exit 1
fi
$G.doRegister "$ACTION" >/dev/null
$G.setForeignShortcutKeys "$ACTION" "[([$code,0,0,0],)]" >/dev/null
# A component registered from outside stays inactive (its keys are not grabbed)
# until the next login. Marking the shortcut present (SetPresent = 2) activates it now.
$G.setShortcutKeys "$ACTION" "[([$code,0,0,0],)]" "uint32 2" >/dev/null
echo "Utter bound to $keys"
