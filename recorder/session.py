"""Per-recording session folder: recordings/YYYY-MM-DD_HH-MM/.

Each session folder holds camera.mp4, screen.mp4 and final.mp4, so the raw
streams are kept and can be re-composited later, plus sync.json with the
session's audio/video sync measurements and alignment offset.
"""

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from recorder.errors import friendly_message, low_disk_space_message

DEFAULT_OUTPUT_ROOT = Path("recordings")

CAMERA_FILENAME = "camera.mp4"
SCREEN_FILENAME = "screen.mp4"
FINAL_FILENAME = "final.mp4"
SYNC_FILENAME = "sync.json"

# Refuse to start a recording with less free space than this.
MIN_FREE_BYTES = 1024 * 1024 * 1024  # 1 GiB


class SessionError(Exception):
    """Raised when the session folder cannot be created or is unusable."""


@dataclass(frozen=True)
class Session:
    folder: Path
    camera_path: Path
    screen_path: Path
    final_path: Path
    sync_path: Path


def _unique_folder(root: Path, started: datetime) -> Path:
    """Return a not-yet-existing folder named after the start time.

    Two recordings started within the same minute get a -2, -3, ...
    suffix so an earlier session is never overwritten.
    """
    base = root / started.strftime("%Y-%m-%d_%H-%M")
    candidate = base
    counter = 2
    while candidate.exists():
        candidate = root.with_name(root.name) / f"{base.name}-{counter}"
        counter += 1
    return candidate


def create_session(
    output_root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Session:
    """Create a new timestamped session folder and return its file paths."""
    root = Path(output_root) if output_root is not None else DEFAULT_OUTPUT_ROOT
    root = root.expanduser()

    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SessionError(
            f"Could not create the output folder {root}. {friendly_message(exc)}"
        )

    try:
        free = shutil.disk_usage(root).free
    except OSError as exc:
        raise SessionError(
            f"Could not check the free disk space in {root}. "
            f"{friendly_message(exc)}"
        )
    if free < MIN_FREE_BYTES:
        raise SessionError(
            low_disk_space_message(
                free // (1024 * 1024), MIN_FREE_BYTES // (1024 * 1024), str(root)
            )
        )

    folder = _unique_folder(root, now or datetime.now())
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise SessionError(
            f"Could not create the session folder {folder}. {friendly_message(exc)}"
        )

    return Session(
        folder=folder,
        camera_path=folder / CAMERA_FILENAME,
        screen_path=folder / SCREEN_FILENAME,
        final_path=folder / FINAL_FILENAME,
        sync_path=folder / SYNC_FILENAME,
    )