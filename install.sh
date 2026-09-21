#!/usr/bin/env bash
# Установка fifine-mouse-ptt: копирует скрипты и создаёт автозапуск.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${HOME}/.local/bin"
AUTOSTART="${HOME}/.config/autostart"
NAME="fifine-ptt"

echo "==> Установка в ${BIN}"
mkdir -p "$BIN"
for f in fifine-ptt fifine-ptt-selftest mic-status; do
  install -Dm755 "${HERE}/${f}" "${BIN}/${f}"
  echo "    ${BIN}/${f}"
done

# Проверяем доступ к evdev: без группы input демон не сможет читать события.
if id -nG | tr ' ' '\n' | grep -qx input; then
  echo "==> Доступ к /dev/input: OK (пользователь в группе input)"
else
  echo
  echo "!! Пользователь ${USER} НЕ входит в группу input." >&2
  echo "   Демон не сможет читать события. Выполните (нужен root), затем перезайдите:" >&2
  echo "       sudo usermod -aG input ${USER}" >&2
  echo "   Либо разово, без перелогина — только для нужных устройств:" >&2
  echo "       sudo setfacl -m u:${USER}:rw /dev/input/event*" >&2
  echo
fi

echo "==> Поиск устройств"
if ! "${BIN}/${NAME}" --status; then
  echo "   Не удалось запустить --status; проверьте зависимости (pactl, python3)." >&2
fi

echo "==> Автозапуск"
mkdir -p "$AUTOSTART"
cat >"${AUTOSTART}/${NAME}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Fifine push-to-talk
Comment=Боковая кнопка мыши: hold-мьют. Сенсорная кнопка микрофона: синхронизация состояния.
Exec=env FIFINE_TOUCH=1 ${BIN}/${NAME}
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF
echo "    ${AUTOSTART}/${NAME}.desktop"

echo
echo "==> Готово."
echo "   Запустить сейчас:  FIFINE_TOUCH=1 ${BIN}/${NAME} &"
echo "   Проверить логику:  ${BIN}/fifine-ptt-selftest"
echo "   Смотреть состояние: watch -n0.3 ${BIN}/mic-status"
echo
echo "   Обработка сенсорной кнопки меняет поведение привычного контрола."
echo "   Если она не нужна — уберите FIFINE_TOUCH=1 из .desktop."
