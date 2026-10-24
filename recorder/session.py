"""Per-recording session folder: <output folder>/YYYY-MM-DD_HH-MM/.

The output folder is the one chosen in Settings; when none is set (None or an
empty value) the default folder is used: recordings/ when running from source,
or ~/Movies/Soul Screen Recorder when running as the packaged .app (whose
working directory is inside the app and is not a place to save videos).

Each session folder holds four raw, independently recorded streams:

- camera.mp4: the presenter's face camera (video only)
- screen.mp4: the desktop (video only)
- mic.wav: the microphone (audio only)
- system.wav: the system audio, captured through BlackHole (audio only)

plus final.mp4, which is composited from them (screen with the camera in a
picture-in-picture overlay and the microphone and system audio as two
separate tracks), and sync.json with the session's sync measurements and
alignment offsets. The raw streams are kept so the session can be
re-composited later.
"""

import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from recorder.errors import friendly_message, low_disk_space_message

DEFAULT_OUTPUT_ROOT = Path("recordings")

CAMERA_FILENAME = "camera.mp4"
SCREEN_FILENAME = "screen.mp4"
MIC_FILENAME = "mic.wav"
SYSTEM_FILENAME = "system.wav"
FINAL_FILENAME = "final.mp4"
SYNC_FILENAME = "sync.json"

# Refuse to start a recording with less free space than this.
MIN_FREE_BYTES = 1024 * 1024 * 1024  # 1 GiB

# Default output folder of the packaged .app (see default_output_root).
PACKAGED_OUTPUT_ROOT = Path("~/Movies/Soul Screen Recorder")


def default_output_root() -> Path:
    """The folder used when no output folder is chosen in Settings.

    Running from source this is recordings/ in the folder the app was started
    from. A packaged .app (py2app sets sys.frozen) starts inside its own
    bundle, so it saves to ~/Movies/Soul Screen Recorder instead.
    """
    if getattr(sys, "frozen", False):
        return PACKAGED_OUTPUT_ROOT
    return DEFAULT_OUTPUT_ROOT


class SessionError(Exception):
    """Raised when the session folder cannot be created or is unusable."""


@dataclass(frozen=True)
class Session:
    folder: Path
    camera_path: Path
    screen_path: Path
    mic_path: Path
    system_path: Path
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
    """Create a new timestamped session folder and return its file paths.

    output_root is the folder chosen in Settings. None or an empty value
    means "not set" and falls back to default_output_root().
    """
    if output_root is None or not str(output_root).strip():
        root = default_output_root()
    else:
        root = Path(str(output_root).strip())
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
        mic_path=folder / MIC_FILENAME,
        system_path=folder / SYSTEM_FILENAME,
        final_path=folder / FINAL_FILENAME,
        sync_path=folder / SYNC_FILENAME,
    )