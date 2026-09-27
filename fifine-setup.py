#!/usr/bin/env python3
"""Automatically detect hardware and generate a config for fifine-ptt.

Run once on a new machine: the script will ask which button to press,
capture the event, find the microphone, and write ~/.config/fifine-ptt/env.

    python3 fifine-setup.py

This avoids manually figuring out device names and button codes —
the main obstacle when moving to another system.
"""

from __future__ import annotations

import argparse
import os
import select
import shutil
import struct
import subprocess
import sys
import time

EV_KEY = 1
EV_SIZE = struct.calcsize("llHHi")
CONFIG_DIR = os.path.expanduser("~/.config/fifine-ptt")
CONFIG_FILE = os.path.join(CONFIG_DIR, "env")

PICK_SOURCE = False   # --pick: ask for a microphone even if a default exists


def say(msg: str = "") -> None:
    print(msg, flush=True)


def dev_name(node: str) -> str:
    entry = os.path.basename(node)
    try:
        return open(f"/sys/class/input/{entry}/device/name").read().strip()
    except OSError:
        return "?"


def list_event_nodes() -> list[str]:
    if not os.path.isdir("/dev/input"):
        return []
    return sorted(f"/dev/input/{n}" for n in os.listdir("/dev/input")
                  if n.startswith("event"))


def check_prerequisites() -> bool:
    ok = True
    say("== Checking the environment")
    for tool, why in (("pactl", "microphone control (PipeWire/PulseAudio)"),
                      ("python3", "the daemon itself")):
        if shutil.which(tool):
            say(f"   [ok] {tool}")
        else:
            say(f"   [!!] {tool} not found — required for: {why}")
            ok = False

    groups = subprocess.run(["id", "-nG"], capture_output=True, text=True).stdout.split()
    if "input" in groups:
        say("   [ok] user is in the input group (access to /dev/input)")
    else:
        say("   [!!] user is NOT in the input group")
        say(f"        run: sudo usermod -aG input {os.environ.get('USER', '$USER')}")
        say("        then log back into the system")
        ok = False

    # Is the sound server responding?
    r = subprocess.run(["pactl", "info"], capture_output=True, text=True)
    if r.returncode == 0:
        say("   [ok] sound server is responding")
    else:
        say("   [!!] pactl cannot connect to the sound server")
        say("        PipeWire/PulseAudio must be running in your session")
        ok = False
    return ok


