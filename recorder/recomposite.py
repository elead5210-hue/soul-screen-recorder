"""Re-composite an existing session folder into a new final video.

Usage:
    python3 -m recorder.recomposite recordings/2026-10-21_14-46
    python3 -m recorder.recomposite recordings/2026-10-21_14-46 --pip-width 480 --margin 30
    python3 -m recorder.recomposite recordings/2026-10-21_14-46 --output final_large_pip.mp4
    python3 -m recorder.recomposite recordings/2026-10-21_14-46 --camera-offset 0.35
    python3 -m recorder.recomposite recordings/2026-10-21_14-46 --mic-offset -0.12 --system-offset 0.05
    python3 -m recorder.recomposite recordings/2026-10-21_14-46 --pip-position top-left --quality high

When --pip-width, --pip-position or --quality are omitted, the values saved in
the app's Settings are used.

--camera-offset, --mic-offset and --system-offset (seconds) fine-align each
stream against the screen, which is the reference and is never shifted:
positive delays that stream, negative makes it earlier. --camera-offset
shifts the camera video, --mic-offset the microphone and --system-offset the
system audio. Each given offset is saved to the session's sync.json once the
new video is made; an offset that is omitted uses the value already saved
there (0 if none).

The four raw files camera.mp4, screen.mp4, mic.wav and system.wav are read;
they are never modified. The new video has the screen with the camera
overlay and two separate audio tracks (microphone and system audio). By
default the result replaces final.mp4 in the same folder. Use --output to
write a different file instead and keep the existing final.mp4.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from recorder.app_settings import QUALITY_PRESETS, load_app_settings
from recorder.compositor import (
    DEFAULT_PIP_MARGIN,
    PIP_POSITIONS,
    CompositeError,
    composite,
)
from recorder.session import (
    CAMERA_FILENAME,
    FINAL_FILENAME,
    MIC_FILENAME,
    SCREEN_FILENAME,
    SYNC_FILENAME,
    SYSTEM_FILENAME,
)
from recorder.sync import SyncError, load_sync, set_stream_offset, validate_offset

# The raw recordings that are read and must never be overwritten.
RAW_FILENAMES = (CAMERA_FILENAME, SCREEN_FILENAME, MIC_FILENAME, SYSTEM_FILENAME)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m recorder.recomposite",
        description=(
            "Re-create the picture-in-picture video, with separate microphone "
            "and system-audio tracks, from a session's raw "
            f"{CAMERA_FILENAME}, {SCREEN_FILENAME}, {MIC_FILENAME} and "
            f"{SYSTEM_FILENAME}."
        ),
    )
    parser.add_argument(
        "session_folder",
        type=Path,
        help="a session folder such as recordings/2026-10-21_14-46",
    )
    parser.add_argument(
        "--pip-width",
        type=int,
        default=None,
        help="width of the presenter overlay in pixels (default: the saved Settings value)",
    )
    parser.add_argument(
        "--margin",
        type=int,
        default=DEFAULT_PIP_MARGIN,
        help=f"distance from the chosen corner in pixels (default {DEFAULT_PIP_MARGIN})",
    )
    parser.add_argument(
        "--pip-position",
        choices=PIP_POSITIONS,
        default=None,
        help="corner for the presenter overlay (default: the saved Settings value)",
    )
    parser.add_argument(
        "--quality",
        choices=QUALITY_PRESETS,
        default=None,
        help="video quality preset (default: the saved Settings value)",
    )
    parser.add_argument(
        "--camera-offset",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "fine-align the camera video against the screen: positive delays "
            "it, negative makes it earlier. Saved to sync.json; "
            "when omitted, the offset saved there is used (default 0)"
        ),
    )
    parser.add_argument(
        "--mic-offset",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "fine-align the microphone against the screen: positive delays "
            "it, negative makes it earlier. Saved to sync.json; "
            "when omitted, the offset saved there is used (default 0)"
        ),
    )
    parser.add_argument(
        "--system-offset",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "fine-align the system audio against the screen: positive delays "
            "it, negative makes it earlier. Saved to sync.json; "
            "when omitted, the offset saved there is used (default 0)"
        ),
    )
    parser.add_argument(
        "--output",
        default=FINAL_FILENAME,
        help=(
            f"output file name inside the session folder (default {FINAL_FILENAME}, "
            "which replaces the existing final video)"
        ),
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    folder: Path = args.session_folder.expanduser()
    if not folder.is_dir():
        print(f"Error: session folder not found: {folder}", file=sys.stderr)
        return 1
    # Options left out use the saved Settings (defaults if none are saved).
    prefs = load_app_settings()
    pip_width = args.pip_width if args.pip_width is not None else prefs.pip_width
    pip_position = args.pip_position or prefs.pip_position
    quality = args.quality or prefs.quality
    if pip_width < 2:
        print("Error: --pip-width must be at least 2.", file=sys.stderr)
        return 1
    if args.margin < 0:
        print("Error: --margin cannot be negative.", file=sys.stderr)
        return 1

    # Keep the output inside the session folder and never overwrite a raw file.
    output_name = Path(args.output).name
    if output_name in RAW_FILENAMES:
        print(
            f"Error: refusing to overwrite a raw recording ({output_name}).",
            file=sys.stderr,
        )
        return 1
    if not output_name.lower().endswith(".mp4"):
        print("Error: --output must be an .mp4 file name.", file=sys.stderr)
        return 1

    sync_path = folder / SYNC_FILENAME
    # Falls back to 0 if sync.json is missing or damaged. An offset that is
    # left out keeps the value saved there.
    saved = load_sync(sync_path)
    given = {
        "camera": args.camera_offset,
        "mic": args.mic_offset,
        "system": args.system_offset,
    }
    offsets = {
        "camera": saved.camera_offset_seconds,
        "mic": saved.mic_offset_seconds,
        "system": saved.system_offset_seconds,
    }
    for stream, value in given.items():
        if value is None:
            continue
        try:
            offsets[stream] = validate_offset(value, stream)
        except SyncError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    print(f"Compositing {folder} ...")
    for stream in ("camera", "mic", "system"):
        if offsets[stream]:
            print(f"{stream.capitalize()} offset: {offsets[stream]:+g} s")
    try:
        result = composite(
            folder / SCREEN_FILENAME,
            folder / CAMERA_FILENAME,
            folder / MIC_FILENAME,
            folder / SYSTEM_FILENAME,
            folder / output_name,
            pip_width=pip_width,
            margin=args.margin,
            camera_offset=offsets["camera"],
            mic_offset=offsets["mic"],
            system_offset=offsets["system"],
            pip_position=pip_position,
            quality=quality,
        )
    except CompositeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Saved {result}")

    # Remember explicitly given offsets only after they produced a video.
    for stream, value in given.items():
        if value is None:
            continue
        try:
            set_stream_offset(sync_path, stream, offsets[stream])
        except SyncError as exc:
            print(
                f"Warning: the video was made, but the {stream} offset was "
                f"not saved: {exc}",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())