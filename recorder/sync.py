"""Audio/video sync data for a session: sync.json.

The camera, screen, microphone and system-audio captures are four separate
ffmpeg processes, so they never start at exactly the same instant. Two kinds
of numbers describe that:

- launch_gap_seconds and launch_offsets_seconds: measured by the app when
  recording starts. launch_offsets_seconds gives, for each stream (camera,
  screen, mic, system), how long after the first process was launched that
  stream's process was launched (the first one is 0). launch_gap_seconds is
  the older single number: how long after the camera process the screen
  process was launched (positive means the screen started later). They are
  recorded for information and troubleshooting only; they are not applied
  automatically, because the time ffmpeg needs to open a device varies.
- camera_offset_seconds, mic_offset_seconds and system_offset_seconds: the
  fine-alignment corrections applied when the final video is composited,
  each relative to the screen recording. Positive delays that stream
  relative to the screen; negative makes it earlier. They are 0 until the
  user measures an offset (for example with a clap marker) and sets them
  with `python3 -m recorder.recomposite`.

A sync.json saved by the older two-file version has only
camera_offset_seconds, which then also covered the microphone (it was
recorded inside camera.mp4). When such a file is loaded, the microphone
offset takes the same value, so the alignment it described is kept.

Loading never raises: a missing or damaged file just gives the defaults, so
sync data can never stop a recording from being composited.
"""

import json
import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Optional

# Largest correction accepted, in seconds. Real offsets are a fraction of a
# second; anything beyond this is almost certainly a typing mistake.
MAX_OFFSET_SECONDS = 30.0

# The four recorded streams, in the order they are reported.
STREAM_NAMES = ("camera", "screen", "mic", "system")
# The streams that can be shifted. Each is aligned relative to the screen,
# so the screen itself has no offset.
OFFSET_STREAMS = ("camera", "mic", "system")

class SyncError(Exception):
    """Raised when a sync value is invalid or sync.json cannot be saved."""


@dataclass(frozen=True)
class SyncInfo:
    launch_gap_seconds: Optional[float] = None
    # Alignment offsets in seconds, each relative to the screen recording.
    camera_offset_seconds: float = 0.0
    mic_offset_seconds: float = 0.0
    system_offset_seconds: float = 0.0
    # Seconds after the first launch that each stream's process was launched,
    # keyed by stream name. Empty when it was not measured.
    launch_offsets_seconds: Dict[str, float] = field(default_factory=dict)


def validate_offset(value: Any, label: str = "camera") -> float:
    """Return `value` as a float offset in seconds, or raise SyncError.

    `label` names the stream (camera, mic or system) in the error message.
    """
    try:
        offset = float(value)
    except (TypeError, ValueError):
        raise SyncError(
            f"The {label} offset must be a number of seconds, got {value!r}."
        )
    if not math.isfinite(offset):
        raise SyncError(f"The {label} offset must be a finite number of seconds.")
    if abs(offset) > MAX_OFFSET_SECONDS:
        raise SyncError(
            f"The {label} offset must be between -{MAX_OFFSET_SECONDS:g} and "
            f"{MAX_OFFSET_SECONDS:g} seconds, got {offset:g}."
        )
    return offset


def _finite_or_none(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _offset_or_zero(value: Any, label: str) -> float:
    """A valid offset, or 0 when the value is missing or unusable."""
    try:
        return validate_offset(value, label)
    except SyncError:
        return 0.0


def _clean_launch_offsets(value: Any) -> Dict[str, float]:
    """Keep only the known streams that have a finite number of seconds."""
    if not isinstance(value, dict):
        return {}
    cleaned: Dict[str, float] = {}
    for name in STREAM_NAMES:
        number = _finite_or_none(value.get(name))
        if number is not None:
            cleaned[name] = number
    return cleaned


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
    launch_offsets = _clean_launch_offsets(data.get("launch_offsets_seconds"))

    camera = _offset_or_zero(data.get("camera_offset_seconds", 0.0), "camera")
    if "mic_offset_seconds" in data:
        mic = _offset_or_zero(data.get("mic_offset_seconds"), "mic")
    else:
        # Saved by the older two-file version: the microphone was recorded
        # inside camera.mp4 and shifted together with the camera, so it
        # keeps the camera's offset.
        mic = camera
    system = _offset_or_zero(data.get("system_offset_seconds", 0.0), "system")

    return SyncInfo(
        launch_gap_seconds=gap,
        camera_offset_seconds=camera,
        mic_offset_seconds=mic,
        system_offset_seconds=system,
        launch_offsets_seconds=launch_offsets,
    )


def save_sync(path: Path, info: SyncInfo) -> None:
    """Write sync.json atomically. Raises SyncError if it cannot be saved."""
    camera = validate_offset(info.camera_offset_seconds, "camera")
    mic = validate_offset(info.mic_offset_seconds, "mic")
    system = validate_offset(info.system_offset_seconds, "system")
    launch_offsets = _clean_launch_offsets(info.launch_offsets_seconds)
    data = {
        "launch_gap_seconds": (
            round(info.launch_gap_seconds, 4)
            if info.launch_gap_seconds is not None
            else None
        ),
        "launch_offsets_seconds": {
            name: round(seconds, 4) for name, seconds in launch_offsets.items()
        },
        "camera_offset_seconds": camera,
        "mic_offset_seconds": mic,
        "system_offset_seconds": system,
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


def record_launch_offsets(
    path: Path,
    launch_offsets_seconds: Dict[str, float],
    launch_gap_seconds: Optional[float] = None,
) -> SyncInfo:
    """Save each stream's measured launch time (seconds after the first launch).

    Any saved alignment offsets are kept. `launch_gap_seconds` is saved
    alongside when given.
    """
    info = replace(
        load_sync(path),
        launch_offsets_seconds=_clean_launch_offsets(launch_offsets_seconds),
    )
    if launch_gap_seconds is not None:
        info = replace(info, launch_gap_seconds=launch_gap_seconds)
    save_sync(path, info)
    return info


def set_stream_offset(path: Path, stream: str, offset_seconds: float) -> SyncInfo:
    """Save a new alignment offset for one stream (camera, mic or system).

    The offset is relative to the screen recording. The other offsets and the
    measured launch times are kept.
    """
    if stream not in OFFSET_STREAMS:
        raise SyncError(
            f"Unknown stream {stream!r}; choose one of: {', '.join(OFFSET_STREAMS)}."
        )
    offset = validate_offset(offset_seconds, stream)
    info = replace(load_sync(path), **{f"{stream}_offset_seconds": offset})
    save_sync(path, info)
    return info


def set_camera_offset(path: Path, camera_offset_seconds: float) -> SyncInfo:
    """Save a new camera offset, keeping every other saved value."""
    return set_stream_offset(path, "camera", camera_offset_seconds)