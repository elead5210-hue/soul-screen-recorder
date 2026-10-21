"""Friendly error messages for the problems people actually run into.

Everything the user can fix has one clear message here: what went wrong, and
what to do about it. The other modules take their texts from this file, so
the wording is the same wherever the problem is noticed:

- ffmpeg is not installed
- BlackHole 2ch is missing
- a camera, microphone or screen was not found (or cannot be opened)
- low disk space before recording, or a full disk while recording

Raw ffmpeg log output is hard to read ("Input/output error", "Selected
device not found"). `explain_ffmpeg_output` recognises the common cases and
turns them into a `FriendlyError`; `friendly_message` does the same for an
exception. Nothing in this module raises, and unknown problems fall back to
the original text, so a real error is never hidden.
"""

import errno
import re
from dataclasses import dataclass
from typing import Optional, Union

# ---- shared messages ---------------------------------------------------

FFMPEG_NOT_FOUND_MESSAGE = (
    "ffmpeg was not found. Install it with: brew install ffmpeg"
)

BLACKHOLE_MISSING_MESSAGE = (
    "BlackHole 2ch was not found, so system audio cannot be captured. "
    "Install it with: brew install --cask blackhole-2ch "
    "(then restart your Mac if it does not show up as an audio device)."
)

DISK_FULL_MESSAGE = (
    "The disk is full, so the recording could not be written. Free up some "
    "space (empty the Trash or delete files you no longer need) and record "
    "again. Everything recorded before the disk filled up may still be "
    "playable."
)

FOLDER_NOT_WRITABLE_MESSAGE = (
    "The recordings folder cannot be written to. Check that the folder "
    "exists and that you have permission to save files there, or run the "
    "app from a different folder."
)


def device_not_found_message(kind: str, name: Optional[str] = None) -> str:
    """A device of this kind ("camera", "microphone", "screen") is missing."""
    what = f'The {kind} "{name}"' if name else f"No {kind}"
    return (
        f"{what} was not found. Connect it, make sure no other app has "
        f"claimed it, then click Refresh in the Devices section"
        f"{' or choose another one' if name else ''}."
    )


def device_unavailable_message(kind: Optional[str] = None) -> str:
    """A device exists but ffmpeg could not open it."""
    what = f"the {kind}" if kind else "a camera, microphone or screen"
    return (
        f"ffmpeg could not open {what}. Check that Camera, Microphone and "
        "Screen Recording access is turned on for the app that launches "
        "Python (System Settings > Privacy & Security), that no other app "
        "is using the device, and then try again."
    )


def low_disk_space_message(free_mb: int, required_mb: int, where: str = "") -> str:
    """Not enough free space to start a recording."""
    place = f" where recordings are saved ({where})" if where else ""
    return (
        f"Low disk space: only {free_mb} MB free{place}, and at least "
        f"{required_mb} MB is needed to record. Free up some space (empty "
        "the Trash or delete files you no longer need) and try again."
    )


# ---- structured form ---------------------------------------------------


@dataclass(frozen=True)
class FriendlyError:
    """A problem in plain words, with what to do about it."""

    title: str  # what went wrong, one sentence
    fix: str = ""  # what the user can do about it

    def text(self) -> str:
        """The message shown under the status."""
        if self.fix:
            return f"{self.title} {self.fix}"
        return self.title


# ---- recognising ffmpeg output ----------------------------------------

_FLAGS = re.IGNORECASE

