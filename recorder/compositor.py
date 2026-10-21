"""Combine camera.mp4 and screen.mp4 into final.mp4 (picture-in-picture).

Layout: the screen recording is the main video and the presenter camera is
scaled to a small overlay in the bottom-right corner. The final audio is a
mix of both inputs: the presenter's microphone (camera.mp4) and the system
audio (screen.mp4).

The raw camera.mp4 and screen.mp4 are never modified, so a session can
always be re-composited later. The output is written to a temporary file
and renamed only when ffmpeg succeeds, so a failed or interrupted run
never leaves a corrupt final.mp4 behind.
"""

import subprocess
from pathlib import Path
from typing import List, Optional

from recorder.devices import find_ffmpeg
from recorder.encoding import video_encoder_args
from recorder.errors import (
    DISK_FULL_MESSAGE,
    FFMPEG_NOT_FOUND_MESSAGE,
    FOLDER_NOT_WRITABLE_MESSAGE,
    explain_ffmpeg_output,
    friendly_message,
    last_log_lines,
)

# Default picture-in-picture layout.
DEFAULT_PIP_WIDTH = 320
DEFAULT_PIP_MARGIN = 20

VIDEO_BITRATE = "8M"
# Keyframe interval in frames (about 2 seconds at 30 fps).
VIDEO_GOP = 60
AUDIO_BITRATE = "192k"

# Compositing re-encodes the whole recording, so allow plenty of time.
COMPOSITE_TIMEOUT_SECONDS = 60 * 60


class CompositeError(Exception):
    """Raised when final.mp4 cannot be produced."""


def _has_audio(ffmpeg: str, path: Path) -> bool:
    """Return True if the file contains at least one audio stream."""
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    # `ffmpeg -i` with no output exits non-zero but lists the streams.
    text = result.stderr.decode("utf-8", errors="replace")
    return "Audio:" in text


