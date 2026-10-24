"""Safeguards that keep a long recording (30 minutes and more) healthy.

Three small, independent helpers, all standard library only:

- `KeepAwake` runs macOS's `caffeinate` while recording, so the Mac (and its
  display) does not go to sleep halfway through. A sleeping Mac stops all four
  captures (camera, screen, microphone and system audio) and leaves a gap in
  the recording. `caffeinate` is tied to the app's
  process, so it ends by itself even if the app crashes.
- `estimate_recording_bytes` and friends work out how much disk space a
  recording needs for a given length and quality preset, so a long recording
  does not run out of space halfway.
- `CaptureMonitor` is a background thread that checks every few seconds that
  the captures are still healthy: an ffmpeg process that quit early, a raw
  file that stopped growing (a stuck capture), or free disk space running
  low. Each problem is reported once through a callback. Fatal problems tell
  the caller to stop the recording cleanly so the files recorded so far are
  finalized and kept.

Nothing here raises. A helper that cannot do its job (no `caffeinate`, a disk
that cannot be queried, a callback that fails) simply does nothing, because a
safeguard must never be the thing that breaks a recording.

The monitor knows nothing about ffmpeg itself: it is given `Watch` objects
(a name, the file being written and a function that says whether the process
is still running), so it can be tested with fakes and without a Mac.
"""

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Set, Tuple

from recorder.capture import CAMERA_BITRATES
from recorder.encoding import DEFAULT_QUALITY, QUALITY_BITRATES

# ---- disk space estimate -------------------------------------------------

# The recording length the app plans for and tests against.
DEFAULT_PLANNED_MINUTES = 30

# Audio rates, matching the ffmpeg commands. The camera and screen files are
# video only. The microphone and the system audio are each their own
# uncompressed WAV file (48 kHz, 16-bit). Stereo is assumed, which is the
# larger case, so a mono device only makes the estimate a little generous.
# final.mp4 has two separate AAC tracks (microphone and system audio) at
# 192 kbit/s each.
CAPTURE_AUDIO_BPS = 48_000 * 16 * 2   # one WAV file: mic.wav or system.wav
CAPTURE_AUDIO_FILES = 2               # mic.wav and system.wav
FINAL_AUDIO_BPS = 192_000             # one AAC track in final.mp4
FINAL_AUDIO_TRACKS = 2                # microphone and system audio

# Extra room on top of the estimate: container overhead, fragment headers and
# bitrate overshoot of the hardware encoder.
SAFETY_MARGIN = 1.10

GIB = 1024 ** 3
MIB = 1024 ** 2


def parse_bitrate(text: object) -> int:
    """Turn an ffmpeg bitrate such as "8M" or "160k" into bits per second.

    ffmpeg uses 1000-based units. Returns 0 for anything unreadable.
    """
    try:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kKmM]?)\s*", str(text))
        if not match:
            return 0
        factor = {"": 1, "k": 1_000, "m": 1_000_000}[match.group(2).lower()]
        return int(float(match.group(1)) * factor)
    except Exception:
        return 0


def _preset(quality: object) -> str:
    """Normalise a quality preset name; unknown values mean the default."""
    name = quality.strip().lower() if isinstance(quality, str) else ""
    return name if name in QUALITY_BITRATES else DEFAULT_QUALITY


def recording_bytes_per_second(
    quality: object = DEFAULT_QUALITY, include_final: bool = True
) -> float:
    """Disk space used per second of recording, without any safety margin.

    Counts camera.mp4 and screen.mp4 (video only), mic.wav and system.wav
    and, unless `include_final` is False, the final.mp4 that is made when
    the recording stops.
    """
    name = _preset(quality)
    screen = parse_bitrate(QUALITY_BITRATES[name])
    camera = parse_bitrate(CAMERA_BITRATES.get(name, CAMERA_BITRATES[DEFAULT_QUALITY]))
    bits = screen + camera + CAPTURE_AUDIO_FILES * CAPTURE_AUDIO_BPS
    if include_final:
        bits += screen + FINAL_AUDIO_TRACKS * FINAL_AUDIO_BPS
    return bits / 8