_DISK_FULL = re.compile(r"no space left on device|disk quota exceeded", _FLAGS)
_NOT_WRITABLE = re.compile(
    r"(permission denied|read-only file system)[^\n]*\.mp4|"
    r"\.mp4[^\n]*(permission denied|read-only file system)",
    _FLAGS,
)
_DEVICE_NOT_FOUND = re.compile(
    r"(video|audio|selected)\s+device\s+not\s+found|"
    r"could not find (video|audio) device|"
    r"no such (video |audio )?device",
    _FLAGS,
)
_DEVICE_BUSY = re.compile(
    r"device or resource busy|already in use|in use by another", _FLAGS
)
_DEVICE_UNAVAILABLE = re.compile(
    r"failed to create av capture input device|"
    r"cannot use [^\n]+|"
    r"error opening input[^\n]*input/output error|"
    r"input/output error",
    _FLAGS,
)
_UNSUPPORTED_MODE = re.compile(
    r"selected (framerate|pixel format|video size)[^\n]*not supported|"
    r"supported modes",
    _FLAGS,
)
_FFMPEG_MISSING = re.compile(r"ffmpeg: (command )?not found|no such file.*ffmpeg", _FLAGS)


def explain_ffmpeg_output(
    output: str, kind: Optional[str] = None
) -> Optional[FriendlyError]:
    """Turn ffmpeg's log text into a friendly error, or None if unrecognised.

    `kind` says what was being opened ("camera", "microphone" or "screen")
    when the caller knows, so the message can name it.
    """
    if not output:
        return None
    try:
        if _DISK_FULL.search(output):
            return FriendlyError(DISK_FULL_MESSAGE)
        if _NOT_WRITABLE.search(output):
            return FriendlyError(FOLDER_NOT_WRITABLE_MESSAGE)
        if _FFMPEG_MISSING.search(output):
            return FriendlyError(FFMPEG_NOT_FOUND_MESSAGE)
        if _DEVICE_NOT_FOUND.search(output):
            return FriendlyError(device_not_found_message(kind or "device"))
        if _DEVICE_BUSY.search(output):
            return FriendlyError(
                f"The {kind or 'device'} is being used by another app.",
                "Close the other app (a video call, for example) and try again.",
            )
        if _UNSUPPORTED_MODE.search(output):
            return FriendlyError(
                f"The {kind or 'device'} does not support the recording "
                "settings (30 fps).",
                "Choose a different one in the Devices section.",
            )
        if _DEVICE_UNAVAILABLE.search(output):
            return FriendlyError(device_unavailable_message(kind))
    except re.error:  # pragma: no cover - patterns are constants
        return None
    return None


def last_log_lines(output: str, count: int = 4) -> str:
    """The last few non-empty lines of ffmpeg output, for secondary detail."""
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    return "\n".join(lines[-count:])


def friendly_ffmpeg_failure(
    output: str, kind: Optional[str] = None, headline: str = ""
) -> str:
    """A message for a failed ffmpeg run.

    A recognised problem is explained in plain words, with the last log
    lines added as detail. An unrecognised one keeps the original wording:
    the headline followed by the last log lines.
    """
    explained = explain_ffmpeg_output(output, kind)
    excerpt = last_log_lines(output)
    if explained is not None:
        message = explained.text()
        if excerpt:
            message += f"\n\nffmpeg said:\n{excerpt}"
        return message
    parts = [part for part in (headline, excerpt) if part]
    return "\n".join(parts)


# ---- exceptions --------------------------------------------------------


def friendly_message(error: Union[BaseException, str]) -> str:
    """A readable message for any exception (or text) shown as an Error.

    Messages the app wrote itself are already clear and are returned as they
    are. Operating-system errors and raw ffmpeg text are translated. Never
    raises and never returns an empty string.
    """
    try:
        if isinstance(error, OSError):
            code = error.errno
            if code == errno.ENOSPC or code == getattr(errno, "EDQUOT", None):
                return DISK_FULL_MESSAGE
            if code in (errno.EACCES, errno.EPERM, errno.EROFS):
                return FOLDER_NOT_WRITABLE_MESSAGE
            if isinstance(error, FileNotFoundError) and "ffmpeg" in str(error).lower():
                return FFMPEG_NOT_FOUND_MESSAGE

        text = str(error).strip()
        explained = explain_ffmpeg_output(text)
        if explained is not None:
            return explained.text()
        if text:
            return text
        return f"Something went wrong ({type(error).__name__})." if not isinstance(
            error, str
        ) else "Something went wrong."
    except Exception:
        return "Something went wrong."