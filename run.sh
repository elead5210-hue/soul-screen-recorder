#!/usr/bin/env bash
# One-command launcher for Soul Screen Recorder.
#
#   ./run.sh
#
# Works from any folder. On the first run it creates a virtual environment
# (venv/) and installs requirements.txt; later runs only reinstall when
# requirements.txt has changed. It also checks that Python has Tkinter and
# that ffmpeg is installed before starting the app, and prints the Homebrew
# command to fix whatever is missing. It also checks the Mac itself: macOS 13
# (Ventura) or newer, a Tk that can draw the window (8.6 or newer), and Apple
# Silicon vs Intel (including Python running under Rosetta), so the Homebrew
# hints point at the right folder (/opt/homebrew or /usr/local).

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

# ---- macOS version and processor --------------------------------------------

# The app supports macOS 13 (Ventura) or newer, on Apple Silicon and Intel Macs.
MIN_MACOS_MAJOR=13

# Homebrew lives in /opt/homebrew on Apple Silicon Macs and in /usr/local on
# Intel Macs. hw.optional.arm64 is 1 on an Apple Silicon chip even when this
# shell runs under Rosetta (where uname -m says x86_64).
BREW_PREFIX=/usr/local
CHIP="Intel"
if [ "$(uname -s)" = "Darwin" ]; then
    if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" = "1" ] ||
        [ "$(uname -m)" = "arm64" ]; then
        BREW_PREFIX=/opt/homebrew
        CHIP="Apple Silicon"
    fi

    # Without SYSTEM_VERSION_COMPAT=0, sw_vers can report 10.16 on newer macOS.
    MACOS_VERSION="$(SYSTEM_VERSION_COMPAT=0 sw_vers -productVersion 2>/dev/null || true)"
    MACOS_MAJOR="${MACOS_VERSION%%.*}"
    case "$MACOS_MAJOR" in
        ''|*[!0-9]*)
            # Version unknown: carry on, the app checks again when it starts.
            ;;
        *)
            if [ "$MACOS_MAJOR" -lt "$MIN_MACOS_MAJOR" ]; then
                fail "macOS $MACOS_VERSION is too old." \
"Soul Screen Recorder needs macOS 13 (Ventura) or newer.
Open System Settings > General > Software Update and install the newest
macOS offered for your Mac (on macOS 12 and older: Apple menu > System
Preferences > Software Update). If no update to macOS 13 or newer is
offered, this Mac is too old to record with this app."
            fi
            ;;
    esac
fi

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

# The Python that comes with macOS (/usr/bin/python3) has Tk 8.5, which draws
# blank or broken windows on current macOS. The app needs Tk 8.6 or newer.
python3 -c 'import sys, tkinter; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)' ||
    fail "This Python uses Tk $(python3 -c 'import tkinter; print(tkinter.TkVersion)' 2>/dev/null || echo '?'), which is too old for the app window." \
"The window needs Tk 8.6 or newer. Install a Python with a current Tk:
    brew install python python-tk
(Homebrew installs into $BREW_PREFIX on this $CHIP Mac. The python.org
installer also includes Tk 8.6.) Then open a new Terminal window, delete the
old virtual environment (rm -rf $VENV_DIR) and run ./run.sh again."

# An Intel Python on an Apple Silicon Mac runs through Rosetta: it works, but
# uses more CPU than a native build.
PY_MACHINE="$(python3 -c 'import platform; print(platform.machine())' 2>/dev/null || true)"
if [ "$CHIP" = "Apple Silicon" ] && [ "$PY_MACHINE" = "x86_64" ]; then
    echo "Note: this Mac has an Apple Silicon chip, but python3 is an Intel build" >&2
    echo "running under Rosetta, so the app will use more CPU than it needs to." >&2
    echo "For a native Python, install it with Homebrew (it lives in" >&2
    echo "$BREW_PREFIX on Apple Silicon):  brew install python python-tk" >&2
    echo "then delete $VENV_DIR/ (rm -rf $VENV_DIR) and run ./run.sh again." >&2
    echo "" >&2
fi

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