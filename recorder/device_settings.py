"""The user's device choices, saved between runs.

The Devices dropdowns let the user pick a camera, microphone and screen
instead of relying on auto-detection. Each choice is stored as the device's
*name* (indexes change when devices are plugged in or removed), and
AUTO_CHOICE ("Auto-detect") means "pick it automatically".

The choices are saved as JSON in the user's application-support folder
(~/Library/Application Support/Soul Screen Recorder/devices.json on macOS),
not in the project folder, so they survive updates and are never committed.

Loading never raises: a missing or damaged file just gives the defaults, so
settings can never stop a recording from starting. Saving is atomic, so an
interrupted save never leaves a half-written file behind.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from recorder.devices import AUTO_CHOICE

APP_FOLDER_NAME = "Soul Screen Recorder"
SETTINGS_FILENAME = "devices.json"


class SettingsError(Exception):
    """Raised when the device settings cannot be saved."""


@dataclass(frozen=True)
class DeviceSettings:
    """Chosen device names; AUTO_CHOICE means auto-detect."""

    camera: str = AUTO_CHOICE
    microphone: str = AUTO_CHOICE
    screen: str = AUTO_CHOICE


def default_settings_path() -> Path:
    """Where the settings file lives for the current user."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        # Not a supported platform for recording, but keep paths sensible
        # so the module can still be imported and tested elsewhere.
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_FOLDER_NAME / SETTINGS_FILENAME


def _clean_choice(value: Any) -> str:
    """Return a usable device name, or AUTO_CHOICE for anything else."""
    if not isinstance(value, str):
        return AUTO_CHOICE
    name = value.strip()
    return name if name else AUTO_CHOICE


def load_settings(path: Optional[Path] = None) -> DeviceSettings:
    """Read the saved choices; return defaults if missing or unusable."""
    target = Path(path) if path is not None else default_settings_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return DeviceSettings()
    if not isinstance(data, dict):
        return DeviceSettings()

    return DeviceSettings(
        camera=_clean_choice(data.get("camera")),
        microphone=_clean_choice(data.get("microphone")),
        screen=_clean_choice(data.get("screen")),
    )


def save_settings(settings: DeviceSettings, path: Optional[Path] = None) -> None:
    """Write the choices atomically. Raises SettingsError if that fails."""
    target = Path(path) if path is not None else default_settings_path()
    data = {
        "camera": _clean_choice(settings.camera),
        "microphone": _clean_choice(settings.microphone),
        "screen": _clean_choice(settings.screen),
    }

    temp = target.with_name(target.name + ".part")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(temp, target)
    except OSError as exc:
        try:
            temp.unlink()
        except OSError:
            pass
        raise SettingsError(f"Could not save the device settings: {exc}")