def pick_source() -> str | None:
    """Select a microphone.

    If a default source exists, use it silently: in the vast majority of cases
    that is the one needed, and an extra question just gets in the way. Show the
    list only when there is no default source or the user explicitly requested
    a selection (the --pick argument).
    """
    say()
    say("== Microphone")

    current = default_source()
    if current and not PICK_SOURCE:
        say(f"   Using default source: {current}")
        say("   (to choose another: fifine-setup.py --pick)")
        return current

    r = subprocess.run(["pactl", "list", "sources", "short"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        say("   Could not get the list of sources.")
        if current:
            say(f"   Using default source: {current}")
            return current
        return None

    sources = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            sources.append(parts[1])

    if not sources:
        say("   No sources found.")
        return current

    say("   Available sources:")
    for i, name in enumerate(sources, 1):
        mark = "  <- default" if name == current else ""
        say(f"     {i}) {name}{mark}")

    answer = input(f"\n   Microphone number (Enter = {current or 'first'}): ").strip()
    if not answer:
        return current or sources[0]
    try:
        return sources[int(answer) - 1]
    except (ValueError, IndexError):
        say("   Invalid number; using the first source.")
        return current or sources[0]


def default_source() -> str | None:
    r = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True)
    return r.stdout.strip() or None


def capture_one_press(prompt: str, seconds: int = 25) -> tuple[str, str, int] | None:
    """Capture the first press of any button/key on any device.

    Returns (device name, event node name, code). Listens to ALL devices
    at once — we do not know in advance which one will send the event.
    """
    nodes = list_event_nodes()
    if not nodes:
        say("   No /dev/input/event* devices found.")
        return None

    fds: dict[int, str] = {}
    for node in nodes:
        try:
            fds[os.open(node, os.O_RDONLY | os.O_NONBLOCK)] = node
        except OSError:
            continue
    if not fds:
        say("   No access to /dev/input (the input group is required).")
        return None

    say(f"   {prompt}")
    say(f"   Listening to {len(fds)} devices; you have {seconds} seconds...")

    deadline = time.time() + seconds
    try:
        while time.time() < deadline:
            ready, _, _ = select.select(list(fds), [], [], 0.3)
            for fd in ready:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    continue
                for off in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
                    chunk = data[off:off + EV_SIZE]
                    if len(chunk) < EV_SIZE:
                        break
                    _, _, etype, code, value = struct.unpack("llHHi", chunk)
                    # React only to a button/key PRESS.
                    if etype == EV_KEY and value == 1 and code != 0:
                        node = fds[fd]
                        return dev_name(node), node, code
    finally:
        for fd in fds:
            os.close(fd)
    return None


def main() -> int:
    global PICK_SOURCE

    parser = argparse.ArgumentParser(
        description="Automatically detect hardware and create a config for fifine-ptt")
    parser.add_argument("--pick", action="store_true",
                        help="ask for a microphone even if a default source exists")
    parser.add_argument("--config-only", action="store_true",
                        help="do not touch devices; only show the current config")
    args = parser.parse_args()
    PICK_SOURCE = args.pick

    say("=== fifine-mouse-ptt setup ===")
    say()

    if args.config_only:
        if os.path.exists(CONFIG_FILE):
            say(f"Current config: {CONFIG_FILE}")
            say()
            with open(CONFIG_FILE) as fh:
                say(fh.read().rstrip())
        else:
            say(f"Config does not exist: {CONFIG_FILE}")
            say("Run without --config-only to create it.")
        return 0

    if not check_prerequisites():
        say()
        say("Fix the issues above first, then run the script again.")
        return 1

    src = pick_source()
    if not src:
        say("Setup is not possible without a source.")
        return 1

    say()
    say("== Mouse button for push-to-talk / push-to-mute")
    say("   I will now ask you to press a side button on the mouse.")
    got = capture_one_press("PRESS A SIDE MOUSE BUTTON (the one by your thumb).", 25)
    if not got:
        say("   Did not capture a press. Try again or set it manually:")
        say("     FIFINE_DEVICE_MATCH='<name>' FIFINE_BTN=<code>")
        return 1
    mouse_name, mouse_node, mouse_code = got
    say(f"   Captured: device '{mouse_name}', code {mouse_code}")

    # Short name for the match mask: remove common suffixes so it also matches
    # when the device is reconnected.
    mask = mouse_name
    for tail in (" System Control", " Consumer Control", " Keyboard", " Mouse"):
        if mask.endswith(tail):
            mask = mask[: -len(tail)]

    say()
    say("== Microphone touch button (optional)")
    say("   If your microphone has its own mute button, it can be synchronized.")
    answer = input("   Configure it? [y/N]: ").strip().lower()
    touch_enabled = False
    touch_mask, touch_code = "", ""
    if answer.startswith("y"):
        got2 = capture_one_press("PRESS THE BUTTON ON THE MICROPHONE BODY.", 25)
        if got2:
            tname, _, tcode = got2
            say(f"   Captured: device '{tname}', code {tcode}")
            touch_mask, touch_code, touch_enabled = tname, str(tcode), True
        else:
            say("   No press captured — skipping synchronization.")

    # ---------------------------------------------------------------- writing
    # Each line gets a comment: people open the file manually when something
    # is not working, and understanding the fields matters more than brevity then.
    os.makedirs(CONFIG_DIR, exist_ok=True)
    lines = [
        "# fifine-ptt config. Created by fifine-setup.py.",
        "#",
        "# The daemon reads this file at startup. Environment variables take",
        "# precedence: override them for a single run without editing the file, e.g.:",
        "#     FIFINE_DEVICE_MATCH='Logitech' fifine-ptt --status",
        "#",
        "# Format: KEY=value. The # character starts a comment.",
        "",
        "# Which audio source to toggle. List all sources with:",
        "#     pactl list sources short",
        f"FIFINE_SOURCE={src}",
        "",
        "# Mouse: a substring of the device name and the button code. The name is taken",
        "# as-is from /sys/class/input/eventN/device/name; the event node number is NOT",
        "# suitable — numbers change on reconnect, names do not.",
        "# List devices with:  python3 mouse-hid-sniff.py 20",
        f"FIFINE_DEVICE_MATCH={mask}",
        f"# {mouse_code} = BTN_EXTRA (side button). Other codes: 272 left, 273 right,",
        "# 274 wheel, 275 and 276 side buttons.",
        f"FIFINE_BTN={mouse_code}",
    ]
    if touch_enabled:
        lines += [
            "",
            "# Button on the microphone body. The device may have TWO independent",
            "# mute gates: hardware (shown by the LED) and software",
            "# (Mic Capture Switch, seen by applications). The LED listens to both,",
            "# while the system listens only to software. FIFINE_TOUCH=1 makes the daemon",
            "# listen to this button and align the software gate with it.",
            "# Details: docs/how-it-works.md",
            "FIFINE_TOUCH=1",
            f"FIFINE_TOUCH_DEVICE_MATCH={touch_mask}",
            f"# {touch_code} = BTN_0/KEY_BUTTONCONFIG on this device.",
            f"FIFINE_TOUCH_BTN={touch_code}",
        ]
    else:
        lines += [
            "",
            "# Synchronization with the microphone button is not configured. If your",
            "# microphone has its own mute button, uncomment and fill in these values:",
            "# FIFINE_TOUCH=1",
            "# FIFINE_TOUCH_DEVICE_MATCH=<microphone name substring>",
            "# FIFINE_TOUCH_BTN=<button code>",
        ]
    lines += [
        "",
        "# Notification popup when toggling. Requires omarchy-osd (Omarchy only) —",
        "# leave commented on other systems or it simply will not work.",
        "# FIFINE_OSD=1",
        "",
        "# Debugging: write every state transition to stderr.",
        "# Useful to run like this:  FIFINE_DEBUG=1 fifine-ptt",
        "# FIFINE_DEBUG=1",
    ]
    with open(CONFIG_FILE, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    say()
    say(f"== Config written: {CONFIG_FILE}")
    for line in lines:
        say(f"   {line}")

    say()
    say("== Done. Verify with:")
    say("   fifine-ptt --status")
    say("   fifine-ptt-selftest")
    say("   watch -n0.3 mic-status      # and press the button")
    say()
    say("The daemon will automatically load this config the next time it starts.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say()
        say("Interrupted.")
        sys.exit(130)
