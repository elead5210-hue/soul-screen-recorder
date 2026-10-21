"""Run the two independent ffmpeg captures.

Stream A (presenter): camera + microphone  -> camera.mp4
Stream B (screen):    screen + BlackHole   -> screen.mp4

Both processes are launched back to back so they start within a fraction
of a second of each other. They are stopped by writing "q" to ffmpeg's
stdin, which lets ffmpeg flush and finalize the MP4.

The files are written as fragmented MP4 (a playable fragment about every
two seconds), so even if ffmpeg is force-closed or the app or Mac crashes
mid-recording, everything recorded so far stays playable instead of the
file ending up without its index and unplayable. After stopping, each
file is checked to confirm it can be opened before success is reported.
"""

import subprocess
import tempfile
import time
from pathlib import Path
from typing import IO, List, Optional

from recorder.devices import SelectedDevices, find_ffmpeg
from recorder.encoding import (
    DEFAULT_QUALITY,
    video_encoder_args,
    video_encoder_args_for_quality,
)
from recorder.errors import friendly_ffmpeg_failure, friendly_message

# How long to wait for ffmpeg to finalize a file after we send "q".
STOP_TIMEOUT_SECONDS = 20
# How long to wait after launch to confirm ffmpeg did not exit immediately.
STARTUP_CHECK_SECONDS = 1.5

FRAMERATE = 30

# Camera bitrate for each quality preset: half the screen bitrate (the screen
# uses the preset's own bitrate from recorder.encoding), because the presenter
# video is small and has less detail.
CAMERA_BITRATES = {
    "low": "2M",
    "medium": "4M",
    "high": "8M",
}

# Fragmented MP4: a new fragment (and keyframe) every couple of seconds.
FRAGMENT_SECONDS = 2
MOVFLAGS = "+frag_keyframe+empty_moov+default_base_moof"

# What each capture opens, used to name the problem in error messages.
_CAPTURE_KINDS = {
    "camera": "camera or microphone",
    "screen": "screen or system audio device",
}
# How much of ffmpeg's log is read to recognise a problem (the user is shown
# only the friendly explanation plus the last few lines).
_LOG_CHARS_FOR_DIAGNOSIS = 4000


class CaptureError(Exception):
    """Raised when a capture cannot start or does not finish cleanly."""


class _FfmpegProcess:
    """One ffmpeg subprocess plus its captured stderr log."""

    def __init__(self, name: str, cmd: List[str]) -> None:
        self.name = name
        self.cmd = cmd
        self._log: IO[bytes] = tempfile.TemporaryFile()
        self.proc: Optional[subprocess.Popen] = None
        # time.monotonic() just before and just after Popen returned.
        self.launch_started_at: Optional[float] = None
        self.launch_returned_at: Optional[float] = None

    def start(self) -> None:
        self.launch_started_at = time.monotonic()
        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self._log,
        )
        self.launch_returned_at = time.monotonic()

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def request_stop(self) -> None:
        """Ask ffmpeg to finish by sending 'q' on stdin."""
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            assert self.proc.stdin is not None
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def wait(self, timeout: float) -> bool:
        """Wait for exit. Returns False if ffmpeg had to be force-killed."""
        if self.proc is None:
            return True
        clean = True
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            clean = False
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        finally:
            if self.proc.stdin is not None:
                try:
                    self.proc.stdin.close()
                except OSError:
                    pass
        return clean

    def error_tail(self, max_chars: int = 600) -> str:
        """Last part of ffmpeg's stderr, for error messages."""
        try:
            self._log.flush()
            self._log.seek(0)
            text = self._log.read().decode("utf-8", errors="replace").strip()
        except (OSError, ValueError):
            return ""
        return text[-max_chars:]

    def close_log(self) -> None:
        try:
            self._log.close()
        except OSError:
            pass


def build_camera_command(
    ffmpeg: str,
    devices: SelectedDevices,
    output: Path,
    quality: str = DEFAULT_QUALITY,
) -> List[str]:
    """Camera video + microphone audio -> camera.mp4."""
    name = quality.strip().lower() if isinstance(quality, str) else ""
    camera_bitrate = CAMERA_BITRATES.get(name, CAMERA_BITRATES[DEFAULT_QUALITY])
    return [
        ffmpeg, "-hide_banner", "-y",
        "-f", "avfoundation",
        "-framerate", str(FRAMERATE),
        "-i", f"{devices.camera.index}:{devices.microphone.index}",
        *video_encoder_args(ffmpeg, camera_bitrate, FRAMERATE * FRAGMENT_SECONDS),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", MOVFLAGS,
        str(output),
    ]


def build_screen_command(
    ffmpeg: str,
    devices: SelectedDevices,
    output: Path,
    quality: str = DEFAULT_QUALITY,
) -> List[str]:
    """Screen video + system audio (BlackHole) -> screen.mp4."""
    return [
        ffmpeg, "-hide_banner", "-y",
        "-f", "avfoundation",
        "-capture_cursor", "1",
        "-framerate", str(FRAMERATE),
        "-i", f"{devices.screen.index}:{devices.system_audio.index}",
        *video_encoder_args_for_quality(
            ffmpeg, quality, FRAMERATE * FRAGMENT_SECONDS
        ),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", MOVFLAGS,
        str(output),
    ]


