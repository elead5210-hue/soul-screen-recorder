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
from typing import List, Optional

FFMPEG_NOT_FOUND_MESSAGE = (
    "ffmpeg was not found. Install it with: brew install ffmpeg"
)

_DEVICE_LINE = re.compile(r"\[(\d+)\]\s+(.+?)\s*$")


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


def select_devices(devices: DeviceList) -> SelectedDevices:
    """Pick camera, microphone, screen and BlackHole from a device list."""
    screen = _first_match(devices.video, "capture screen")
    if screen is None:
        raise DeviceError(
            "No screen capture device found. Check that Screen Recording "
            "permission is granted in System Settings > Privacy & Security."
        )

    camera = _first_match(devices.video, exclude=["capture screen"],
                          *[""]) if False else None
    for device in devices.video:
        if "capture screen" not in device.name.lower():
            camera = device
            break
    if camera is None:
        raise DeviceError(
            "No camera found. Connect a camera and grant Camera permission "
            "in System Settings > Privacy & Security."
        )

    system_audio = _first_match(devices.audio, "blackhole")
    if system_audio is None:
        raise DeviceError(
            "BlackHole 2ch was not found, so system audio cannot be "
            "captured. Install it with: brew install --cask blackhole-2ch"
        )

    microphone = _first_match(devices.audio, exclude=["blackhole"], *[""])
    if microphone is None:
        for device in devices.audio:
            if "blackhole" not in device.name.lower():
                microphone = device
                break
    if microphone is None:
        raise DeviceError(
            "No microphone found. Connect a microphone and grant "
            "Microphone permission in System Settings > Privacy & Security."
        )

    return SelectedDevices(
        camera=camera,
        microphone=microphone,
        screen=screen,
        system_audio=system_audio,
    )


def detect_devices(ffmpeg_path: Optional[str] = None) -> SelectedDevices:
    """List devices and select the ones needed for recording."""
    return select_devices(list_devices(ffmpeg_path))