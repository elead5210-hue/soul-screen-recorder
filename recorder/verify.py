"""Check that a recording session holds three playable video files.

A finished session folder should contain camera.mp4, screen.mp4 and
final.mp4. For each one this module checks that the file

  1. exists and is not empty,
  2. opens in ffmpeg and has a video stream, and
  3. really decodes: the first video frame is read and decoded.

Usage from a terminal (exit status 0 = all three files are playable):

    python3 -m recorder.verify recordings/2026-10-21_14-46

The app itself uses check_file() on final.mp4 after compositing, so the Done
status only appears when the file the user cares about can be played.

With the --audio option (or verify_session(..., with_audio=True)) the sound
is measured too, with ffmpeg's volumedetect filter:

    python3 -m recorder.verify recordings/2026-10-21_14-46 --audio

  - final.mp4 must have an audio track that is not silent (the mic and the
    system audio mixed together). Missing or silent audio fails the check; a
    quiet but present track passes with a WARN line.
  - camera.mp4 (the microphone) and screen.mp4 (the system audio) are
    reported too, but silence there is only a WARN: nothing may have been
    playing, or nobody may have spoken.

With the --lengths option (or verify_session(..., with_lengths=True)) the
length of each file's audio is compared with the length of its video, which
catches audio that was dropped during a long recording: audio a couple of
seconds shorter is a WARN, clearly shorter is a FAIL. With --min-minutes the
session must also be at least that long, so a long session can be confirmed
complete:

    python3 -m recorder.verify recordings/2026-10-21_14-46 --min-minutes 30

Nothing here modifies a file: ffmpeg only reads the files and writes the
decoded frame or audio to nowhere (`-f null`).
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from recorder.devices import find_ffmpeg
from recorder.session import CAMERA_FILENAME, FINAL_FILENAME, SCREEN_FILENAME

# The files a finished session must contain, in the order they are reported.
EXPECTED_FILES: Tuple[str, ...] = (CAMERA_FILENAME, SCREEN_FILENAME, FINAL_FILENAME)

# Opening a file and decoding one frame only reads its start, so this is a
# generous limit that is never reached for a healthy file.
CHECK_TIMEOUT_SECONDS = 60

# Measuring the sound decodes the whole audio track, which takes a few seconds
# for a long recording.
AUDIO_TIMEOUT_SECONDS = 300

# Peak levels in dB (0 dB is the loudest possible sound). Below the first
# value the track is treated as silent; below the second it is audible but
# quiet enough to be worth a warning.
SILENT_PEAK_DB = -60.0
QUIET_PEAK_DB = -20.0

# Dropped-audio check: how much shorter than its video a file's audio may be.
# From the first value up is a warning; beyond the larger of the second value
# and the given share of the video length the check fails.
AUDIO_GAP_WARN_SECONDS = 2.0
AUDIO_GAP_FAIL_SECONDS = 5.0
AUDIO_GAP_FAIL_RATIO = 0.02
# A file may be this much shorter than the required minimum length.
MIN_LENGTH_TOLERANCE_SECONDS = 1.0

_TIME_RE = re.compile(r"time=\s*(\d+):(\d+):(\d+(?:\.\d+)?)")

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_MEAN_RE = re.compile(r"mean_volume:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dB")
_PEAK_RE = re.compile(r"max_volume:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dB")


class VerifyError(Exception):
    """Raised when the check itself cannot run (for example no ffmpeg)."""


@dataclass(frozen=True)
class FileCheck:
    """Result for one file."""

    name: str
    path: Path
    ok: bool
    detail: str
    # Length in seconds when ffmpeg reports one (None if unknown).
    duration_seconds: Optional[float] = None
    # A passed check that still deserves attention (shown as WARN).
    warning: bool = False
    # "file" for a video file check, "audio" for a sound level check.
    kind: str = "file"


@dataclass(frozen=True)
class SessionCheck:
    """Result for a whole session folder."""

    folder: Path
    files: Tuple[FileCheck, ...]

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.files)

    @property
    def failed(self) -> List[FileCheck]:
        return [f for f in self.files if not f.ok]

    @property
    def video_files(self) -> List[FileCheck]:
        return [f for f in self.files if f.kind == "file"]

    @property
    def audio_files(self) -> List[FileCheck]:
        return [f for f in self.files if f.kind == "audio"]


def _parse_duration(text: str) -> Optional[float]:
    """Return the duration ffmpeg printed, or None (fragmented MP4 may say N/A)."""
    match = _DURATION_RE.search(text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_duration(seconds: Optional[float]) -> str:
    """Human-readable length such as 1:02:03 or 0:45 (empty if unknown)."""
    if seconds is None:
        return ""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def check_file(path: Path, ffmpeg: Optional[str] = None) -> FileCheck:
    """Check that one video file exists, opens and decodes its first frame.

    Never raises for a bad file: every problem becomes a FileCheck with
    ok=False and a plain-words detail. Raises VerifyError only if ffmpeg
    itself is missing, because then no file can be checked at all.
    """
    path = Path(path)
    name = path.name

    try:
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
    except OSError as exc:
        return FileCheck(name, path, False, f"cannot be read ({exc.strerror or exc})")
    if not exists:
        return FileCheck(name, path, False, "is missing")
    if size == 0:
        return FileCheck(name, path, False, "is empty (0 bytes)")

    if ffmpeg is None:
        try:
            ffmpeg = find_ffmpeg()
        except Exception as exc:
            raise VerifyError(str(exc))

    cmd = [
        ffmpeg, "-hide_banner", "-nostdin",
        "-i", str(path),
        "-map", "0:v:0",
        "-frames:v", "1",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=CHECK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return FileCheck(name, path, False, "took too long to open and may be damaged")
    except OSError as exc:
        raise VerifyError(f"Could not run ffmpeg: {exc}")

    text = result.stderr.decode("utf-8", errors="replace")
    duration = _parse_duration(text)

    if "matches no streams" in text or (
        result.returncode != 0 and "Video:" not in text and "moov atom" not in text
        and "Invalid data" not in text
    ):
        return FileCheck(name, path, False, "has no video stream", duration)
    if "moov atom not found" in text or "Invalid data found" in text:
        return FileCheck(
            name, path, False, "cannot be opened and may be unplayable", duration
        )
    if result.returncode != 0:
        return FileCheck(
            name, path, False, "was opened but its video could not be decoded", duration
        )

    length = format_duration(duration)
    detail = f"is playable ({length})" if length else "is playable"
    return FileCheck(name, path, True, detail, duration)


@dataclass(frozen=True)
class AudioLevels:
    """What volumedetect found in a file's first audio track."""

    has_audio: bool
    mean_db: Optional[float] = None
    peak_db: Optional[float] = None