def estimate_recording_bytes(
    minutes: float = DEFAULT_PLANNED_MINUTES,
    quality: object = DEFAULT_QUALITY,
    include_final: bool = True,
) -> int:
    """Disk space needed for a recording of `minutes`, with a safety margin."""
    try:
        seconds = max(0.0, float(minutes)) * 60
    except (TypeError, ValueError):
        seconds = 0.0
    per_second = recording_bytes_per_second(quality, include_final)
    return int(seconds * per_second * SAFETY_MARGIN)


def minutes_of_space(
    free_bytes: int,
    quality: object = DEFAULT_QUALITY,
    include_final: bool = True,
) -> float:
    """How many minutes of recording fit in `free_bytes` (with the margin)."""
    per_minute = recording_bytes_per_second(quality, include_final) * 60 * SAFETY_MARGIN
    if per_minute <= 0:
        return 0.0
    return max(0.0, free_bytes) / per_minute


def format_bytes(count: float) -> str:
    """Text like 512 MB or 4.6 GB for messages (binary units, as macOS shows)."""
    try:
        count = float(count)
    except (TypeError, ValueError):
        return "unknown"
    if count >= GIB:
        return f"{count / GIB:.1f} GB"
    return f"{max(0, round(count / MIB))} MB"


def format_elapsed(seconds: float) -> str:
    """Text like 7:05 or 1:02:03 for a clock showing how long a recording runs."""
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        total = 0
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def free_bytes(folder: Path) -> Optional[int]:
    """Free disk space where `folder` is (or would be); None if unreadable."""
    try:
        path = Path(folder).expanduser()
        # The folder may not exist yet: ask about the nearest one that does.
        while not path.exists() and path != path.parent:
            path = path.parent
        return shutil.disk_usage(path).free
    except Exception:
        return None


@dataclass(frozen=True)
class SpaceCheck:
    """Whether a planned recording fits on the disk."""

    free: Optional[int]  # None when the free space could not be read
    needed: int
    minutes_fit: Optional[float]

    @property
    def enough(self) -> bool:
        """True when it fits, or when the free space is unknown."""
        return self.free is None or self.free >= self.needed

    def message(self) -> str:
        """A sentence for the user; empty when there is enough space."""
        if self.enough or self.free is None:
            return ""
        fit = int(self.minutes_fit or 0)
        return (
            f"Only {format_bytes(self.free)} of disk space is free, and a "
            f"recording of this length needs about {format_bytes(self.needed)}. "
            f"About {fit} minute{'s' if fit != 1 else ''} will fit. Free up "
            "some space, or choose another folder in Settings."
        )


def check_space(
    folder: Path,
    minutes: float = DEFAULT_PLANNED_MINUTES,
    quality: object = DEFAULT_QUALITY,
) -> SpaceCheck:
    """Check whether `minutes` of recording fit where `folder` is. Never raises."""
    needed = estimate_recording_bytes(minutes, quality)
    free = free_bytes(folder)
    fit = minutes_of_space(free, quality) if free is not None else None
    return SpaceCheck(free=free, needed=needed, minutes_fit=fit)


# ---- keep the Mac awake --------------------------------------------------

CAFFEINATE = "/usr/bin/caffeinate"


