#!/usr/bin/env bash
# One-command launcher for Soul Screen Recorder.
#
#   ./run.sh
#
# Works from any folder. On the first run it creates a virtual environment
# (venv/) and installs requirements.txt; later runs only reinstall when
# requirements.txt has changed. It also checks that Python has Tkinter and
# that ffmpeg is installed before starting the app, and prints the Homebrew
# command to fix whatever is missing.

set -euo pipefail

# Always work from the project folder, wherever the script was started from.
SCRIPT_PATH="${BASH_SOURCE[0]}"
while [ -L "$SCRIPT_PATH" ]; do
    LINK_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
    SCRIPT_PATH="$(readlink "$SCRIPT_PATH")"
    case "$SCRIPT_PATH" in
        /*) ;;
        *) SCRIPT_PATH="$LINK_DIR/$SCRIPT_PATH" ;;
    esac
done
PROJECT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$PROJECT_DIR"

VENV_DIR="venv"
REQUIREMENTS="requirements.txt"
STAMP="$VENV_DIR/.requirements.stamp"

fail() {
    echo "Error: $1" >&2
    if [ -n "${2:-}" ]; then
        echo "" >&2
        echo "$2" >&2
    fi
    exit 1
}

# ---- Python and Tkinter ---------------------------------------------------

command -v python3 >/dev/null 2>&1 ||
    fail "python3 was not found." \
"Install Python 3.9 or newer, for example with Homebrew:
    brew install python python-tk"

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' ||
    fail "Python 3.9 or newer is required (found $(python3 -V 2>&1))." \
"Install a newer Python, for example with Homebrew:
    brew install python python-tk"

python3 -c 'import tkinter' >/dev/null 2>&1 ||
    fail "Python has no Tkinter, which the app window needs." \
"If you use Homebrew Python, install it with:
    brew install python-tk
(The python.org installer includes Tkinter.)"

# ---- ffmpeg ---------------------------------------------------------------

# Apps started from the Finder or an editor may not have Homebrew on PATH, so
# look in the usual Homebrew folders too (the app does the same).
FFMPEG=""
if command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG="$(command -v ffmpeg)"
elif [ -x /opt/homebrew/bin/ffmpeg ]; then
    FFMPEG=/opt/homebrew/bin/ffmpeg
elif [ -x /usr/local/bin/ffmpeg ]; then
    FFMPEG=/usr/local/bin/ffmpeg
fi

[ -n "$FFMPEG" ] ||
    fail "ffmpeg was not found, and recording needs it." \
"Install it with Homebrew:
    brew install ffmpeg
System audio also needs the BlackHole 2ch driver:
    brew install --cask blackhole-2ch"

# ---- virtual environment and dependencies -----------------------------------

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating the virtual environment in $VENV_DIR/ (first run only) ..."
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR" ||
        fail "Could not create the virtual environment in $VENV_DIR/."
fi

if [ -f "$REQUIREMENTS" ]; then
    CURRENT="$(cksum < "$REQUIREMENTS")"
    SAVED=""
    [ -f "$STAMP" ] && SAVED="$(cat "$STAMP")"
    if [ "$CURRENT" != "$SAVED" ]; then
        echo "Installing Python dependencies from $REQUIREMENTS ..."
        "$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check \
            -r "$REQUIREMENTS" ||
            fail "Could not install the Python dependencies from $REQUIREMENTS."
        echo "$CURRENT" > "$STAMP"
    fi
fi

# ---- start the app ----------------------------------------------------------

# exec replaces this script, so closing the window (or Ctrl+C) ends the app
# directly and its exit code is passed on.
exec "$VENV_DIR/bin/python" main.py "$@"