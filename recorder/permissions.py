"""Detect the macOS privacy permissions the recorder needs.

Recording needs three permissions, granted to the app that launches Python
(for example Terminal, iTerm or an IDE), because ffmpeg runs as its child:

- Camera: to record the presenter
- Microphone: to record the presenter's voice
- Screen Recording ("Screen & System Audio Recording" on newer macOS)

Without Camera or Microphone access ffmpeg fails to open the device. Without
Screen Recording access the screen capture does not fail: macOS silently
records only the wallpaper, which is easy to miss until the video is played.
So the permissions are checked *before* recording starts and a clear message
is shown instead.

No extra Python packages are needed. The status is read through the system
frameworks with ctypes:

- Camera / Microphone: AVCaptureDevice authorizationStatusForMediaType:
  (AVFoundation), which tells "never asked" apart from "denied".
- Screen Recording: CGPreflightScreenCaptureAccess (CoreGraphics). macOS does
  not distinguish "never asked" from "denied" here, so both are DENIED.

Every function in this module is safe to call anywhere: nothing raises. On a
platform or macOS version where a status cannot be read, it is UNKNOWN, and
callers should let recording go ahead (macOS then asks, or ffmpeg reports the
problem itself).
"""

import ctypes
import subprocess
import sys
from enum import Enum
from typing import Dict, Iterable, List, Optional


class Permission(Enum):
    CAMERA = "camera"
    MICROPHONE = "microphone"
    SCREEN_RECORDING = "screen_recording"


class PermissionStatus(Enum):
    GRANTED = "granted"
    DENIED = "denied"                  # turned off (or restricted) for the app
    NOT_DETERMINED = "not_determined"  # macOS has not asked yet
    UNKNOWN = "unknown"                # could not be determined


# What each permission is called in the messages shown to the user.
_LABELS = {
    Permission.CAMERA: "Camera",
    Permission.MICROPHONE: "Microphone",
    Permission.SCREEN_RECORDING: "Screen Recording",
}

# The name of each pane in System Settings > Privacy & Security.
_PANE_NAMES = {
    Permission.CAMERA: "Camera",
    Permission.MICROPHONE: "Microphone",
    Permission.SCREEN_RECORDING: (
        "Screen & System Audio Recording (called Screen Recording "
        "on older macOS versions)"
    ),
}

# Deep links that open the matching privacy pane directly.
_SETTINGS_URLS = {
    Permission.CAMERA: (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_Camera"
    ),
    Permission.MICROPHONE: (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_Microphone"
    ),
    Permission.SCREEN_RECORDING: (
        "x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_ScreenCapture"
    ),
}

_OBJC_LIB = "/usr/lib/libobjc.dylib"
_AVFOUNDATION_LIB = "/System/Library/Frameworks/AVFoundation.framework/AVFoundation"
_COREFOUNDATION_LIB = (
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)
_COREGRAPHICS_LIB = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"

# AVMediaTypeVideo / AVMediaTypeAudio are the NSStrings "vide" and "soun".
_AV_MEDIA_TYPES = {
    Permission.CAMERA: "vide",
    Permission.MICROPHONE: "soun",
}

# AVAuthorizationStatus values.
_AV_NOT_DETERMINED = 0
_AV_RESTRICTED = 1
_AV_DENIED = 2
_AV_AUTHORIZED = 3

_K_CF_STRING_ENCODING_UTF8 = 0x08000100


def label(permission: Permission) -> str:
    """Human-readable name, e.g. 'Screen Recording'."""
    return _LABELS[permission]


# ---- reading the status ------------------------------------------------


def _av_status(permission: Permission) -> PermissionStatus:
    """Camera or Microphone status from AVCaptureDevice."""
    if sys.platform != "darwin":
        return PermissionStatus.UNKNOWN
    try:
        objc = ctypes.CDLL(_OBJC_LIB)
        ctypes.CDLL(_AVFOUNDATION_LIB)  # makes AVCaptureDevice available
        core_foundation = ctypes.CDLL(_COREFOUNDATION_LIB)

        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.objc_msgSend.restype = ctypes.c_long
        objc.objc_msgSend.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]

        core_foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
        core_foundation.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        core_foundation.CFRelease.restype = None
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]

        device_class = objc.objc_getClass(b"AVCaptureDevice")
        if not device_class:
            return PermissionStatus.UNKNOWN
        selector = objc.sel_registerName(b"authorizationStatusForMediaType:")

        media_type = core_foundation.CFStringCreateWithCString(
            None,
            _AV_MEDIA_TYPES[permission].encode("ascii"),
            _K_CF_STRING_ENCODING_UTF8,
        )
        if not media_type:
            return PermissionStatus.UNKNOWN
        try:
            raw = objc.objc_msgSend(device_class, selector, media_type)
        finally:
            core_foundation.CFRelease(media_type)
    except Exception:
        return PermissionStatus.UNKNOWN

    if raw == _AV_AUTHORIZED:
        return PermissionStatus.GRANTED
    if raw == _AV_NOT_DETERMINED:
        return PermissionStatus.NOT_DETERMINED
    if raw in (_AV_DENIED, _AV_RESTRICTED):
        return PermissionStatus.DENIED
    return PermissionStatus.UNKNOWN