class KeepAwake:
    """Stops the Mac from sleeping while it is started.

    Runs `caffeinate -d -i -m -s -w <this process>`: the display and the
    system stay awake (a sleeping display records black frames, a sleeping
    system stops the captures), and `-w` makes caffeinate quit by itself when
    this app ends, even if it crashes. `start()` returns False instead of
    raising when caffeinate is not there (for example on another system).
    """

    def __init__(
        self,
        command: Optional[Sequence[str]] = None,
        popen: Callable[..., "subprocess.Popen"] = subprocess.Popen,
    ) -> None:
        self._command = list(command) if command is not None else None
        self._popen = popen
        self._proc: Optional["subprocess.Popen"] = None
        self._lock = threading.Lock()

    def _build_command(self) -> Optional[List[str]]:
        if self._command is not None:
            return list(self._command)
        path = shutil.which("caffeinate") or (
            CAFFEINATE if os.path.exists(CAFFEINATE) else None
        )
        if path is None:
            return None
        return [path, "-d", "-i", "-m", "-s", "-w", str(os.getpid())]

    @property
    def active(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        """Keep the Mac awake. True if it is (now) being kept awake."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return True
            try:
                command = self._build_command()
                if command is None:
                    return False
                self._proc = self._popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                self._proc = None
                return False

    def stop(self) -> None:
        """Let the Mac sleep again. Safe to call any number of times."""
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                    proc.wait(timeout=2)
        except Exception:
            pass

    def __enter__(self) -> "KeepAwake":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


# ---- watching the captures -----------------------------------------------

class ProblemKind(Enum):
    PROCESS_EXITED = "process_exited"    # ffmpeg quit while recording
    FILE_STALLED = "file_stalled"        # the raw file stopped growing
    LOW_DISK_SPACE = "low_disk_space"    # warning: space is running low
    DISK_NEARLY_FULL = "disk_nearly_full"  # too little left to carry on


@dataclass(frozen=True)
class Problem:
    """Something the monitor noticed, in plain words."""

    kind: ProblemKind
    message: str
    fatal: bool           # True: stop the recording cleanly now
    # "camera", "screen", "mic" or "system" where it applies
    source: Optional[str] = None


@dataclass(frozen=True)
class Watch:
    """One capture to keep an eye on."""

    name: str                          # "camera", "screen", "mic" or "system"
    path: Path                         # the raw file being written
    is_running: Callable[[], bool]     # is the ffmpeg process still alive?
    # Optional: explains why the process quit, from its log (plain words).
    explain_exit: Optional[Callable[[], str]] = None


DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_STALL_SECONDS = 30.0
DEFAULT_WARN_FREE_BYTES = 2 * GIB
DEFAULT_CRITICAL_FREE_BYTES = 300 * MIB


def _file_size(path: Path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


class CaptureMonitor:
    """Checks every few seconds that the captures are still healthy.

    Each problem is reported once, through `on_problem(problem)`, which runs
    on the monitor's own thread (UI code must hand it over to its own
    thread). After a `fatal` problem the caller should stop the recording
    cleanly; the monitor keeps running, without repeating itself, until
    `stop()` is called. Stop the monitor *before* stopping the captures, so
    that ffmpeg exiting on request is not mistaken for a failure.

    Every stream is watched on its own (camera, screen, mic and system), so
    a failure in any one of them is reported by name, and the caller then
    stops all four captures cleanly.

    The file-growth check is deliberately slow (`stall_seconds`): audio is
    written continuously, so a file that has not grown for that long means
    the capture is really stuck, not just looking at a still screen.
    """

    def __init__(
        self,
        watches: Sequence[Watch],
        on_problem: Callable[[Problem], None],
        disk_folder: Optional[Path] = None,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        stall_seconds: float = DEFAULT_STALL_SECONDS,
        warn_free_bytes: int = DEFAULT_WARN_FREE_BYTES,
        critical_free_bytes: int = DEFAULT_CRITICAL_FREE_BYTES,
        clock: Callable[[], float] = time.monotonic,
        free_space: Callable[[Path], Optional[int]] = free_bytes,
    ) -> None:
        self._watches = list(watches)
        self._on_problem = on_problem
        if disk_folder is not None:
            self._disk_folder: Optional[Path] = Path(disk_folder)
        elif self._watches:
            self._disk_folder = Path(self._watches[0].path).parent
        else:
            self._disk_folder = None
        self._interval = max(0.05, float(interval))
        self._stall_seconds = float(stall_seconds)
        self._warn_free = int(warn_free_bytes)
        self._critical_free = int(critical_free_bytes)
        self._clock = clock
        self._free_space = free_space

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._reported: Set[Tuple[ProblemKind, Optional[str]]] = set()
        self._problems: List[Problem] = []
        # name -> (last size seen, when it last grew)
        self._growth: dict = {}
        self._begun_at: Optional[float] = None

    # ---- results ------------------------------------------------------

    @property
    def problems(self) -> List[Problem]:
        """Every problem reported so far, oldest first."""
        with self._lock:
            return list(self._problems)

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # ---- the thread ---------------------------------------------------

    def start(self) -> None:
        """Begin watching on a background thread. Safe to call twice."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._begun_at = self._clock()
            self._growth = {
                watch.name: (_file_size(watch.path), self._begun_at)
                for watch in self._watches
            }
            self._thread = threading.Thread(
                target=self._run, name="capture-monitor", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop watching. Safe to call any number of times, from anywhere."""
        self._stop_event.set()
        thread = self._thread
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.is_alive()
        ):
            thread.join(timeout)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            self.check_once()

    # ---- one round of checks -----------------------------------------

    def check_once(self) -> List[Problem]:
        """Run every check once; returns the problems that are new.

        Called by the monitor thread, and directly by tests. Never raises.
        """
        found: List[Problem] = []
        try:
            now = self._clock()
            if self._begun_at is None:
                self._begun_at = now
            for watch in self._watches:
                found.extend(self._check_watch(watch, now))
            found.extend(self._check_disk())
        except Exception:
            return []

        reported: List[Problem] = []
        for problem in found:
            if self._stop_event.is_set():
                # The recording is being stopped on purpose: nothing to report.
                break
            key = (problem.kind, problem.source)
            with self._lock:
                if key in self._reported:
                    continue
                self._reported.add(key)
                self._problems.append(problem)
            reported.append(problem)
            try:
                self._on_problem(problem)
            except Exception:
                # A broken callback must never break the monitor.
                pass
        return reported

    def _check_watch(self, watch: Watch, now: float) -> List[Problem]:
        problems: List[Problem] = []

        try:
            alive = bool(watch.is_running())
        except Exception:
            alive = True  # cannot tell: do not raise a false alarm
        if not alive:
            problems.append(self._exited_problem(watch))
            return problems  # a stopped process has no file growth to judge

        size = _file_size(watch.path)
        last_size, last_change = self._growth.get(watch.name, (size, now))
        if size > last_size:
            self._growth[watch.name] = (size, now)
        else:
            self._growth.setdefault(watch.name, (last_size, last_change))
            quiet_for = now - last_change
            if quiet_for >= self._stall_seconds:
                problems.append(self._stalled_problem(watch, size, quiet_for))
        return problems

    def _exited_problem(self, watch: Watch) -> Problem:
        detail = ""
        if watch.explain_exit is not None:
            try:
                detail = (watch.explain_exit() or "").strip()
            except Exception:
                detail = ""
        message = f"The {watch.name} recording stopped unexpectedly."
        if detail:
            message += f" {detail}"
        message += " What was recorded up to that point is kept."
        return Problem(ProblemKind.PROCESS_EXITED, message, True, watch.name)

    def _stalled_problem(self, watch: Watch, size: int, quiet_for: float) -> Problem:
        seconds = int(quiet_for)
        if size == 0:
            message = (
                f"The {watch.name} file has not been written for {seconds} "
                f"seconds, so the {watch.name} recording appears to be stuck."
            )
        else:
            message = (
                f"The {watch.name} file has not grown for {seconds} seconds, "
                f"so the {watch.name} recording appears to be stuck."
            )
        message += " What was recorded up to that point is kept."
        return Problem(ProblemKind.FILE_STALLED, message, True, watch.name)

    def _check_disk(self) -> List[Problem]:
        if self._disk_folder is None:
            return []
        try:
            free = self._free_space(self._disk_folder)
        except Exception:
            free = None
        if free is None:
            return []  # unreadable: never stop a recording because of it

        if free < self._critical_free:
            return [
                Problem(
                    ProblemKind.DISK_NEARLY_FULL,
                    "The recording was stopped because the disk is almost full "
                    f"({format_bytes(free)} left). What was recorded up to now "
                    "is kept. Free up some space (empty the Trash or delete "
                    "files you no longer need) before recording again.",
                    True,
                )
            ]
        if free < self._warn_free:
            return [
                Problem(
                    ProblemKind.LOW_DISK_SPACE,
                    f"Disk space is running low: only {format_bytes(free)} is "
                    "free where the recording is being saved. The recording "
                    f"stops by itself when less than "
                    f"{format_bytes(self._critical_free)} is left, and what "
                    "was recorded up to then is kept.",
                    False,
                )
            ]
        return []