"""Detect where the Mac is currently sending sound.

System audio is recorded from BlackHole 2ch. For the recording to contain
sound AND for the user to still hear it, macOS must be sending audio to a
Multi-Output Device that includes both the normal speakers/headphones and
BlackHole 2ch. This module reads the current default output device from
`system_profiler SPAudioDataType -json` and classifies it:

    MULTI_OUTPUT   a Multi-Output (aggregate) device: heard and captured
    BLACKHOLE_ONLY BlackHole by itself: captured, but silent for the user
    PLAIN_OUTPUT   speakers, headphones, etc.: heard, but NOT captured
    UNKNOWN        the output could not be determined (do not block)

Detection is best effort. Any failure (system_profiler missing, a timeout,
unexpected output) results in UNKNOWN, never an exception, so a problem here
can never stop a recording on its own.
"""

import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator, Optional

SYSTEM_PROFILER = "/usr/sbin/system_profiler"
_TIMEOUT_SECONDS = 10

_DEFAULT_OUTPUT_KEY = "coreaudio_default_audio_output_device"
_TRANSPORT_KEY = "coreaudio_device_transport"
_YES_VALUES = ("spaudio_yes", "yes", "true", "1")


class OutputKind(Enum):
    MULTI_OUTPUT = "multi_output"
    BLACKHOLE_ONLY = "blackhole_only"
    PLAIN_OUTPUT = "plain_output"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OutputInfo:
    kind: OutputKind
    name: Optional[str] = None  # name of the default output device, if known


def _iter_devices(node: Any) -> Iterator[dict]:
    """Yield every dict in the profiler output that looks like a device."""
    if isinstance(node, dict):
        if "_name" in node:
            yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _iter_devices(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_devices(item)


def _is_default_output(device: dict) -> bool:
    value = device.get(_DEFAULT_OUTPUT_KEY)
    return isinstance(value, str) and value.strip().lower() in _YES_VALUES


def classify_device(name: str, transport: Optional[str] = None) -> OutputKind:
    """Classify an output device from its name and transport type."""
    lowered = name.lower()
    transport_lowered = (transport or "").lower()

    if "blackhole" in lowered:
        return OutputKind.BLACKHOLE_ONLY
    if (
        "aggregate" in transport_lowered
        or "multi-output" in lowered
        or "multi output" in lowered
        or "multioutput" in lowered
    ):
        return OutputKind.MULTI_OUTPUT
    return OutputKind.PLAIN_OUTPUT


def parse_default_output(profiler_json: str) -> OutputInfo:
    """Find the default output device in `system_profiler -json` output."""
    try:
        data = json.loads(profiler_json)
    except (ValueError, TypeError):
        return OutputInfo(OutputKind.UNKNOWN)

    for device in _iter_devices(data):
        if not _is_default_output(device):
            continue
        name = str(device.get("_name", "")).strip()
        if not name:
            continue
        transport = device.get(_TRANSPORT_KEY)
        transport_text = transport if isinstance(transport, str) else None
        return OutputInfo(classify_device(name, transport_text), name)

    return OutputInfo(OutputKind.UNKNOWN)


def detect_default_output() -> OutputInfo:
    """Return the current default sound output, or UNKNOWN if not detectable."""
    try:
        result = subprocess.run(
            [SYSTEM_PROFILER, "SPAudioDataType", "-json"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return OutputInfo(OutputKind.UNKNOWN)

    if result.returncode != 0:
        return OutputInfo(OutputKind.UNKNOWN)

    text = result.stdout.decode("utf-8", errors="replace")
    return parse_default_output(text)