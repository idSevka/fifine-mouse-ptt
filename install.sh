#!/usr/bin/env bash
# Установка fifine-mouse-ptt: копирует скрипты и настраивает автозапуск.
#
# Автозапуск двумя способами на выбор:
#   systemd --user  — надёжнее: перезапускает демон при падении (рекомендуется)
#   .desktop        — проще: стандарт freedesktop, без systemd
#
# Способ можно задать флагом:   ./install.sh --systemd | --desktop | --none
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
  *) echo "Неизвестный флаг: $1" >&2; echo "Использование: $0 [--systemd|--desktop|--none]" >&2; exit 2 ;;
esac

echo "==> Установка в ${BIN}"
mkdir -p "$BIN"
for f in fifine-ptt fifine-ptt-selftest fifine-ptt-hardware-test mic-status fifine-setup.py; do
  if [ -f "${HERE}/${f}" ]; then
    install -Dm755 "${HERE}/${f}" "${BIN}/${f}"
    echo "    ${BIN}/${f}"
  fi
done

# ---------------------------------------------------------------- проверки
echo
echo "==> Проверка окружения"

if id -nG | tr ' ' '\n' | grep -qx input; then
  echo "    [ok] доступ к /dev/input (группа input)"
  INPUT_OK=1
else
  INPUT_OK=0
  echo "    [!!] пользователь ${USER} НЕ входит в группу input"
  echo "         Демон не сможет читать события. Выполните и перезайдите:"
  echo "             sudo usermod -aG input ${USER}"
  echo "         Либо разово, без перелогина (сбросится при перезагрузке):"
  echo "             sudo setfacl -m u:${USER}:rw /dev/input/event*"
fi

if command -v pactl >/dev/null 2>&1 && pactl info >/dev/null 2>&1; then
  echo "    [ok] звуковой сервер отвечает"
else
  echo "    [!!] pactl недоступен или звуковой сервер не отвечает"
  echo "         Установите pipewire или pulseaudio-utils (см. README)"
fi

# --------------------------------------------------------------- автозапуск
echo
if [ -z "$MODE" ]; then
  # Автовыбор: systemd, если он есть как пользовательский менеджер.
  if systemctl --user show-environment >/dev/null 2>&1; then
    MODE="systemd"
  else
    MODE="desktop"
  fi
  echo "==> Автозапуск: выбран способ '${MODE}' автоматически"
fi

case "$MODE" in
  systemd)
    # Убираем .desktop-автозапуск, если он остался от прошлого запуска
    # install.sh с --desktop: два канала = два демона на одной кнопке.
    # Сам демон тоже защищён flock'ом, но чистка здесь избавляет от
    # неочевидного «второй процесс молча выходит» в логах.
    if [ -e "${AUTOSTART}/${NAME}.desktop" ]; then
      rm -f "${AUTOSTART}/${NAME}.desktop"
      echo "    [i] удалён старый ${AUTOSTART}/${NAME}.desktop (иначе был бы двойной запуск)"
    fi
    mkdir -p "$UNITDIR"
    install -Dm644 "${HERE}/${NAME}.service" "${UNITDIR}/${NAME}.service"
    systemctl --user daemon-reload
    echo "    юнит: ${UNITDIR}/${NAME}.service"
    echo "    включить:  systemctl --user enable --now ${NAME}"
    echo "    статус:    systemctl --user status ${NAME}"
    echo "    логи:      journalctl --user -u ${NAME} -f"
    if [ "$INPUT_OK" -eq 1 ]; then
      systemctl --user enable --now "${NAME}.service" 2>/dev/null \
        && echo "    [ok] запущен и добавлен в автозапуск" \
        || echo "    [!!] не удалось запустить, включите вручную (команда выше)"
    else
      echo "    (запуск отложен: сначала выдайте доступ к /dev/input)"
    fi
    ;;
  desktop)
    mkdir -p "$AUTOSTART"
    cat >"${AUTOSTART}/${NAME}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Fifine push-to-talk
Comment=Боковая кнопка мыши: hold-мьют. Кнопка микрофона: синхронизация состояния.
Exec=env FIFINE_TOUCH=1 ${BIN}/${NAME}
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
    echo "    ${AUTOSTART}/${NAME}.desktop"
    echo "    Запустить сейчас: FIFINE_TOUCH=1 ${BIN}/${NAME} &"
    echo
    echo "    ВНИМАНИЕ: .desktop не перезапускает демон при падении."
    echo "    Если нужна устойчивость — используйте systemd:"
    echo "        $0 --systemd"
    ;;
  none)
    echo "==> Автозапуск не настраивался (--none)"
    ;;
esac

# ---------------------------------------------------------------- итог
echo
echo "==> Проверка находки устройств"
if [ "$INPUT_OK" -eq 1 ]; then
  "${BIN}/${NAME}" --status 2>&1 | sed 's/^/    /' || true
else
  echo "    пропущено (нет доступа к /dev/input)"
fi

echo
echo "==> Готово"
echo "    Конфиг железа (если ещё не сделан): ${BIN}/fifine-setup.py"
echo "    Проверка логики:                    ${BIN}/fifine-ptt-selftest"
echo "    Проверка живого железа:             ${BIN}/fifine-ptt-hardware-test"
echo "    Смотреть состояние:                 watch -n0.3 ${BIN}/mic-status"
