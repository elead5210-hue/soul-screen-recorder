"""Run the four independent ffmpeg captures.

Stream 1 (presenter): face camera, video only   -> camera.mp4
Stream 2 (screen):    desktop, video only       -> screen.mp4
Stream 3 (mic):       microphone, audio only    -> mic.wav
Stream 4 (system):    BlackHole, audio only     -> system.wav

All four processes are launched back to back so they start within a
fraction of a second of each other. Each stream is its own ffmpeg process,
so a problem with one device is reported for that stream by name.

The audio is written as 48 kHz 16-bit PCM WAV, flushed to disk as it is
recorded, so the sound captured so far is on disk even if the app or Mac
crashes (the WAV header lengths are finalized on a clean stop). They are stopped by writing "q" to ffmpeg's
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
from typing import IO, Dict, List, Optional

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

# Long-recording stability. Quiet logging (no progress line, warnings only)
# keeps the temporary stderr log small over a 30-minute session.
LOG_ARGS = ["-nostats", "-loglevel", "warning"]
# Larger avfoundation input thread queue plus wall-clock timestamps, so audio
# is not dropped when the machine is busy and the streams stay in sync.
INPUT_ARGS = ["-thread_queue_size", "1024", "-use_wallclock_as_timestamps", "1"]

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

# Audio-only captures: uncompressed 16-bit PCM WAV at one fixed sample rate.
# PCM has no encoder delay, which keeps the audio easy to align with video.
AUDIO_SAMPLE_RATE = 48000

# What each capture opens, used to name the problem in error messages.
_CAPTURE_KINDS = {
    "camera": "camera",
    "screen": "screen",
    "mic": "microphone",
    "system": "system audio device (BlackHole)",
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
    """Camera video only (no audio) -> camera.mp4."""
    name = quality.strip().lower() if isinstance(quality, str) else ""
    camera_bitrate = CAMERA_BITRATES.get(name, CAMERA_BITRATES[DEFAULT_QUALITY])
    return [
        ffmpeg, "-hide_banner", "-y", *LOG_ARGS,
        "-f", "avfoundation",
        *INPUT_ARGS,
        "-framerate", str(FRAMERATE),
        "-i", f"{devices.camera.index}:none",
        *video_encoder_args(ffmpeg, camera_bitrate, FRAMERATE * FRAGMENT_SECONDS),
        "-pix_fmt", "yuv420p",
        "-an",
        "-movflags", MOVFLAGS,
        str(output),
    ]


def build_screen_command(
    ffmpeg: str,
    devices: SelectedDevices,
    output: Path,
    quality: str = DEFAULT_QUALITY,
) -> List[str]:
    """Screen video only (no audio) -> screen.mp4."""
    return [
        ffmpeg, "-hide_banner", "-y", *LOG_ARGS,
        "-f", "avfoundation",
        *INPUT_ARGS,
        "-capture_cursor", "1",
        "-framerate", str(FRAMERATE),
        "-i", f"{devices.screen.index}:none",
        *video_encoder_args_for_quality(
            ffmpeg, quality, FRAMERATE * FRAGMENT_SECONDS
        ),
        "-pix_fmt", "yuv420p",
        "-an",
        "-movflags", MOVFLAGS,
        str(output),
    ]


def _build_audio_command(ffmpeg: str, device_index: int, output: Path) -> List[str]:
    """One audio device, no video -> a 48 kHz 16-bit PCM WAV file."""
    return [
        ffmpeg, "-hide_banner", "-y", *LOG_ARGS,
        "-f", "avfoundation",
        *INPUT_ARGS,
        "-i", f"none:{device_index}",
        "-vn",
        "-c:a", "pcm_s16le", "-ar", str(AUDIO_SAMPLE_RATE),
        # Push every packet to disk as it is recorded, so a crash loses at
        # most a moment of sound. rf64 auto switches to the RF64 header on
        # its own for a file larger than 4 GB.
        "-flush_packets", "1",
        "-rf64", "auto",
        "-f", "wav",
        str(output),
    ]


def build_mic_command(
    ffmpeg: str,
    devices: SelectedDevices,
    output: Path,
) -> List[str]:
    """Microphone only -> mic.wav."""
    return _build_audio_command(ffmpeg, devices.microphone.index, output)


def build_system_audio_command(
    ffmpeg: str,
    devices: SelectedDevices,
    output: Path,
) -> List[str]:
    """System audio (BlackHole) only -> system.wav."""
    return _build_audio_command(ffmpeg, devices.system_audio.index, output)


def _is_playable(ffmpeg: str, path: Path, marker: str = "Video:") -> bool:
    """Quick check that ffmpeg can open the file and finds the expected stream.

    `marker` is the text ffmpeg prints for the stream type: "Video:" for the
    camera and screen files, "Audio:" for the microphone and system files.

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
    return marker in text


