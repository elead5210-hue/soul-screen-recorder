"""Discover avfoundation devices via ffmpeg and pick the ones we need.

ffmpeg prints the device list to stderr, in two sections:

    AVFoundation video devices:
    [AVFoundation indev @ 0x...] [0] FaceTime HD Camera
    [AVFoundation indev @ 0x...] [1] Capture screen 0
    AVFoundation audio devices:
    [AVFoundation indev @ 0x...] [0] MacBook Pro Microphone
    [AVFoundation indev @ 0x...] [1] BlackHole 2ch

Video and audio devices are numbered separately.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Tuple

# The user-facing messages live in recorder/errors.py so the wording is the
# same everywhere. FFMPEG_NOT_FOUND_MESSAGE is re-exported for other modules.
from recorder.errors import (
    BLACKHOLE_MISSING_MESSAGE,
    FFMPEG_NOT_FOUND_MESSAGE,
    device_not_found_message,
)

_DEVICE_LINE = re.compile(r"\[(\d+)\]\s+(.+?)\s*$")

# The dropdown/settings value meaning "pick this device automatically".
AUTO_CHOICE = "Auto-detect"

# avfoundation lists each display as a video device with this in its name.
SCREEN_NAME_MARKER = "capture screen"

# Name fragments of devices that are not a real camera or microphone. Auto-
# detection skips them (a device you pick yourself is always honoured).
_VIRTUAL_CAMERA_MARKERS = (
    "virtual", "snap camera", "manycam", "ndi video", "desk view",
)
_NON_MICROPHONE_MARKERS = (
    "blackhole", "multi-output", "aggregate", "soundflower", "loopback",
    "zoomaudiodevice", "virtual",
)


class DeviceError(Exception):
    """Raised when a required device or ffmpeg itself is missing."""


@dataclass(frozen=True)
class Device:
    index: int
    name: str


@dataclass(frozen=True)
class DeviceList:
    video: List[Device]
    audio: List[Device]


@dataclass(frozen=True)
class SelectedDevices:
    camera: Device
    microphone: Device
    screen: Device
    system_audio: Device


def find_ffmpeg() -> str:
    """Return the path to ffmpeg, or raise DeviceError if it is missing."""
    path = shutil.which("ffmpeg")
    if path is None:
        # Homebrew locations that may not be on PATH for GUI-launched apps.
        for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
            if shutil.which(candidate):
                return candidate
        raise DeviceError(FFMPEG_NOT_FOUND_MESSAGE)
    return path


def parse_device_list(output: str) -> DeviceList:
    """Parse the text ffmpeg prints for `-list_devices true`."""
    video: List[Device] = []
    audio: List[Device] = []
    section: Optional[List[Device]] = None

    for line in output.splitlines():
        lowered = line.lower()
        if "avfoundation video devices" in lowered:
            section = video
            continue
        if "avfoundation audio devices" in lowered:
            section = audio
            continue
        if section is None:
            continue
        match = _DEVICE_LINE.search(line)
        if match:
            section.append(Device(int(match.group(1)), match.group(2)))

    return DeviceList(video=video, audio=audio)


def list_devices(ffmpeg_path: Optional[str] = None) -> DeviceList:
    """Ask ffmpeg for the avfoundation devices and parse the result."""
    ffmpeg = ffmpeg_path or find_ffmpeg()
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "avfoundation",
             "-list_devices", "true", "-i", ""],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        raise DeviceError(FFMPEG_NOT_FOUND_MESSAGE)
    except subprocess.TimeoutExpired:
        raise DeviceError("Timed out while listing capture devices.")

    # ffmpeg exits non-zero here by design; the list is in stderr.
    return parse_device_list(result.stderr)


def _first_match(devices: List[Device], *needles: str,
                 exclude: Optional[List[str]] = None) -> Optional[Device]:
    exclude = [e.lower() for e in (exclude or [])]
    for device in devices:
        name = device.name.lower()
        if any(e in name for e in exclude):
            continue
        if any(n.lower() in name for n in needles):
            return device
    return None


def _is_screen(device: Device) -> bool:
    return SCREEN_NAME_MARKER in device.name.lower()


def _has_marker(device: Device, markers: Tuple[str, ...]) -> bool:
    name = device.name.lower()
    return any(marker in name for marker in markers)


def screen_options(devices: DeviceList) -> List[Device]:
    """Every screen that can be recorded."""
    return [d for d in devices.video if _is_screen(d)]


def camera_options(devices: DeviceList) -> List[Device]:
    """Every camera (video devices that are not screens)."""
    return [d for d in devices.video if not _is_screen(d)]


def microphone_options(devices: DeviceList) -> List[Device]:
    """Every audio input except BlackHole, which is reserved for system audio."""
    return [d for d in devices.audio if "blackhole" not in d.name.lower()]


def _find_named(options: List[Device], name: Optional[str]) -> Optional[Device]:
    """Return the device called `name` (case-insensitive), or None.

    Devices are matched by name because their indexes change when devices
    are plugged in or removed. None, an empty name or AUTO_CHOICE means
    "no preference"; a name that is not connected also gives None, so the
    caller falls back to auto-detection.
    """
    if not name:
        return None
    wanted = name.strip().lower()
    if not wanted or wanted == AUTO_CHOICE.lower():
        return None
    for device in options:
        if device.name.lower() == wanted:
            return device
    return None


def _auto_pick(options: List[Device], skip_markers: Tuple[str, ...]) -> Optional[Device]:
    """First device that is not virtual; if all are, the first device."""
    for device in options:
        if not _has_marker(device, skip_markers):
            return device
    return options[0] if options else None


def _chosen_name(name: Optional[str]) -> Optional[str]:
    """The device the user picked, or None when it is on Auto-detect."""
    if not name or not name.strip() or name.strip().lower() == AUTO_CHOICE.lower():
        return None
    return name.strip()


def select_devices(
    devices: DeviceList,
    camera_name: Optional[str] = None,
    microphone_name: Optional[str] = None,
    screen_name: Optional[str] = None,
) -> SelectedDevices:
    """Pick camera, microphone, screen and BlackHole from a device list.

    The optional names are the user's choices from the settings dropdowns.
    Any that is missing, AUTO_CHOICE, or not currently connected falls back
    to automatic detection. BlackHole is always found automatically.
    """
    screen_choices = screen_options(devices)
    screen = _find_named(screen_choices, screen_name) or (
        screen_choices[0] if screen_choices else None
    )
    if screen is None:
        raise DeviceError(
            device_not_found_message("screen", _chosen_name(screen_name))
            + " Also check that Screen Recording permission is granted in "
            "System Settings > Privacy & Security."
        )

    camera_choices = camera_options(devices)
    camera = _find_named(camera_choices, camera_name) or _auto_pick(
        camera_choices, _VIRTUAL_CAMERA_MARKERS
    )
    if camera is None:
        raise DeviceError(
            device_not_found_message("camera", _chosen_name(camera_name))
            + " Also check that Camera permission is granted in System "
            "Settings > Privacy & Security."
        )

    system_audio = _first_match(devices.audio, "blackhole")
    if system_audio is None:
        raise DeviceError(BLACKHOLE_MISSING_MESSAGE)

    microphone_choices = microphone_options(devices)
    microphone = _find_named(microphone_choices, microphone_name) or _auto_pick(
        microphone_choices, _NON_MICROPHONE_MARKERS
    )
    if microphone is None:
        raise DeviceError(
            device_not_found_message("microphone", _chosen_name(microphone_name))
            + " Also check that Microphone permission is granted in System "
            "Settings > Privacy & Security."
        )

    return SelectedDevices(
        camera=camera,
        microphone=microphone,
        screen=screen,
        system_audio=system_audio,
    )


def detect_devices(
    ffmpeg_path: Optional[str] = None,
    camera_name: Optional[str] = None,
    microphone_name: Optional[str] = None,
    screen_name: Optional[str] = None,
) -> SelectedDevices:
    """List devices and select the ones needed for recording.

    The optional names are the user's saved choices; see select_devices.
    """
    return select_devices(
        list_devices(ffmpeg_path),
        camera_name=camera_name,
        microphone_name=microphone_name,
        screen_name=screen_name,
    )