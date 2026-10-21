#!/usr/bin/env bash
# Build the double-clickable "Soul Screen Recorder.app" with py2app.
#
#   ./build_app.sh
#
# The app is written to dist/Soul Screen Recorder.app. It uses the same venv/
# virtual environment as run.sh, so the first build also sets that up. The
# build tools (py2app) come from requirements-build.txt; running the app from
# source (./run.sh) never needs them.

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
APP_NAME="Soul Screen Recorder"
APP_PATH="dist/$APP_NAME.app"

fail() {
    echo "Error: $1" >&2
    if [ -n "${2:-}" ]; then
        echo "" >&2
        echo "$2" >&2
    fi
    exit 1
}

# ---- checks -------------------------------------------------------------

[ "$(uname -s)" = "Darwin" ] ||
    fail "The app can only be built on macOS (py2app makes macOS apps)."

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

# ffmpeg is not packed into the app and is not needed to build it; the app
# looks for it when it runs. Warn now so it is not a surprise later.
if ! command -v ffmpeg >/dev/null 2>&1 \
    && [ ! -x /opt/homebrew/bin/ffmpeg ] \
    && [ ! -x /usr/local/bin/ffmpeg ]; then
    echo "Warning: ffmpeg is not installed. The app will build, but it needs"
    echo "ffmpeg to record. Install it with:  brew install ffmpeg"
    echo "(System audio also needs:  brew install --cask blackhole-2ch)"
    echo ""
fi

# ---- virtual environment and build tools ------------------------------------

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating the virtual environment in $VENV_DIR/ ..."
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR" ||
        fail "Could not create the virtual environment in $VENV_DIR/."
fi

PYTHON="$VENV_DIR/bin/python"

echo "Installing the build tools (py2app) ..."
"$PYTHON" -m pip install --quiet --disable-pip-version-check \
    -r requirements.txt -r requirements-build.txt ||
    fail "Could not install the build tools from requirements-build.txt."

# ---- build ------------------------------------------------------------------

# Start from a clean slate: stale files from an earlier build can end up in
# the new app.
rm -rf build dist

echo "Building $APP_NAME.app (this takes a minute) ..."
"$PYTHON" setup.py py2app >build.log 2>&1 || {
    tail -n 25 build.log >&2 || true
    fail "The build failed. The full log is in build.log."
}
rm -f build.log

[ -d "$APP_PATH" ] ||
    fail "The build finished but $APP_PATH was not created."

# Sign the app (ad hoc, no developer account needed) so macOS treats it as
# one stable app and remembers the permissions you give it.
if command -v codesign >/dev/null 2>&1; then
    codesign --force --deep --sign - "$APP_PATH" >/dev/null 2>&1 ||
        echo "Warning: could not sign the app. It still runs, but macOS may ask for permissions again after a rebuild."
fi

# ---- done -------------------------------------------------------------------

cat <<EOF

Built: $PROJECT_DIR/$APP_PATH

To use it:
  1. Open it:  open "$APP_PATH"
     (or double-click it in Finder; drag it to Applications to keep it)
  2. The first time, macOS asks for Camera and Microphone access. Click Allow.
  3. For the screen, open System Settings > Privacy & Security >
     Screen & System Audio Recording, turn on "$APP_NAME", then quit and
     reopen the app.
  4. System audio still needs BlackHole 2ch and a Multi-Output Device (see
     the README).

If macOS says the app cannot be opened because it is from an unidentified
developer, right-click the app, choose Open, then click Open.
EOF