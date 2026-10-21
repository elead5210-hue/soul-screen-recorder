"""Choose the video encoder used for capture and compositing.

Recording two streams at once (and compositing afterwards) is only light on
the CPU when the video is encoded by the Mac's hardware encoder, which ffmpeg
exposes as `h264_videotoolbox`. This module checks once per ffmpeg binary
that the encoder exists and returns the matching ffmpeg arguments.

If the installed ffmpeg was built without VideoToolbox (some non-Homebrew
builds), the software encoder `libx264` with a fast preset is used instead,
so recording still works, just with higher CPU use. The check never raises:
if it cannot run, hardware encoding is assumed, because that is what the
standard Homebrew ffmpeg provides.
"""

import subprocess
from typing import Dict, List

HARDWARE_ENCODER = "h264_videotoolbox"
SOFTWARE_ENCODER = "libx264"

_TIMEOUT_SECONDS = 15

# Video quality presets and the bitrate each one uses. "medium" matches the
# bitrate the app used before quality became a setting. The names match
# recorder.app_settings.QUALITY_PRESETS.
QUALITY_BITRATES: Dict[str, str] = {
    "low": "3M",
    "medium": "8M",
    "high": "16M",
}
DEFAULT_QUALITY = "medium"

# Cache of ffmpeg path -> whether h264_videotoolbox is available.
_hardware_cache: Dict[str, bool] = {}


def encoders_list_contains(encoders_output: str, name: str) -> bool:
    """Return True if `ffmpeg -encoders` output lists the encoder `name`.

    Each encoder line looks like ` V....D h264_videotoolbox    VideoToolbox ...`,
    so the name is matched as the second whitespace-separated field.
    """
    for line in encoders_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False


def hardware_encoder_available(ffmpeg: str) -> bool:
    """Check (once per ffmpeg binary) whether h264_videotoolbox is available."""
    cached = _hardware_cache.get(ffmpeg)
    if cached is not None:
        return cached

    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Could not run the check: assume the standard hardware encoder.
        # A real problem with ffmpeg is reported by the capture itself.
        _hardware_cache[ffmpeg] = True
        return True

    text = result.stdout.decode("utf-8", errors="replace")
    available = encoders_list_contains(text, HARDWARE_ENCODER)
    _hardware_cache[ffmpeg] = available
    return available


def video_encoder_args(ffmpeg: str, bitrate: str, gop: int) -> List[str]:
    """Return the ffmpeg arguments that select and configure the encoder.

    `bitrate` is an ffmpeg bitrate such as "8M". `gop` is the keyframe
    interval in frames, which also sets the fragment length of the MP4 files.
    """
    if hardware_encoder_available(ffmpeg):
        return [
            "-c:v", HARDWARE_ENCODER,
            "-b:v", bitrate,
            "-g", str(gop),
        ]
    return [
        "-c:v", SOFTWARE_ENCODER,
        "-preset", "veryfast",
        "-b:v", bitrate,
        "-g", str(gop),
    ]


def quality_bitrate(quality: str) -> str:
    """Return the ffmpeg bitrate for a quality preset name.

    The name is matched case-insensitively; anything unknown falls back to
    the default (medium) preset so a bad value never stops a recording.
    """
    name = quality.strip().lower() if isinstance(quality, str) else ""
    return QUALITY_BITRATES.get(name, QUALITY_BITRATES[DEFAULT_QUALITY])


def video_encoder_args_for_quality(ffmpeg: str, quality: str, gop: int) -> List[str]:
    """Return the encoder arguments for a quality preset name.

    Same as video_encoder_args, but takes "low", "medium" or "high" instead
    of a raw bitrate.
    """
    return video_encoder_args(ffmpeg, quality_bitrate(quality), gop)


def describe_encoder(ffmpeg: str) -> str:
    """Human-readable name of the encoder that will be used."""
    if hardware_encoder_available(ffmpeg):
        return f"{HARDWARE_ENCODER} (hardware)"
    return f"{SOFTWARE_ENCODER} (software fallback, higher CPU use)"