def build_filter_graph(
    pip_width: int,
    margin: int,
    screen_has_audio: bool,
    camera_has_audio: bool,
    camera_offset: float = 0.0,
) -> "tuple[str, Optional[str]]":
    """Return (filter_complex, audio_label).

    Input 0 is screen.mp4 and input 1 is camera.mp4. audio_label is the
    mapped audio output label, or None when neither input has audio.

    camera_offset is in seconds and shifts both the camera video and the
    camera audio before overlay and mixing: positive delays the presenter,
    negative advances it (the start of the camera recording is trimmed).
    The default of 0 leaves the graph unchanged.
    """
    # Even width keeps yuv420p / the hardware encoder happy; -2 keeps the
    # camera's aspect ratio with an even height.
    width = max(2, int(pip_width) // 2 * 2)

    offset = float(camera_offset)
    video_shift = ""
    audio_shift = ""
    if offset > 0:
        video_shift = f"setpts=PTS+{offset:.3f}/TB,"
        audio_shift = f"adelay={int(round(offset * 1000))}:all=1"
    elif offset < 0:
        video_shift = f"trim=start={-offset:.3f},setpts=PTS-STARTPTS,"
        audio_shift = f"atrim=start={-offset:.3f},asetpts=PTS-STARTPTS"

    parts = [
        f"[1:v]{video_shift}scale={width}:-2[pip]",
        f"[0:v][pip]overlay=W-w-{int(margin)}:H-h-{int(margin)},"
        "format=yuv420p[v]",
    ]

    # The camera audio input to use: the raw stream, or the shifted copy.
    camera_audio_in = "[1:a]"
    if camera_has_audio and audio_shift:
        parts.append(f"[1:a]{audio_shift}[ca]")
        camera_audio_in = "[ca]"

    audio_label: Optional[str] = None
    if screen_has_audio and camera_has_audio:
        # amix lowers each input's level, so bring the mix back up and
        # use a limiter to avoid clipping when both sources are loud.
        parts.append(
            f"[0:a]{camera_audio_in}"
            "amix=inputs=2:duration=longest:dropout_transition=0,"
            "volume=2,alimiter=limit=0.95[a]"
        )
        audio_label = "[a]"
    elif screen_has_audio:
        audio_label = "0:a"
    elif camera_has_audio:
        audio_label = "1:a" if camera_audio_in == "[1:a]" else camera_audio_in

    return ";".join(parts), audio_label


def build_composite_command(
    ffmpeg: str,
    screen_path: Path,
    camera_path: Path,
    output: Path,
    pip_width: int = DEFAULT_PIP_WIDTH,
    margin: int = DEFAULT_PIP_MARGIN,
    screen_has_audio: bool = True,
    camera_has_audio: bool = True,
    camera_offset: float = 0.0,
) -> List[str]:
    """Build the ffmpeg command that writes the PiP video to `output`."""
    graph, audio_label = build_filter_graph(
        pip_width, margin, screen_has_audio, camera_has_audio, camera_offset
    )
    cmd = [
        ffmpeg, "-hide_banner", "-y",
        "-i", str(screen_path),
        "-i", str(camera_path),
        "-filter_complex", graph,
        "-map", "[v]",
    ]
    if audio_label is not None:
        cmd += ["-map", audio_label, "-c:a", "aac", "-b:a", AUDIO_BITRATE]
    cmd += [
        *video_encoder_args(ffmpeg, VIDEO_BITRATE, VIDEO_GOP),
        "-pix_fmt", "yuv420p",
        # Stop at the shortest stream so the mix never runs past the video.
        "-shortest",
        "-movflags", "+faststart",
        str(output),
    ]
    return cmd


def composite(
    screen_path: Path,
    camera_path: Path,
    final_path: Path,
    pip_width: int = DEFAULT_PIP_WIDTH,
    margin: int = DEFAULT_PIP_MARGIN,
    ffmpeg_path: Optional[str] = None,
    camera_offset: float = 0.0,
) -> Path:
    """Create final.mp4 from the two raw recordings and return its path.

    Raises CompositeError with a readable message on any failure.
    """
    screen_path = Path(screen_path)
    camera_path = Path(camera_path)
    final_path = Path(final_path)

    for path, label in ((screen_path, "screen"), (camera_path, "camera")):
        if not path.exists() or path.stat().st_size == 0:
            raise CompositeError(
                f"Cannot create the final video: the {label} file is "
                f"missing or empty ({path.name})."
            )

    try:
        ffmpeg = ffmpeg_path or find_ffmpeg()
    except Exception as exc:
        raise CompositeError(str(exc))

    cmd = build_composite_command(
        ffmpeg,
        screen_path,
        camera_path,
        # ffmpeg picks the container from the extension, so keep .mp4.
        final_path.with_name(final_path.stem + ".part" + final_path.suffix),
        pip_width=pip_width,
        margin=margin,
        screen_has_audio=_has_audio(ffmpeg, screen_path),
        camera_has_audio=_has_audio(ffmpeg, camera_path),
        camera_offset=camera_offset,
    )
    temp_path = Path(cmd[-1])

    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=COMPOSITE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _remove(temp_path)
        raise CompositeError(
            "Creating the final video took too long and was stopped. "
            "camera.mp4 and screen.mp4 are still saved."
        )
    except OSError as exc:
        _remove(temp_path)
        raise CompositeError(f"Could not launch ffmpeg. {friendly_message(exc)}")

    if result.returncode != 0:
        log = result.stderr.decode("utf-8", errors="replace").strip()
        _remove(temp_path)
        message = (
            "Could not create the final video. camera.mp4 and screen.mp4 "
            "are still saved."
        )
        # Only problems that are certain to apply to compositing are
        # explained; anything else shows the last lines of ffmpeg's log.
        explained = explain_ffmpeg_output(log)
        if explained is not None and explained.title in (
            DISK_FULL_MESSAGE,
            FOLDER_NOT_WRITABLE_MESSAGE,
            FFMPEG_NOT_FOUND_MESSAGE,
        ):
            message += "\n" + explained.text()
        else:
            tail = last_log_lines(log)
            if tail:
                message += "\n" + tail
        raise CompositeError(message)

    if not temp_path.exists() or temp_path.stat().st_size == 0:
        _remove(temp_path)
        raise CompositeError(
            "The final video was not written. camera.mp4 and screen.mp4 "
            "are still saved."
        )

    try:
        temp_path.replace(final_path)
    except OSError as exc:
        _remove(temp_path)
        raise CompositeError(
            f"Could not save {final_path.name}. {friendly_message(exc)} "
            "camera.mp4 and screen.mp4 are still saved."
        )

    return final_path


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass