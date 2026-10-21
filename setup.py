"""Build the double-clickable macOS app with py2app.

    ./build_app.sh                  (recommended: sets everything up)

or by hand, from the project folder:

    pip install -r requirements-build.txt
    python3 setup.py py2app

The result is dist/Soul Screen Recorder.app. This file is only used for
building the app; running the app from source (./run.sh) does not need it.

The Info.plist below holds the privacy usage descriptions macOS shows when
the app asks for Camera, Microphone and Screen Recording access. Without
them macOS stops a packaged app from using the camera and microphone.
"""

from setuptools import setup

# The supported platform is defined once, in recorder/compat.py, so the app,
# the startup check and this Info.plist always agree. compat.py only uses the
# standard library, so importing it here is safe.
from recorder.compat import MIN_MACOS_TEXT

APP_NAME = "Soul Screen Recorder"
BUNDLE_IDENTIFIER = "com.soulscreenrecorder.app"
VERSION = "1.0.0"
# The oldest macOS the app is meant to run on (see the README). Taken from
# recorder.compat.MIN_MACOS, the same minimum the source version checks.
MINIMUM_MACOS = MIN_MACOS_TEXT

APP = ["main.py"]

PLIST = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleIdentifier": BUNDLE_IDENTIFIER,
    "CFBundleVersion": VERSION,
    "CFBundleShortVersionString": VERSION,
    "LSMinimumSystemVersion": MINIMUM_MACOS,
    "LSApplicationCategoryType": "public.app-category.video",
    "NSHighResolutionCapable": True,
    # Privacy usage descriptions: shown in the macOS permission prompts.
    "NSCameraUsageDescription": (
        "Soul Screen Recorder records your camera so you can appear as the "
        "presenter in the picture-in-picture video."
    ),
    "NSMicrophoneUsageDescription": (
        "Soul Screen Recorder records your microphone so your voice is "
        "included in the recording."
    ),
    # Screen Recording has no required usage-description key; macOS asks for
    # it the first time the screen is captured. This text is used where the
    # system displays one.
    "NSScreenCaptureUsageDescription": (
        "Soul Screen Recorder records your screen (and the system audio "
        "played through BlackHole) as the main video."
    ),
}

OPTIONS = {
    # The app has no files to open or drop on it, so no argv emulation.
    "argv_emulation": False,
    "plist": PLIST,
    # Our own code, plus Tkinter for the window.
    "packages": ["recorder", "ui"],
    "includes": ["tkinter"],
    # Nothing else is imported, so keep the bundle small.
    "excludes": ["pytest", "unittest", "test"],
}

setup(
    name=APP_NAME,
    version=VERSION,
    app=APP,
    options={"py2app": OPTIONS},
)