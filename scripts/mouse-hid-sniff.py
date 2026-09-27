#!/usr/bin/env python3
"""Record all events from all input devices in JSONL and print a breakdown by button press.

Usage:  python3 mouse-hid-sniff.py [duration_sec] [output_file]

Records not only evdev codes, but also HID events (hidraw) from the receiver:
mice with vendor-specific buttons (Attack Shark/GXT and others) often send button
events directly to the mouse HID interface, bypassing the evdev device, so evdev cannot see them.

evdev/hidraw are read directly from /dev; root is not required if the user belongs to
the input group (check with: id -nG | tr ' ' '\n' | grep -x input).
"""
import json
import os
import select
import struct
import sys
import time

# ---------------------------------------------------------------- evdev layout
# struct input_event { struct timeval time; __u16 type, code; __s32 value; }
EV_FMT = "llHHi"
EV_SIZE = struct.calcsize(EV_FMT)

EV_TYPES = {0: "SYN", 1: "KEY", 2: "REL", 3: "ABS", 4: "MSC", 17: "LED", 20: "REP"}
EV_SYN = 0
EV_KEY = 1
EV_MSC = 4
SYN_REPORT = 0
MSC_SCAN = 4

# Only button-relevant codes; print all others as numbers.
KEY_NAMES = {
    272: "BTN_LEFT", 273: "BTN_RIGHT", 274: "BTN_MIDDLE", 275: "BTN_SIDE",
    276: "BTN_EXTRA", 277: "BTN_FORWARD", 278: "BTN_BACK", 279: "BTN_TASK",
    280: "BTN_?_280", 281: "BTN_?_281", 282: "BTN_?_282", 283: "BTN_?_283",
    284: "BTN_?_284", 285: "BTN_?_285", 286: "BTN_?_286", 287: "BTN_?_287",
}
for i, n in enumerate("BTN_TRIGGER BTN_THUMB BTN_THUMB2 BTN_TOP BTN_TOP2 "
                      "BTN_PINKIE BTN_BASE BTN_BASE2 BTN_BASE3 BTN_BASE4".split()):
    KEY_NAMES[288 + i] = n


def dev_name(event_node):
    """Get the device name from sysfs so the log shows which device sent the event."""
    base = os.path.basename(event_node)          # event13
    path = f"/sys/class/input/{base}/device/name"
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        pass
    # hidraw nodes can also provide a name via HID-unique; this is not critical.
    return "?"


def opened(paths):
    fds = {}
    for p in paths:
        try:
            fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
        except OSError as err:
            print(f"! cannot open {p}: {err}", file=sys.stderr)
    return fds


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 90
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser(
        "~/mouse-hid-capture.jsonl")

    event_nodes = sorted(
        os.path.join("/dev/input", n) for n in os.listdir("/dev/input")
        if n.startswith("event"))
    hidraw_nodes = sorted(
        os.path.join("/dev", n) for n in os.listdir("/dev")
        if n.startswith("hidraw")) if os.path.isdir("/dev") else []

    print("Devices:")
    for p in event_nodes:
        print(f"  {p:22} {dev_name(p)}")
    print(f"hidraw: {hidraw_nodes or '(no access/no devices)'}")
    print(f"\nRecording for {seconds:.0f} s to {out}\n")

    fds = opened(event_nodes + hidraw_nodes)
    log = open(out, "w")
    by_card = {}           # (dev, code) -> [(t, value)]
    hid_sizes = {}         # dev -> HID report size in bytes
    t0 = time.time()

    while time.time() - t0 < seconds:
        ready, _, _ = select.select(list(fds), [], [], 0.3)
        for fd in ready:
            dev = fds[fd]
            try:
                data = os.read(fd, 4096)
            except OSError:
                continue
            if not data:
                continue
            rel = time.time() - t0

            if dev.startswith("/dev/input"):
                for off in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
                    chunk = data[off:off + EV_SIZE]
                    if len(chunk) < EV_SIZE:
                        break           # Incomplete read tail; retrieve it next time.
                    _, _, etype, code, value = struct.unpack(EV_FMT, chunk)
                    if etype == 0 and code == SYN_REPORT:
                        continue
                    name = dev_name(dev)
                    rec = {"t": round(rel, 4), "dev": dev, "dev_name": name,
                           "type": EV_TYPES.get(etype, etype), "code": code,
                           "code_name": KEY_NAMES.get(code, ""), "value": value}
                    log.write(json.dumps(rec) + "\n")
                    log.flush()
                    key = (name, KEY_NAMES.get(code, f"code:{code}"))
                    by_card.setdefault(key, []).append((rel, value, etype))
                    label = KEY_NAMES.get(code, f"code:{code}")
                    if etype == EV_KEY and value == 1:
                        print(f"  {rel:7.2f} {name[:38]:38} {label} PRESSED")
                    elif etype == EV_KEY and value == 0:
                        print(f"  {rel:7.2f} {name[:38]:38} {label} released")
                    elif value not in (0,) and etype not in (EV_MSC,):
                        print(f"  {rel:7.2f} {name[:38]:38} {label} = {value}")
            else:
                # HID report: first byte is the report ID, followed by the data.
                size = hid_sizes.setdefault(dev, len(data))
                hexs = data.hex(" ")
                rec = {"t": round(rel, 4), "dev": dev, "type": "HID",
                       "len": len(data), "data": hexs}
                log.write(json.dumps(rec) + "\n")
                log.flush()
                by_card.setdefault((dev, "HID"), []).append((rel, hexs, "HID"))
                print(f"  {rel:7.2f} HID {os.path.basename(dev)} ({size}B): {hexs}")

    log.close()
    for fd in fds:
        os.close(fd)

    # ------------------------------------------------------------------ summary
    print("\n================ SUMMARY ================")
    for (name, label), hits in sorted(by_card.items()):
        presses = [t for t, v, ty in hits if ty == EV_KEY and v == 1]
        if presses:
            gaps = [round(b - a, 3) for a, b in zip(presses, presses[1:])]
            print(f"{name[:40]:40} {label:12} presses={len(presses)} "
                  f"t={[round(p,2) for p in presses]} auto-repeats={gaps}")
        else:
            print(f"{name[:40]:40} {label:12} events={len(hits)}")
    print(f"\nRaw log: {out}")


if __name__ == "__main__":
    FROM = "=" + EV_FMT     # native/little-endian as on x86_64
    main()