def _core_graphics() -> Optional[ctypes.CDLL]:
    if sys.platform != "darwin":
        return None
    try:
        return ctypes.CDLL(_COREGRAPHICS_LIB)
    except OSError:
        return None


def _screen_status() -> PermissionStatus:
    """Screen Recording status from CGPreflightScreenCaptureAccess."""
    graphics = _core_graphics()
    if graphics is None:
        return PermissionStatus.UNKNOWN
    try:
        preflight = graphics.CGPreflightScreenCaptureAccess
        preflight.restype = ctypes.c_bool
        preflight.argtypes = []
        granted = bool(preflight())
    except Exception:
        # Not available before macOS 10.15.
        return PermissionStatus.UNKNOWN
    # macOS does not say whether it was ever asked, so "not granted" is
    # treated as denied: the screen capture would be blank.
    return PermissionStatus.GRANTED if granted else PermissionStatus.DENIED


def check_permission(permission: Permission) -> PermissionStatus:
    """The current status of one permission. Never raises."""
    try:
        if permission == Permission.SCREEN_RECORDING:
            return _screen_status()
        return _av_status(permission)
    except Exception:
        return PermissionStatus.UNKNOWN


def check_permissions() -> Dict[Permission, PermissionStatus]:
    """The status of Camera, Microphone and Screen Recording. Never raises."""
    return {
        Permission.CAMERA: check_permission(Permission.CAMERA),
        Permission.MICROPHONE: check_permission(Permission.MICROPHONE),
        Permission.SCREEN_RECORDING: check_permission(Permission.SCREEN_RECORDING),
    }


def missing_permissions(
    statuses: Dict[Permission, PermissionStatus],
) -> List[Permission]:
    """The permissions that are definitely turned off.

    NOT_DETERMINED and UNKNOWN are not included: macOS asks the first time
    the device is opened, and an unreadable status must never block
    recording.
    """
    return [
        permission
        for permission, status in statuses.items()
        if status == PermissionStatus.DENIED
    ]


# ---- messages for the user ---------------------------------------------


def _join_names(names: List[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def summary(missing: Iterable[Permission]) -> str:
    """One short line, e.g. 'Camera and Microphone access is turned off.'"""
    names = [label(p) for p in missing]
    if not names:
        return ""
    verb = "is" if len(names) == 1 else "are"
    return f"{_join_names(names)} access {verb} turned off."


def fix_instructions(missing: Iterable[Permission]) -> str:
    """Step-by-step instructions for turning the missing permissions on."""
    missing = list(missing)
    if not missing:
        return ""

    names = _join_names([label(p) for p in missing])
    panes = _join_names([_PANE_NAMES[p] for p in missing])
    pane_word = "pane" if len(missing) == 1 else "panes"
    return (
        f"Soul Screen Recorder needs {names} permission, and it is turned off.\n"
        "To fix this:\n"
        f"1. Open System Settings > Privacy & Security > {panes} "
        f"(the {pane_word} can also be opened with the button below).\n"
        "2. Turn on the app that launches Python, for example Terminal, "
        "iTerm or your code editor.\n"
        "3. Quit and reopen that app, then start the recorder again. macOS "
        "only applies a new permission to apps that are started afterwards.\n"
        "If the switch is missing or cannot be changed, your Mac may be "
        "managed by an organization that restricts this permission."
    )


# ---- acting on it ------------------------------------------------------


def request_screen_recording_access() -> bool:
    """Trigger the one-time macOS Screen Recording prompt.

    Returns True if access is already granted. When it is not, macOS shows
    its prompt (only the first time for this app) and the answer takes effect
    after the launching app is restarted. Never raises.
    """
    graphics = _core_graphics()
    if graphics is None:
        return False
    try:
        request = graphics.CGRequestScreenCaptureAccess
        request.restype = ctypes.c_bool
        request.argtypes = []
        return bool(request())
    except Exception:
        return False


def open_privacy_settings(permission: Permission) -> bool:
    """Open the System Settings privacy pane for a permission.

    Returns True if the pane was asked to open. Never raises.
    """
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["open", _SETTINGS_URLS[permission]],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0