def _is_playable(ffmpeg: str, path: Path) -> bool:
    """Quick check that ffmpeg can open the file and finds a video stream.

    This only reads the file's headers, so it is fast even for long
    recordings. If the check itself cannot run, the file is given the
    benefit of the doubt.
    """
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    text = result.stderr.decode("utf-8", errors="replace")
    if "moov atom not found" in text or "Invalid data found" in text:
        return False
    return "Video:" in text


class DualCapture:
    """Starts and stops the camera and screen captures together."""

    def __init__(
        self,
        devices: SelectedDevices,
        camera_path: Path,
        screen_path: Path,
        ffmpeg_path: Optional[str] = None,
        quality: str = DEFAULT_QUALITY,
    ) -> None:
        ffmpeg = ffmpeg_path or find_ffmpeg()
        self._ffmpeg = ffmpeg
        self.camera_path = camera_path
        self.screen_path = screen_path
        self._camera = _FfmpegProcess(
            "camera", build_camera_command(ffmpeg, devices, camera_path, quality)
        )
        self._screen = _FfmpegProcess(
            "screen", build_screen_command(ffmpeg, devices, screen_path, quality)
        )
        self._started = False
        self._launch_gap_seconds: Optional[float] = None

    @property
    def launch_gap_seconds(self) -> Optional[float]:
        """Measured gap between the two ffmpeg launches, in seconds.

        Positive means the screen capture was launched after the camera
        capture (so the presenter started first); negative means the
        opposite. None until both processes have been launched.
        """
        return self._launch_gap_seconds

    @property
    def _processes(self) -> List[_FfmpegProcess]:
        return [self._camera, self._screen]

    def start(self) -> None:
        """Launch both captures back to back, then verify they are running."""
        if self._started:
            raise CaptureError("Capture is already running.")

        self._launch_gap_seconds = None
        try:
            # Both commands are fully built already. Launch back to back,
            # nothing in between, to keep the start times close; each launch
            # is timestamped with time.monotonic() around Popen.
            self._camera.start()
            self._screen.start()
        except (FileNotFoundError, OSError) as exc:
            self._abort()
            raise CaptureError(
                f"Could not launch ffmpeg. {friendly_message(exc)}"
            )

        cam_t = self._camera.launch_returned_at
        scr_t = self._screen.launch_returned_at
        if cam_t is not None and scr_t is not None:
            self._launch_gap_seconds = scr_t - cam_t

        self._started = True

        # If a device is missing or a permission is denied, ffmpeg exits
        # almost immediately. Catch that now instead of at Stop time.
        time.sleep(STARTUP_CHECK_SECONDS)
        for p in self._processes:
            if not p.is_running():
                log = p.error_tail(_LOG_CHARS_FOR_DIAGNOSIS)
                self._abort()
                raise CaptureError(
                    friendly_ffmpeg_failure(
                        log,
                        _CAPTURE_KINDS.get(p.name),
                        f"The {p.name} capture failed to start.",
                    )
                )

    def stop(self) -> None:
        """Stop both captures and wait for the files to be finalized."""
        if not self._started:
            return

        # Send 'q' to both first so they finish at nearly the same time,
        # then wait on each.
        for p in self._processes:
            p.request_stop()

        problems: List[str] = []
        forced: List[str] = []
        for p in self._processes:
            clean = p.wait(STOP_TIMEOUT_SECONDS)
            if not clean:
                # Reported below only if the file turns out to be unplayable.
                forced.append(p.name)
            elif p.proc is not None and p.proc.returncode not in (0, 255):
                log = p.error_tail(_LOG_CHARS_FOR_DIAGNOSIS)
                problems.append(
                    friendly_ffmpeg_failure(
                        log,
                        _CAPTURE_KINDS.get(p.name),
                        f"The {p.name} capture ended with an error.",
                    )
                )

        self._started = False

        for p in self._processes:
            p.close_log()

        for path, label in ((self.camera_path, "camera"),
                            (self.screen_path, "screen")):
            if not path.exists() or path.stat().st_size == 0:
                problems.append(f"The {label} file was not written: {path.name}")
            elif not _is_playable(self._ffmpeg, path):
                note = (
                    " The capture did not stop in time and was force-closed."
                    if label in forced
                    else ""
                )
                problems.append(
                    f"The {label} file could not be opened and may be "
                    f"unplayable: {path.name}.{note}"
                )

        if problems:
            raise CaptureError("\n".join(problems))

    def _abort(self) -> None:
        """Tear down anything that is running after a failed start."""
        for p in self._processes:
            p.request_stop()
        for p in self._processes:
            p.wait(5)
            p.close_log()
        self._started = False