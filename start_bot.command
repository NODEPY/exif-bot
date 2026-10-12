#!/bin/zsh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

clear

echo "=============================="
echo "🤖 AI EXIF BOT"
echo "=============================="
echo ""

if [ ! -x "$SCRIPT_DIR/venv/bin/python3" ]; then

    echo "❌ venv не знайдено."
    echo "Спочатку створи середовище."
    echo ""

    read -k 1 "?Натисни будь-яку клавішу..."
    exit 1
fi

"$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/bot.py"

echo ""
echo "=============================="
echo "Бот завершив роботу"
echo "=============================="

read -k 1 "?Натисни будь-яку клавішу..."