def parse_audio_levels(text: str) -> AudioLevels:
    """Read the levels from ffmpeg's log (see the volumedetect filter).

    A log with no audio stream gives has_audio=False; one with an audio
    stream but no measurement gives has_audio=True with unknown levels.
    """
    if "matches no streams" in text:
        return AudioLevels(False)
    mean = _MEAN_RE.search(text)
    peak = _PEAK_RE.search(text)
    return AudioLevels(
        True,
        float(mean.group(1)) if mean else None,
        float(peak.group(1)) if peak else None,
    )


def check_audio(
    path: Path,
    label: str,
    ffmpeg: Optional[str] = None,
    required: bool = False,
) -> FileCheck:
    """Measure the sound in a file's first audio track.

    `label` says what the sound is (for example "microphone"). With
    required=True a missing, silent or unreadable track fails the check;
    otherwise those cases are only warnings. A quiet track always passes
    with a warning. Raises VerifyError only if ffmpeg itself is missing.
    """
    path = Path(path)
    name = f"{path.name} audio ({label})"

    def problem(detail: str) -> FileCheck:
        return FileCheck(name, path, not required, detail, warning=True, kind="audio")

    if ffmpeg is None:
        try:
            ffmpeg = find_ffmpeg()
        except Exception as exc:
            raise VerifyError(str(exc))

    cmd = [
        ffmpeg, "-hide_banner", "-nostdin",
        "-i", str(path),
        "-map", "0:a:0",
        "-vn",
        "-af", "volumedetect",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=AUDIO_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return problem("took too long to measure")
    except OSError as exc:
        raise VerifyError(f"Could not run ffmpeg: {exc}")

    text = result.stderr.decode("utf-8", errors="replace")
    levels = parse_audio_levels(text)

    if not levels.has_audio:
        return problem("has no audio track")
    if result.returncode != 0:
        return problem("has an audio track that could not be read")
    if levels.peak_db is None:
        # The track exists but the level could not be read from the log.
        return FileCheck(
            name, path, True, "has an audio track (level not measured)",
            warning=True, kind="audio",
        )

    mean = f"mean {levels.mean_db:.1f} dB, " if levels.mean_db is not None else ""
    measured = f"{mean}peak {levels.peak_db:.1f} dB"
    if levels.peak_db <= SILENT_PEAK_DB:
        return problem(f"is silent ({measured})")
    if levels.peak_db < QUIET_PEAK_DB:
        return FileCheck(
            name, path, True,
            f"is quiet ({measured}); raise the volume of the source",
            warning=True, kind="audio",
        )
    return FileCheck(name, path, True, f"is audible ({measured})", kind="audio")


def measure_stream_seconds(
    path: Path, kind: str, ffmpeg: str, timeout: float = AUDIO_TIMEOUT_SECONDS
) -> Optional[float]:
    """Length in seconds of a file's first video ("v") or audio ("a") stream.

    The stream is copied to nowhere (no decoding, so it is fast) and the last
    timestamp ffmpeg reports is used. This works for fragmented MP4 files,
    which often have no total length in their header. Returns None if the
    stream is missing or cannot be measured. Raises VerifyError only if
    ffmpeg cannot be run.
    """
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin",
        "-i", str(path),
        "-map", f"0:{kind}:0",
        "-c", "copy",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError as exc:
        raise VerifyError(f"Could not run ffmpeg: {exc}")
    if result.returncode != 0:
        return None
    text = result.stderr.decode("utf-8", errors="replace")
    matches = _TIME_RE.findall(text)
    if not matches:
        return None
    hours, minutes, seconds = matches[-1]
    return max(0.0, int(hours) * 3600 + int(minutes) * 60 + float(seconds))


def check_length(
    path: Path,
    ffmpeg: Optional[str] = None,
    min_seconds: Optional[float] = None,
) -> FileCheck:
    """Compare a file's audio length with its video length (dropped audio).

    Audio clearly shorter than the video is a WARN or a FAIL (see the
    AUDIO_GAP_* values). With `min_seconds` the video must also be at least
    that long, otherwise the check fails. A file with no audio track is only
    judged on its length (the audio check reports missing audio). If the
    length cannot be measured the check only warns, unless a minimum length
    was asked for, in which case it fails. Raises VerifyError only if ffmpeg
    itself is missing.
    """
    path = Path(path)
    name = f"{path.name} length"

    if ffmpeg is None:
        try:
            ffmpeg = find_ffmpeg()
        except Exception as exc:
            raise VerifyError(str(exc))

    video = measure_stream_seconds(path, "v", ffmpeg)
    if video is None:
        return FileCheck(
            name, path, min_seconds is None, "could not be measured",
            warning=True, kind="length",
        )
    audio = measure_stream_seconds(path, "a", ffmpeg)

    ok = True
    warning = False
    parts = [f"is {format_duration(video)} long"]

    if min_seconds is not None and video < min_seconds - MIN_LENGTH_TOLERANCE_SECONDS:
        ok = False
        parts.append(f"which is shorter than the required {format_duration(min_seconds)}")

    if audio is not None:
        gap = video - audio
        fail_gap = max(AUDIO_GAP_FAIL_SECONDS, AUDIO_GAP_FAIL_RATIO * video)
        if gap > fail_gap:
            ok = False
            parts.append(
                f"but its audio is only {format_duration(audio)}, so audio was "
                "probably dropped"
            )
        elif gap >= AUDIO_GAP_WARN_SECONDS:
            warning = True
            parts.append(
                f"but its audio is {format_duration(audio)}, so some audio may "
                "have been dropped"
            )
        else:
            parts.append("and the audio and video lengths match")

    detail = " ".join(parts) if len(parts) == 1 else ", ".join(parts)
    return FileCheck(
        name, path, ok, detail, duration_seconds=video, warning=warning, kind="length"
    )


def verify_session(
    folder: Path,
    ffmpeg_path: Optional[str] = None,
    names: Sequence[str] = EXPECTED_FILES,
    with_audio: bool = False,
    with_lengths: bool = False,
    min_minutes: Optional[float] = None,
) -> SessionCheck:
    """Check every expected file in a session folder.

    With with_audio=True the sound levels of the files that passed the video
    check are measured as well (see check_audio). Raises VerifyError if the
    folder does not exist or ffmpeg is missing.
    """
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise VerifyError(f"Session folder not found: {folder}")

    ffmpeg = ffmpeg_path
    if ffmpeg is None:
        try:
            ffmpeg = find_ffmpeg()
        except Exception as exc:
            raise VerifyError(str(exc))

    files = [check_file(folder / name, ffmpeg) for name in names]

    if with_audio:
        # (what the sound is, whether missing or silent audio fails the check)
        audio_kinds = {
            CAMERA_FILENAME: ("microphone", False),
            SCREEN_FILENAME: ("system audio", False),
            FINAL_FILENAME: ("mic + system audio", True),
        }
        playable = {f.name for f in files if f.ok}
        for name in names:
            if name in audio_kinds and name in playable:
                label, required = audio_kinds[name]
                files.append(check_audio(folder / name, label, ffmpeg, required))

    if with_lengths or min_minutes is not None:
        min_seconds = float(min_minutes) * 60 if min_minutes is not None else None
        playable_files = {f.name for f in files if f.ok and f.kind == "file"}
        for name in names:
            if name in playable_files:
                files.append(check_length(folder / name, ffmpeg, min_seconds))

    return SessionCheck(folder=folder, files=tuple(files))


def format_report(check: SessionCheck) -> str:
    """A pass/fail checklist, one line per file plus a summary line."""
    lines = [f"Session: {check.folder}"]
    for item in check.files:
        if not item.ok:
            mark = "FAIL"
        elif item.warning:
            mark = "WARN"
        else:
            mark = "PASS"
        lines.append(f"  [{mark}] {item.name} {item.detail}")

    audio = check.audio_files
    if check.ok:
        lines.append(f"All {len(check.video_files)} files are playable.")
        if audio:
            lines.append("The final video's audio is audible.")
        if any(f.warning for f in check.files):
            lines.append("Check the WARN lines above.")
    else:
        noun = "checks" if len(check.files) != len(check.video_files) else "files"
        lines.append(
            f"{len(check.failed)} of {len(check.files)} {noun} failed the check."
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m recorder.verify",
        description=(
            "Check that a session folder holds three playable files: "
            f"{', '.join(EXPECTED_FILES)}."
        ),
    )
    parser.add_argument(
        "session_folder",
        type=Path,
        help="a session folder such as recordings/2026-10-21_14-46",
    )
    parser.add_argument(
        "--audio",
        action="store_true",
        help=(
            "also measure the sound: final.mp4 must have audible audio, and the "
            "microphone (camera.mp4) and system audio (screen.mp4) are reported"
        ),
    )
    parser.add_argument(
        "--lengths",
        action="store_true",
        help=(
            "also compare each file's audio length with its video length, to "
            "catch audio that was dropped during the recording"
        ),
    )
    parser.add_argument(
        "--min-minutes",
        type=float,
        default=None,
        metavar="MINUTES",
        help=(
            "also require every file to be at least this long (implies "
            "--lengths), e.g. 30 to confirm a 30-minute session is complete"
        ),
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        check = verify_session(
            args.session_folder,
            with_audio=args.audio,
            with_lengths=args.lengths,
            min_minutes=args.min_minutes,
        )
    except VerifyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(format_report(check))
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())