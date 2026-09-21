#!/usr/bin/env python3
"""Автопоиск железа и генерация конфига для fifine-ptt.

Запусти один раз на новой машине: скрипт спросит, какую кнопку нажимать,
поймает событие, найдёт микрофон и запишет ~/.config/fifine-ptt/env.

    python3 fifine-setup.py

Это избавляет от ручного выяснения имён устройств и кодов кнопок —
главного препятствия при переносе на другую систему.
"""

from __future__ import annotations

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
    say("== Проверка окружения")
    for tool, why in (("pactl", "управление микрофоном (PipeWire/PulseAudio)"),
                      ("python3", "сам демон")):
        if shutil.which(tool):
            say(f"   [ok] {tool}")
        else:
            say(f"   [!!] {tool} не найден — нужен для: {why}")
            ok = False

    groups = subprocess.run(["id", "-nG"], capture_output=True, text=True).stdout.split()
    if "input" in groups:
        say("   [ok] пользователь в группе input (доступ к /dev/input)")
    else:
        say("   [!!] пользователь НЕ в группе input")
        say(f"        выполни: sudo usermod -aG input {os.environ.get('USER', '$USER')}")
        say("        затем перезайди в систему")
        ok = False

    # Звуковой сервер отвечает?
    r = subprocess.run(["pactl", "info"], capture_output=True, text=True)
    if r.returncode == 0:
        say("   [ok] звуковой сервер отвечает")
    else:
        say("   [!!] pactl не может связаться со звуковым сервером")
        say("        PipeWire/PulseAudio должен быть запущен в твоей сессии")
        ok = False
    return ok


def pick_source() -> str | None:
    say()
    say("== Микрофон")
    r = subprocess.run(["pactl", "list", "sources", "short"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        say("   Не удалось получить список источников.")
        return None

    sources = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            sources.append(parts[1])

    say("   Доступные источники:")
    for i, name in enumerate(sources, 1):
        mark = "  <- по умолчанию" if name == default_source() else ""
        say(f"     {i}) {name}{mark}")

    answer = input("\n   Номер микрофона (Enter = по умолчанию): ").strip()
    if not answer:
        return default_source()
    try:
        return sources[int(answer) - 1]
    except (ValueError, IndexError):
        say("   Не понял номер, беру источник по умолчанию.")
        return default_source()


def default_source() -> str | None:
    r = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True)
    return r.stdout.strip() or None


def capture_one_press(prompt: str, seconds: int = 25) -> tuple[str, str, int] | None:
    """Ловит первое нажатие любой кнопки/клавиши на любом устройстве.

    Возвращает (имя устройства, имя event-узла, код). Слушает ВСЕ устройства
    сразу — заранее неизвестно, какое из них пришлёт событие.
    """
    nodes = list_event_nodes()
    if not nodes:
        say("   Не найдено ни одного /dev/input/event*.")
        return None

    fds: dict[int, str] = {}
    for node in nodes:
        try:
            fds[os.open(node, os.O_RDONLY | os.O_NONBLOCK)] = node
        except OSError:
            continue
    if not fds:
        say("   Нет доступа к /dev/input (нужна группа input).")
        return None

    say(f"   {prompt}")
    say(f"   Слушаю {len(fds)} устройств, у тебя {seconds} секунд...")

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
                    # Реагируем только на НАЖАТИЕ кнопки/клавиши.
                    if etype == EV_KEY and value == 1 and code != 0:
                        node = fds[fd]
                        return dev_name(node), node, code
    finally:
        for fd in fds:
            os.close(fd)
    return None


def main() -> int:
    say("=== Настройка fifine-mouse-ptt ===")
    say()

    if not check_prerequisites():
        say()
        say("Сначала устрани замечания выше, потом запусти скрипт снова.")
        return 1

    src = pick_source()
    if not src:
        say("Без источника настройка невозможна.")
        return 1

    say()
    say("== Кнопка мыши для push-to-talk / push-to-mute")
    say("   Сейчас попрошу нажать боковую кнопку мыши.")
    got = capture_one_press("НАЖМИ БОКОВУЮ КНОПКУ МЫШИ (ту, что у большого пальца).", 25)
    if not got:
        say("   Не поймал нажатие. Попробуй ещё раз или задай вручную:")
        say("     FIFINE_DEVICE_MATCH='<имя>' FIFINE_BTN=<код>")
        return 1
    mouse_name, mouse_node, mouse_code = got
    say(f"   Поймано: устройство '{mouse_name}', код {mouse_code}")

    # Короткое имя для маски: убираем типовые хвосты, чтобы совпадало
    # и при переподключении устройства.
    mask = mouse_name
    for tail in (" System Control", " Consumer Control", " Keyboard", " Mouse"):
        if mask.endswith(tail):
            mask = mask[: -len(tail)]

    say()
    say("== Сенсорная кнопка микрофона (необязательно)")
    say("   Если у микрофона есть своя кнопка мьюта, её можно синхронизировать.")
    answer = input("   Настроить? [y/N]: ").strip().lower()
    touch_enabled = False
    touch_mask, touch_code = "", ""
    if answer.startswith("y"):
        got2 = capture_one_press("НАЖМИ КНОПКУ НА КОРПУСЕ МИКРОФОНА.", 25)
        if got2:
            tname, _, tcode = got2
            say(f"   Поймано: устройство '{tname}', код {tcode}")
            touch_mask, touch_code, touch_enabled = tname, str(tcode), True
        else:
            say("   Не поймал — синхронизацию пропускаю.")

    # ---------------------------------------------------------------- запись
    os.makedirs(CONFIG_DIR, exist_ok=True)
    lines = [
        "# Конфиг fifine-ptt, создан fifine-setup.py",
        "# Загружается демоном автоматически, если файл существует.",
        f"FIFINE_SOURCE={src}",
        f"FIFINE_DEVICE_MATCH={mask}",
        f"FIFINE_BTN={mouse_code}",
    ]
    if touch_enabled:
        lines += [
            "FIFINE_TOUCH=1",
            f"FIFINE_TOUCH_DEVICE_MATCH={touch_mask}",
            f"FIFINE_TOUCH_BTN={touch_code}",
        ]
    with open(CONFIG_FILE, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    say()
    say(f"== Конфиг записан: {CONFIG_FILE}")
    for line in lines:
        say(f"   {line}")

    say()
    say("== Готово. Проверка:")
    say("   fifine-ptt --status")
    say("   fifine-ptt-selftest")
    say("   watch -n0.3 mic-status      # и нажать кнопку")
    say()
    say("Демон подхватит этот конфиг автоматически при следующем запуске.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say()
        say("Прервано.")
        sys.exit(130)
