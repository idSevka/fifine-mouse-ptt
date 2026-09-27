#!/usr/bin/env bash
# Install fifine-mouse-ptt: copy scripts and configure autostart.
#
# Choose one of two autostart methods:
#   systemd --user  — more reliable: restarts the daemon after a failure (recommended)
#   .desktop        — simpler: freedesktop standard, without systemd
#
# Set the method with a flag:   ./install.sh --systemd | --desktop | --none
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${HOME}/.local/bin"
AUTOSTART="${HOME}/.config/autostart"
UNITDIR="${HOME}/.config/systemd/user"
NAME="fifine-ptt"

MODE=""
case "${1:-}" in
  --systemd) MODE="systemd" ;;
  --desktop) MODE="desktop" ;;
  --none)    MODE="none" ;;
  "")        MODE="" ;;
  *) echo "Unknown flag: $1" >&2; echo "Usage: $0 [--systemd|--desktop|--none]" >&2; exit 2 ;;
esac

echo "==> Installing to ${BIN}"
mkdir -p "$BIN"
for f in fifine-ptt fifine-ptt-selftest fifine-ptt-hardware-test mic-status fifine-setup.py; do
  if [ -f "${HERE}/${f}" ]; then
    install -Dm755 "${HERE}/${f}" "${BIN}/${f}"
    echo "    ${BIN}/${f}"
  fi
done

# ---------------------------------------------------------------- checks
echo
echo "==> Checking the environment"

if id -nG | tr ' ' '\n' | grep -qx input; then
  echo "    [ok] access to /dev/input (input group)"
  INPUT_OK=1
else
  INPUT_OK=0
  echo "    [!!] user ${USER} is NOT a member of the input group"
  echo "         The daemon cannot read input events. Run this, then log in again:"
  echo "             sudo usermod -aG input ${USER}"
  echo "         Or grant temporary access without logging out (resets on reboot):"
  echo "             sudo setfacl -m u:${USER}:rw /dev/input/event*"
fi

if command -v pactl >/dev/null 2>&1 && pactl info >/dev/null 2>&1; then
  echo "    [ok] audio server is responding"
else
  echo "    [!!] pactl is unavailable or the audio server is not responding"
  echo "         Install pipewire or pulseaudio-utils (see README)"
fi

# --------------------------------------------------------------- autostart
echo
if [ -z "$MODE" ]; then
  # Auto-select systemd if a user-level manager is available.
  if systemctl --user show-environment >/dev/null 2>&1; then
    MODE="systemd"
  else
    MODE="desktop"
  fi
  echo "==> Autostart: selected '${MODE}' automatically"
fi

case "$MODE" in
  systemd)
    # Remove .desktop autostart if it was left by a previous installation.
    # install.sh with --desktop: two launch mechanisms = two daemons on one button.
    # The daemon is also protected by flock, but cleaning up here avoids the
    # confusing log message that the second process exits silently.
    if [ -e "${AUTOSTART}/${NAME}.desktop" ]; then
      rm -f "${AUTOSTART}/${NAME}.desktop"
      echo "    [i] removed old ${AUTOSTART}/${NAME}.desktop (would otherwise launch twice)"
    fi
    mkdir -p "$UNITDIR"
    install -Dm644 "${HERE}/${NAME}.service" "${UNITDIR}/${NAME}.service"
    systemctl --user daemon-reload
    echo "    unit:      ${UNITDIR}/${NAME}.service"
    echo "    enable:    systemctl --user enable --now ${NAME}"
    echo "    status:    systemctl --user status ${NAME}"
    echo "    logs:      journalctl --user -u ${NAME} -f"
    if [ "$INPUT_OK" -eq 1 ]; then
      systemctl --user enable --now "${NAME}.service" 2>/dev/null \
        && echo "    [ok] started and enabled at login" \
        || echo "    [!!] could not start; enable it manually (command above)"
    else
      echo "    (startup deferred: grant access to /dev/input first)"
    fi
    ;;
  desktop)
    mkdir -p "$AUTOSTART"
    cat >"${AUTOSTART}/${NAME}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Fifine push-to-talk
Comment=Mouse side button: hold to mute. Microphone button: state synchronization.
Exec=env FIFINE_TOUCH=1 ${BIN}/${NAME}
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
    echo "    ${AUTOSTART}/${NAME}.desktop"
    echo "    Start now: FIFINE_TOUCH=1 ${BIN}/${NAME} &"
    echo
    echo "    NOTE: .desktop does not restart the daemon after a failure."
    echo "    For better reliability, use systemd:"
    echo "        $0 --systemd"
    ;;
  none)
    echo "==> Autostart was not configured (--none)"
    ;;
esac

# ---------------------------------------------------------------- summary
echo
echo "==> Checking for detected devices"
if [ "$INPUT_OK" -eq 1 ]; then
  "${BIN}/${NAME}" --status 2>&1 | sed 's/^/    /' || true
else
  echo "    skipped (no access to /dev/input)"
fi

echo
echo "==> Done"
echo "    Hardware configuration (if not done yet): ${BIN}/fifine-setup.py"
echo "    Logic test:                              ${BIN}/fifine-ptt-selftest"
echo "    Hardware test:                           ${BIN}/fifine-ptt-hardware-test"
echo "    Monitor status:                          watch -n0.3 ${BIN}/mic-status"
