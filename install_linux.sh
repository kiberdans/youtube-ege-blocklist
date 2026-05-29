#!/usr/bin/env bash
set -euo pipefail

echo "=== Установка Python 3 + tkinter + customtkinter ==="

if command -v apt &>/dev/null; then
    echo "[Debian/Ubuntu/Mint]"
    sudo apt update
    sudo apt install -y python3 python3-tk python3-pip

elif command -v pacman &>/dev/null; then
    echo "[Arch/CachyOS/Manjaro/EndeavourOS]"
    sudo pacman -S --noconfirm python tk python-pip

elif command -v dnf &>/dev/null; then
    echo "[Fedora/RHEL]"
    sudo dnf install -y python3 python3-tkinter python3-pip

elif command -v zypper &>/dev/null; then
    echo "[openSUSE]"
    sudo zypper install -y python3 python3-tk python3-pip

elif command -v xbps-install &>/dev/null; then
    echo "[Void Linux]"
    sudo xbps-install -y python3 tk python3-pip

else
    echo "Не удалось определить пакетный менеджер."
    echo "Установите Python 3, pip и tkinter вручную."
    exit 1
fi

pip3 install --break-system-packages customtkinter 2>/dev/null || pip3 install customtkinter

echo ""
echo "Готово. Запустите: python3 main.py"
