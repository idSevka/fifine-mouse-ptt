# How It Works and Why It Is Done This Way

This document describes actual measurements, not assumptions. Everything below was
verified on specific hardware and under specific conditions, listed at the end.

---

## Problem 1: A state file + timer do not work

A classic script for a hold button looks like this:

```bash
press)
    # if the state file exists, the button is already held — skip the repeat
    [ -f "$STATE" ] && exit 0
    # but previously this was also combined with a time check:
    # “if the file is younger than 400 ms, treat it as a repeat”
    pactl get-source-mute ... > /tmp/state     # remember the previous state
    pactl set-source-mute ... toggle           # toggle it
    ;;
release)
    pactl set-source-mute ... $(cat /tmp/state)  # restore the previous state
    rm -f /tmp/state
    ;;
```

There are two defects here, and they compound:

1. **Time-based check.** Hyprland repeats arrive at variable intervals.
2. **`rm -f "$STATE"` on the slow path.** If a repeat does pass the check,
   the file is deleted and the press is handled as a new one — the saved state
   gets overwritten.

Reproduction (press → repeat after 0.6 s → release):

```
start:     unmuted
press1 ->  muted    state=unmuted    <- correct
press2 ->  unmuted  state=muted      <- state overwritten
release -> muted                     <- restored to the WRONG state
```

Measured intervals between repeats on one wireless receiver:
**0.2, 0.4, 0.6, and 1.8 seconds**. No fixed threshold works here: 1.8 s
misses the 400 ms window, while a 2-second window will swallow a genuine fast
double-click. **The correct solution is to remove the timer, not tune its value.**

The daemon does this:

```python
def on_press(self):
    if self.pressed:          # already held → repeat → DO NOT touch anything
        return
    self.pressed = True
    self.saved = is_muted()   # read the actual state exactly once
    set_muted(not self.saved)

def on_release(self):
    if not self.pressed or self.saved is None:
        return                # release without a press → ignore
    self.pressed = False
    restore, self.saved = self.saved, None
    set_muted(restore)
```

The key point: the state lives in the process's memory and is captured **once**
on press. No number of extra events can corrupt it.

---

## Problem 2: Two independent mute gates

This is the least obvious part, and it was the root cause of the prolonged
confusion.

The Fifine USB Microphone turned out to have **two** independent ways to mute
audio:

| | Hardware gate | Software gate |
|---|---|---|
| controlled by | touch button on the body | `pactl set-source-mute` |
| visible as | LED on the body | `Mic Capture Switch` (ALSA/PipeWire) |
| visible to the OS | **no** | yes |
| affects applications | indirectly | **yes, directly** |

Measurements proving these are different things:

**Six consecutive presses of the touch button** while polling every 200 ms:

```
start:                        PipeWire=LIVE  chip=on
15:48:11  FIFINE_KEY 256 value=1 / value=0
15:48:14  FIFINE_KEY 256 value=1 / value=0
15:48:35  FIFINE_KEY 256 value=1 / value=0
15:48:43  FIFINE_KEY 256 value=1 / value=0
15:48:53  FIFINE_KEY 256 value=1 / value=0
15:48:55  FIFINE_KEY 256 value=1 / value=0
end:                          PipeWire=LIVE  chip=on    <- NOT A SINGLE CHANGE
```

The LED switched correctly, and audibility changed in Discord.
But neither `pactl` nor `amixer` recorded a single change. A full dump of all
eight card registers was also captured with `amixer -c 3 contents` — none
changed.

**Conclusion:** the button event is readable; the gate state is not. These are
**different channels**, and a negative result on one says nothing about the
other. This mistake (generalizing “the state cannot be read” to “the button is
not connected to anything readable”) cost an extra round of diagnostics.

The LED listens to **both** gates: if you press the mouse side button, it
reacts. In other words, the indicator knows more than the system does.

### How this is fixed

Since the touch-button event is readable, the daemon listens for it and brings
the software gate into sync:

```
touch button pressed (code 256)
    │
    ├─ daemon sees the event
    ├─ reads the current state using pactl
    └─ inverts it in the system → the system catches up with the LED
```

Important safeguard: if the touch button is pressed **while the mouse button
is being held** — ignore it. Otherwise, the original state has already been
captured, the inversion will corrupt it, and `release` will restore the wrong
value. This is exactly the same bug we were trying to eliminate, just through a
new door.

---

## How to find the codes on your hardware

Listen to all devices at once while physically pressing the buttons:

```bash
python3 scripts/mouse-hid-sniff.py 120 ~/capture.jsonl
```

The script opens all readable `/dev/input/event*` and all available
`/dev/hidraw*`, writes JSONL with timestamps, and prints a summary of the
buttons. It already handles two pitfalls:

- **`/dev/hidraw*` is `0600 root:root`**, unlike `/dev/input/*`
  (`root:input 0660`). A user in the `input` group can read evdev, but not
  hidraw. This matters: some vendor buttons are reported **only** through HID
  and do not appear in evdev at all.
- **A read can return an incomplete `struct input_event`.** Parsing such a
  trailing fragment on a 16-byte boundary fails with `struct.error`. Exit the
  loop instead of unpacking it.

Check that the device is actually a mouse:

```bash
cat /sys/class/input/eventN/device/capabilities/key    # expect bits 272..276
cat /sys/class/input/eventN/device/capabilities/rel    # non-zero for a mouse
```

A five-button mouse shows `1f0000 0 0 0 0` — this is
`BTN_LEFT/RIGHT/MIDDLE/SIDE/EXTRA` = codes 272–276.

**Do not bind to `eventN`.** Numbers change on reconnect and reboot: the same
receiver was a keyboard at `event8` in one session and a mouse at `event13` in
the next. Match by device name and by the presence of the code in
`capabilities/key`.

---

## Verify that everything works

Logic simulation (does not require hardware):

```bash
fifine-ptt-selftest
```

Covers both polarities × {0, 1, 5} extra presses and checks that the final state
equals the initial state. 6 scenarios.

> **A green self-test proves the logic, not that the button works.** It calls
> your own methods with your own event sequence and cannot fail for a reason
> below your code. Do not treat it as confirmation of the fix.

Test on live hardware:

```bash
watch -n0.3 mic-status       # and press the button
```

---

## Measurement conditions

- Arch Linux, Hyprland 0.56 (Omarchy 4.0.4)
- Microphone: Fifine USB Microphone (`3142:00a8`), ALSA card 3
- Mouse: Beken USB Gaming Mouse (`1d57:fa61`), side button = `BTN_EXTRA` (276)
- Microphone touch button: separate Consumer Control device, `code 256`
  (in the mask: codes `113,114,115,163,164,165,166,256`)

Codes and names will differ on other hardware, but the approach remains the same.
