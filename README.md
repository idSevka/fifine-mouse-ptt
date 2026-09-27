# fifine-mouse-ptt

Push-to-talk / push-to-mute for a USB microphone from a mouse side button — plus
sync with the microphone's own mute button.

This project is maintained in English.

Built and verified on a Fifine USB Microphone under Arch + Hyprland, but the
approach applies to any device that emits a readable evdev event.

---

## Why not just a keybinding

The obvious approach is a press/release binding in your window manager's config,
with the logic in a shell script that keeps state in `/tmp`. That approach
breaks, and here is exactly how:

**1. The compositor sends repeat press events while the button is held.**
Intervals drift — measured on one wireless receiver: 0.2, 0.4, 0.6 and **1.8**
seconds between repeats. A script guarding with a time window ("treat as repeat
if less than N ms ago") cannot pick a correct N: any fixed threshold is
simultaneously too short for the slow repeats and long enough to swallow a
genuine fast double-click. A repeat arriving outside the window is processed as
a fresh press, overwrites the saved state, and on release the mic is restored to
the **wrong** side. Users report this as "it only works in one position".

**2. A microphone can have two independent mute gates.** The Fifine does: a
hardware gate inside the chip with an LED (driven by the touch button on the
body), and a separate `Mic Capture Switch` in ALSA/PipeWire that applications
actually honour. The LED reflects **both**, the OS reflects **only the second**.
The touch button does not publish its state to the host at all.

How this project solves it:

- **Read evdev directly** instead of going through a binding. One physical press
  produces exactly one `value=1` and one `value=0`.
- **Keep the saved state in the process's memory**, not in a file. No stray event
  can clobber it.
- **Guard with a boolean flag, not a timer.** While the key is logically down,
  any further `value=1` is ignored. Kernel autorepeat (`value=2`) is skipped.
- **Also watch the microphone's own button** (evdev `code 256`) and flip the
  software mute to follow it, so the OS state and the LED stay in agreement.

---

## Install

### Any distribution

No window manager required — Hyprland is not needed. All you need is a sound
server (PipeWire or PulseAudio) and access to `/dev/input`.

```bash
git clone https://github.com/idSevka/fifine-mouse-ptt.git
cd fifine-mouse-ptt

# 1. Let it find your hardware and write a config
python3 fifine-setup.py

# 2. Install
./install.sh

# 3. Verify
fifine-ptt --status         # are the devices found?
fifine-ptt-selftest         # logic: 6/6
fifine-ptt-hardware-test    # live check: press the button when asked
watch -n0.3 mic-status      # and press the button
```

**Start with `fifine-setup.py` on a new machine.** It checks your environment,
finds the microphone, asks you to press the mouse button and captures its code,
then writes `~/.config/fifine-ptt/env`. Nothing needs to be edited afterwards —
the daemon picks the config up automatically.

`install.sh` sets up autostart, choosing automatically between a systemd user
unit (preferred — it restarts the daemon if it crashes) and a plain
`.desktop` entry. Force either way:

```bash
./install.sh --systemd     # recommended, survives crashes
./install.sh --desktop     # no systemd needed
./install.sh --none        # install only, no autostart
```

### Dependencies

The only real dependency is `pactl` (from `pipewire` or `pulseaudio-utils`) plus
`python3`, which is usually already present.

| Distribution | Command |
|---|---|
| Arch / Omarchy | `sudo pacman -S libpulse pipewire` |
| Ubuntu / Debian | `sudo apt install pulseaudio-utils pipewire-bin` |
| Fedora | `sudo dnf install pulseaudio-utils pipewire-utils` |
| openSUSE | `sudo zypper install pulseaudio-utils` |

Check the sound server answers:

```bash
pactl info    # should print Server Name: PulseAudio (on PipeWire ...)
```

### /dev/input permissions

The daemon reads events straight from `/dev/input/event*`, which by default is
readable only by the `input` group:

```bash
sudo usermod -aG input $USER
```

**Then log out and back in** — the group does not apply otherwise. Verify:

```bash
id -nG | tr ' ' '\n' | grep -x input && echo "access ok"
```

Alternative without a re-login (resets on reboot):

```bash
sudo setfacl -m u:$USER:rw /dev/input/event*
```

### Autostart

With `--systemd` (preferred):

```bash
systemctl --user status fifine-ptt     # state
journalctl --user -u fifine-ptt -f     # logs
```

With `--desktop`, `install.sh` writes `~/.config/autostart/fifine-ptt.desktop`,
a freedesktop standard honoured by GNOME, KDE, XFCE, Hyprland and others.

Do not enable both at once — two daemons fighting over the same mute state will
misbehave. `install.sh` warns about this.

The daemon also refuses to start a second instance on its own, so a stray
autostart entry can no longer cause two processes to fight over the button. It
takes an exclusive `flock` on `~/.run/fifine-ptt.lock`; the second instance
exits immediately with status 0 and prints why:

```
fifine-ptt is already running in another instance — exiting (duplicate-start protection)
```

This matters because two daemons read the same button: both see `press`, both
flip the mic, and on release the state is restored twice — i.e. back to where it
started. From the outside that looks like a dead button with no error anywhere.

`flock` is used rather than a pid file so the kernel releases the lock when the
process dies — `kill -9` cannot leave a stale lock that blocks the next start.

Check that exactly one instance is running:

```bash
pgrep -fa fifine-ptt          # one process
cat ~/.run/fifine-ptt.lock    # pid of the running daemon
```

`--status` does not take the lock, so it always works alongside a running daemon.

---

## Moving to another machine

Because device names and audio sources differ on different hardware:

1. `git clone` and `python3 fifine-setup.py` — it finds everything and writes a
   config.
2. `./install.sh` — installs and sets up autostart.
3. If something was not found, set it by hand in `~/.config/fifine-ptt/env`.

The config file overrides the built-in defaults, but **environment variables take
priority over the config**, so you can override once without editing anything:

```bash
FIFINE_DEVICE_MATCH="Logitech" fifine-ptt --status
```

---

## Using a different microphone or mouse

Nothing in the code is Fifine-specific. It is a generic "hold a mouse button to
override a mic" tool; three variables adapt it to any hardware:

| What | Variable | How to find it |
|---|---|---|
| The microphone | `FIFINE_SOURCE` | `pactl list sources short` — take the name from the 2nd column |
| The button | `FIFINE_DEVICE_MATCH` + `FIFINE_BTN` | `python3 scripts/mouse-hid-sniff.py 30`, press the button |
| A button on the mic | `FIFINE_TOUCH_DEVICE_MATCH` + `FIFINE_TOUCH_BTN` | same capture, press that button |

The match is a **case-insensitive substring** of the device name as shown in
`/sys/class/input/eventN/device/name`, combined with a check that the device can
actually emit that button code. Matching on a name substring plus a capability
bit is what keeps sibling interfaces of one device from being confused with each
other.

Example: Logitech mouse, button 275 (`BTN_SIDE`), HyperX microphone:

```bash
FIFINE_DEVICE_MATCH="Logitech" \
FIFINE_BTN=275 \
FIFINE_SOURCE="alsa_input.usb-HP__Inc_HyperX_Quadcast-00.analog-stereo" \
    fifine-ptt
```

Put the same lines into `~/.config/fifine-ptt/env` and they will apply on every
start.

### If the hardware has no readable event

Some devices report a vendor button only over the raw HID interface
(`/dev/hidraw*`), never through evdev. Such a button cannot be used by this
daemon as-is. Check before assuming:

```bash
python3 scripts/mouse-hid-sniff.py 30      # press the button during the run
```

The sniffer reads both evdev and hidraw, so if the button appears nowhere, it is
not exposed to userspace at all (often it is remappable only in the vendor's
Windows utility).

---

## How it works

```
     mouse side button                       mic body button
     BTN_EXTRA = 276                         code 256 (separate device node)
            │                                        │
            ▼                                        ▼
     ┌──────────────────────────────────────────────────────┐
     │  fifine-ptt — daemon reading /dev/input/event*        │
     │                                                       │
     │  press:    read pactl → save → invert                 │
     │  release:  restore the saved value                    │
     │  mic btn:  read pactl → invert (sync)                 │
     └──────────────────────────────────────────────────────┘
                              │
                              ▼
                        pactl set-source-mute
                              │
                              ▼
                    Mic Capture Switch (ALSA / PipeWire)
                              │
                              ▼
                    audible / not audible in applications
```

The strategy (push-to-talk or push-to-mute) is **chosen on every press** from the
state read at that moment:

```
press:   was muted   -> became unmuted   # mic was off → turn it on while held
release: restored muted

press:   was unmuted -> became muted     # mic was on  → mute while held
release: restored unmuted
```

---

## Environment variables

Read from `~/.config/fifine-ptt/env`, created by `fifine-setup.py`. Variables set
in the environment take priority over the file.

| Variable | Default | Meaning |
|---|---|---|
| `FIFINE_SOURCE` | the Fifine source | which audio source to mute |
| `FIFINE_BTN` | `276` | mouse button code (`BTN_EXTRA`) |
| `FIFINE_DEVICE_MATCH` | `Beken USB Gaming Mouse` | device name substring (mouse) |
| `FIFINE_TOUCH` | off | enable sync with the mic's own button |
| `FIFINE_TOUCH_BTN` | `256` | mic button code |
| `FIFINE_TOUCH_DEVICE_MATCH` | `fifine` | device name substring (microphone) |
| `FIFINE_OSD` | off | on-screen popup on switch (requires `omarchy-osd`) |
| `FIFINE_DEBUG` | off | log every state transition to stderr |

`FIFINE_TOUCH` is **off by default**: handling the mic's own button changes what
a habitual physical control does, so enable it deliberately.

---

## Commands

```bash
fifine-ptt                  # run the daemon (normally via autostart)
fifine-ptt --status         # show state and matched devices
fifine-ptt-selftest         # logic tests (6 scenarios, no hardware needed)
fifine-ptt-hardware-test    # live hardware check: does the button send clean events?
mic-status                  # state at two levels: PipeWire and the ALSA chip
fifine-setup.py             # find hardware and write the config
fifine-setup.py --pick      # choose the microphone explicitly
fifine-setup.py --config-only   # print the current config
```

`mic-status` is the main diagnostic tool. It shows state at both levels and flags
disagreement between them:

```
16:35:11       PipeWire:    ENABLED (live)   [no]
               ALSA (chip): ENABLED (live)   [on]  (card 3)
```

`fifine-ptt-hardware-test` answers a different question: does the physical button
send **clean** events? It measures how long a hold lasts, whether autorepeat
fires, and whether press/release come as a pair. A mouse whose firmware turns one
press into an instant press+release pair, or that drops the release, cannot work
with any hold-to-override design — and this test tells you that in 40 seconds
instead of a debugging session.

---

## Troubleshooting

**The button does nothing.** Is the daemon running (`pgrep -af fifine-ptt`) and
does it see the device (`fifine-ptt --status`)? Run with `FIFINE_DEBUG=1` and
press the button — transitions appear on stderr.

**The button works inconsistently, or "backwards".** Almost certainly a mismatch
between state sources: compare `mic-status` output against whatever indicator you
trust (LED, app icon). See [docs/how-it-works.md](docs/how-it-works.md).

**Device not found.** Find the real names and codes:

```bash
grep -A6 -i "mouse\|microphone" /proc/bus/input/devices
for ev in /sys/class/input/event*; do
  printf '%s %s\n' "$(basename $ev)" "$(cat $ev/device/name 2>/dev/null)"
done
python3 scripts/mouse-hid-sniff.py 30
```

**"Source not found in the sound server."** The configured audio source does not
exist. List the real ones with `pactl list sources short` and set
`FIFINE_SOURCE` accordingly.

---

## Limitations

- Reading `/dev/input/event*` requires membership in the `input` group (or root).
  Check: `id -nG | tr ' ' '\n' | grep -x input`.
- The daemon switches `Mic Capture Switch`. If your microphone has a **hardware**
  gate whose state the OS cannot read, the software and hardware mutes can drift
  apart — which is exactly what `FIFINE_TOUCH=1` compensates for, provided the
  device's button emits an evdev event.
- Verified on a Fifine USB Microphone + Beken USB Gaming Mouse under Hyprland.
  Other hardware needs its own codes.

---

## License

MIT — do whatever you like.
