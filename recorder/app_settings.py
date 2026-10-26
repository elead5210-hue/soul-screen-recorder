"""The user's recording preferences, saved between runs.

These are the Settings section options: the size and corner of the
picture-in-picture presenter video, the folder recordings are saved in, and
the video quality preset. They are stored as JSON next to the device choices
(~/Library/Application Support/Soul Screen Recorder/settings.json on macOS),
not in the project folder, so they survive updates and are never committed.

Loading never raises: a missing or damaged file, or any value that is out of
range, just falls back to the default for that one value, so settings can
never stop a recording from starting. Saving is atomic, so an interrupted
save never leaves a half-written file behind.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from recorder.device_settings import SettingsError, default_settings_path

APP_SETTINGS_FILENAME = "settings.json"

# Picture-in-picture size (width in pixels of the presenter video).
DEFAULT_PIP_WIDTH = 320
MIN_PIP_WIDTH = 160
MAX_PIP_WIDTH = 960

# Picture-in-picture corners.
PIP_BOTTOM_RIGHT = "bottom-right"
PIP_BOTTOM_LEFT = "bottom-left"
PIP_TOP_RIGHT = "top-right"
PIP_TOP_LEFT = "top-left"
PIP_POSITIONS = (
    PIP_BOTTOM_RIGHT,
    PIP_BOTTOM_LEFT,
    PIP_TOP_RIGHT,
    PIP_TOP_LEFT,
)
DEFAULT_PIP_POSITION = PIP_BOTTOM_RIGHT

# Video quality presets (the bitrates they map to live in recorder.encoding).
QUALITY_LOW = "low"
QUALITY_MEDIUM = "medium"
QUALITY_HIGH = "high"
QUALITY_PRESETS = (QUALITY_LOW, QUALITY_MEDIUM, QUALITY_HIGH)
DEFAULT_QUALITY = QUALITY_MEDIUM

# An empty output folder means "use the default recordings folder".
DEFAULT_OUTPUT_FOLDER = ""

# Channel selection: a deselected channel is ignored when a recording starts.
DEFAULT_RECORD_SCREEN = True
DEFAULT_RECORD_SYSTEM_AUDIO = True
DEFAULT_RECORD_MIC = True
DEFAULT_RECORD_CAMERA = True


@dataclass(frozen=True)
class AppSettings:
    """Recording preferences; every field always holds a valid value."""

    pip_width: int = DEFAULT_PIP_WIDTH
    pip_position: str = DEFAULT_PIP_POSITION
    output_folder: str = DEFAULT_OUTPUT_FOLDER
    quality: str = DEFAULT_QUALITY
    record_screen: bool = DEFAULT_RECORD_SCREEN
    record_system_audio: bool = DEFAULT_RECORD_SYSTEM_AUDIO
    record_mic: bool = DEFAULT_RECORD_MIC
    record_camera: bool = DEFAULT_RECORD_CAMERA

    def output_path(self) -> Optional[Path]:
        """The chosen output folder, or None to use the default one."""
        if not self.output_folder:
            return None
        return Path(self.output_folder).expanduser()


def app_settings_path() -> Path:
    """Where the preferences file lives (next to devices.json)."""
    return default_settings_path().with_name(APP_SETTINGS_FILENAME)


def _clean_pip_width(value: Any) -> int:
    """Return a width within the allowed range, or the default."""
    # bool is an int subclass; True/False are not meaningful widths.
    if isinstance(value, bool):
        return DEFAULT_PIP_WIDTH
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return DEFAULT_PIP_WIDTH
    if not isinstance(value, (int, float)):
        return DEFAULT_PIP_WIDTH
    if value != value or value in (float("inf"), float("-inf")):
        return DEFAULT_PIP_WIDTH
    width = int(round(value))
    width = max(MIN_PIP_WIDTH, min(MAX_PIP_WIDTH, width))
    # ffmpeg's H.264 encoders need even dimensions.
    return width - (width % 2)


def _clean_choice(value: Any, allowed: tuple, default: str) -> str:
    """Return value (case-insensitive) if it is one of allowed, else default."""
    if not isinstance(value, str):
        return default
    choice = value.strip().lower()
    return choice if choice in allowed else default


def _clean_folder(value: Any) -> str:
    """Return a tidy folder path string, or "" for the default folder."""
    if not isinstance(value, str):
        return DEFAULT_OUTPUT_FOLDER
    folder = value.strip()
    if not folder or "\0" in folder:
        return DEFAULT_OUTPUT_FOLDER
    return folder


def _clean_bool(value: Any, default: bool) -> bool:
    """Return value if it is a real bool, else the default."""
    return value if isinstance(value, bool) else default


def clean_settings(settings: AppSettings) -> AppSettings:
    """Return a copy of settings with every field validated."""
    return AppSettings(
        pip_width=_clean_pip_width(settings.pip_width),
        pip_position=_clean_choice(
            settings.pip_position, PIP_POSITIONS, DEFAULT_PIP_POSITION
        ),
        output_folder=_clean_folder(settings.output_folder),
        quality=_clean_choice(settings.quality, QUALITY_PRESETS, DEFAULT_QUALITY),
        record_screen=_clean_bool(settings.record_screen, DEFAULT_RECORD_SCREEN),
        record_system_audio=_clean_bool(
            settings.record_system_audio, DEFAULT_RECORD_SYSTEM_AUDIO
        ),
        record_mic=_clean_bool(settings.record_mic, DEFAULT_RECORD_MIC),
        record_camera=_clean_bool(settings.record_camera, DEFAULT_RECORD_CAMERA),
    )


def load_app_settings(path: Optional[Path] = None) -> AppSettings:
    """Read the saved preferences; return defaults if missing or unusable."""
    target = Path(path) if path is not None else app_settings_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return AppSettings()
    if not isinstance(data, dict):
        return AppSettings()

    return AppSettings(
        pip_width=_clean_pip_width(data.get("pip_width")),
        pip_position=_clean_choice(
            data.get("pip_position"), PIP_POSITIONS, DEFAULT_PIP_POSITION
        ),
        output_folder=_clean_folder(data.get("output_folder")),
        quality=_clean_choice(data.get("quality"), QUALITY_PRESETS, DEFAULT_QUALITY),
        record_screen=_clean_bool(data.get("record_screen"), DEFAULT_RECORD_SCREEN),
        record_system_audio=_clean_bool(
            data.get("record_system_audio"), DEFAULT_RECORD_SYSTEM_AUDIO
        ),
        record_mic=_clean_bool(data.get("record_mic"), DEFAULT_RECORD_MIC),
        record_camera=_clean_bool(data.get("record_camera"), DEFAULT_RECORD_CAMERA),
    )


def save_app_settings(settings: AppSettings, path: Optional[Path] = None) -> None:
    """Write the preferences atomically. Raises SettingsError if that fails."""
    target = Path(path) if path is not None else app_settings_path()
    cleaned = clean_settings(settings)
    data = {
        "pip_width": cleaned.pip_width,
        "pip_position": cleaned.pip_position,
        "output_folder": cleaned.output_folder,
        "quality": cleaned.quality,
        "record_screen": cleaned.record_screen,
        "record_system_audio": cleaned.record_system_audio,
        "record_mic": cleaned.record_mic,
        "record_camera": cleaned.record_camera,
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
        raise SettingsError(f"Could not save the settings: {exc}")