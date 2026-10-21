"""Audio/video sync data for a session: sync.json.

The camera and screen captures are two separate ffmpeg processes, so they
never start at exactly the same instant. Two numbers describe that:

- launch_gap_seconds: measured by the app when recording starts. It is how
  long after the camera process was launched the screen process was
  launched (positive means the screen started later). It is recorded for
  information and troubleshooting only; it is not applied automatically,
  because the time ffmpeg needs to open a device varies.
- camera_offset_seconds: the fine-alignment correction applied when the
  final video is composited. Positive delays the presenter (camera video
  and microphone) relative to the screen; negative makes the presenter
  earlier. It is 0 until the user measures an offset (for example with a
  clap marker) and sets it with `python3 -m recorder.recomposite
  --camera-offset`.

Loading never raises: a missing or damaged file just gives the defaults, so
sync data can never stop a recording from being composited.
"""

import json
import math
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

# Largest correction accepted, in seconds. Real offsets are a fraction of a
# second; anything beyond this is almost certainly a typing mistake.
MAX_OFFSET_SECONDS = 30.0


class SyncError(Exception):
    """Raised when a sync value is invalid or sync.json cannot be saved."""


@dataclass(frozen=True)
class SyncInfo:
    launch_gap_seconds: Optional[float] = None
    camera_offset_seconds: float = 0.0


def validate_offset(value: Any) -> float:
    """Return `value` as a float offset in seconds, or raise SyncError."""
    try:
        offset = float(value)
    except (TypeError, ValueError):
        raise SyncError(f"The camera offset must be a number of seconds, got {value!r}.")
    if not math.isfinite(offset):
        raise SyncError("The camera offset must be a finite number of seconds.")
    if abs(offset) > MAX_OFFSET_SECONDS:
        raise SyncError(
            f"The camera offset must be between -{MAX_OFFSET_SECONDS:g} and "
            f"{MAX_OFFSET_SECONDS:g} seconds, got {offset:g}."
        )
    return offset


def _finite_or_none(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_sync(path: Path) -> SyncInfo:
    """Read sync.json; return defaults if it is missing or unusable."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return SyncInfo()
    if not isinstance(data, dict):
        return SyncInfo()

    gap = _finite_or_none(data.get("launch_gap_seconds"))

    try:
        offset = validate_offset(data.get("camera_offset_seconds", 0.0))
    except SyncError:
        offset = 0.0

    return SyncInfo(launch_gap_seconds=gap, camera_offset_seconds=offset)


def save_sync(path: Path, info: SyncInfo) -> None:
    """Write sync.json atomically. Raises SyncError if it cannot be saved."""
    offset = validate_offset(info.camera_offset_seconds)
    data = {
        "launch_gap_seconds": (
            round(info.launch_gap_seconds, 4)
            if info.launch_gap_seconds is not None
            else None
        ),
        "camera_offset_seconds": offset,
    }

    path = Path(path)
    temp = path.with_name(path.name + ".part")
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(temp, path)
    except OSError as exc:
        try:
            temp.unlink()
        except OSError:
            pass
        raise SyncError(f"Could not save {path.name}: {exc}")


def record_launch_gap(path: Path, launch_gap_seconds: Optional[float]) -> SyncInfo:
    """Save a newly measured launch gap, keeping any saved camera offset."""
    info = replace(load_sync(path), launch_gap_seconds=launch_gap_seconds)
    save_sync(path, info)
    return info


def set_camera_offset(path: Path, camera_offset_seconds: float) -> SyncInfo:
    """Save a new camera offset, keeping the measured launch gap."""
    offset = validate_offset(camera_offset_seconds)
    info = replace(load_sync(path), camera_offset_seconds=offset)
    save_sync(path, info)
    return info