class MultiCapture:
    """Starts and stops the camera, screen, microphone and system-audio
    captures together, as four independent ffmpeg processes."""

    def __init__(
        self,
        devices: SelectedDevices,
        camera_path: Path,
        screen_path: Path,
        mic_path: Path,
        system_path: Path,
        ffmpeg_path: Optional[str] = None,
        quality: str = DEFAULT_QUALITY,
        record_camera: bool = True,
        record_screen: bool = True,
        record_mic: bool = True,
        record_system: bool = True,
    ) -> None:
        # Deselected streams are never opened or recorded.
        self._enabled = tuple(
            name
            for name, wanted in (
                ("camera", record_camera),
                ("screen", record_screen),
                ("mic", record_mic),
                ("system", record_system),
            )
            if wanted
        )
        if not self._enabled:
            raise CaptureError(
                "All channels are deselected, so there is nothing to record. "
                "Turn on at least one channel in the settings."
            )
        ffmpeg = ffmpeg_path or find_ffmpeg()
        self._ffmpeg = ffmpeg
        self.camera_path = camera_path
        self.screen_path = screen_path
        self.mic_path = mic_path
        self.system_path = system_path
        self._camera: Optional[_FfmpegProcess] = None
        self._screen: Optional[_FfmpegProcess] = None
        self._mic: Optional[_FfmpegProcess] = None
        self._system: Optional[_FfmpegProcess] = None
        if "camera" in self._enabled:
            self._camera = _FfmpegProcess(
                "camera",
                build_camera_command(ffmpeg, devices, camera_path, quality),
            )
        if "screen" in self._enabled:
            self._screen = _FfmpegProcess(
                "screen",
                build_screen_command(ffmpeg, devices, screen_path, quality),
            )
        if "mic" in self._enabled:
            self._mic = _FfmpegProcess(
                "mic", build_mic_command(ffmpeg, devices, mic_path)
            )
        if "system" in self._enabled:
            self._system = _FfmpegProcess(
                "system",
                build_system_audio_command(ffmpeg, devices, system_path),
            )
        self._started = False
        self._launch_gap_seconds: Optional[float] = None
        self._launch_offsets: Dict[str, float] = {}

    @property
    def launch_gap_seconds(self) -> Optional[float]:
        """Measured gap between the two ffmpeg launches, in seconds.

        Positive means the screen capture was launched after the camera
        capture (so the presenter started first); negative means the
        opposite. None until both processes have been launched.
        """
        return self._launch_gap_seconds

    @property
    def launch_offsets_seconds(self) -> Dict[str, float]:
        """When each stream was launched, in seconds after the first one.

        Keys are "camera", "screen", "mic" and "system"; the stream launched
        first has 0. Empty until the processes have been launched. Like
        launch_gap_seconds, this is a measurement of when ffmpeg was launched,
        not of when each device actually began delivering data.
        """
        return dict(self._launch_offsets)

    @property
    def _processes(self) -> List[_FfmpegProcess]:
        return [
            p
            for p in (self._camera, self._screen, self._mic, self._system)
            if p is not None
        ]

    @property
    def enabled_streams(self) -> tuple:
        """Names of the streams being captured (deselected ones are left out)."""
        return self._enabled

    def start(self) -> None:
        """Launch the selected captures back to back, then verify they are running."""
        if self._started:
            raise CaptureError("Capture is already running.")

        self._launch_gap_seconds = None
        self._launch_offsets = {}
        try:
            # All commands are fully built already. Launch back to back,
            # nothing in between, to keep the start times close; each launch
            # is timestamped with time.monotonic() around Popen.
            for p in self._processes:
                p.start()
        except (FileNotFoundError, OSError) as exc:
            self._abort()
            raise CaptureError(
                f"Could not launch ffmpeg. {friendly_message(exc)}"
            )

        cam_t = (
            self._camera.launch_returned_at if self._camera is not None else None
        )
        scr_t = (
            self._screen.launch_returned_at if self._screen is not None else None
        )
        if cam_t is not None and scr_t is not None:
            self._launch_gap_seconds = scr_t - cam_t

        launched = {
            p.name: p.launch_returned_at
            for p in self._processes
            if p.launch_returned_at is not None
        }
        if launched:
            first = min(launched.values())
            self._launch_offsets = {
                name: t - first for name, t in launched.items()
            }

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

    @property
    def raw_paths(self) -> List[Path]:
        """The raw files being written: camera, screen, mic and system."""
        paths = {
            "camera": self.camera_path,
            "screen": self.screen_path,
            "mic": self.mic_path,
            "system": self.system_path,
        }
        return [paths[name] for name in self._enabled]

    def is_running(self) -> bool:
        """True while capture has been started and all four ffmpeg processes are alive."""
        return self._started and all(p.is_running() for p in self._processes)

    def exit_problems(self) -> List[str]:
        """Friendly messages for any capture that exited while recording.

        Meant to be polled by a monitor during a long recording. Returns an
        empty list while everything is running normally (or not started).
        """
        if not self._started:
            return []
        problems: List[str] = []
        for p in self._processes:
            if p.proc is None or p.proc.poll() is None:
                continue
            log = p.error_tail(_LOG_CHARS_FOR_DIAGNOSIS)
            problems.append(
                friendly_ffmpeg_failure(
                    log,
                    _CAPTURE_KINDS.get(p.name),
                    f"The {p.name} capture stopped unexpectedly.",
                )
            )
        return problems

    def stop(self) -> None:
        """Stop all four captures and wait for the files to be finalized."""
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

        for path, label, marker in [
            item
            for item in (
                (self.camera_path, "camera", "Video:"),
                (self.screen_path, "screen", "Video:"),
                (self.mic_path, "mic", "Audio:"),
                (self.system_path, "system", "Audio:"),
            )
            if item[1] in self._enabled
        ]:
            if not path.exists() or path.stat().st_size == 0:
                problems.append(f"The {label} file was not written: {path.name}")
            elif not _is_playable(self._ffmpeg, path, marker):
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


# The old two-stream name, kept so existing imports still resolve until the
# controller is updated to pass the microphone and system-audio paths.
DualCapture = MultiCapture