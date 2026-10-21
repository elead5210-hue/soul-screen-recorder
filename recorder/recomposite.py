"""Re-composite an existing session folder into a new final video.

Usage:
    python3 -m recorder.recomposite recordings/2026-10-21_14-46
    python3 -m recorder.recomposite recordings/2026-10-21_14-46 --pip-width 480 --margin 30
    python3 -m recorder.recomposite recordings/2026-10-21_14-46 --output final_large_pip.mp4

Only camera.mp4 and screen.mp4 are read; they are never modified. By
default the result replaces final.mp4 in the same folder. Use --output to
write a different file instead and keep the existing final.mp4.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from recorder.compositor import (
    DEFAULT_PIP_MARGIN,
    DEFAULT_PIP_WIDTH,
    CompositeError,
    composite,
)
from recorder.session import CAMERA_FILENAME, FINAL_FILENAME, SCREEN_FILENAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m recorder.recomposite",
        description=(
            "Re-create the picture-in-picture video from a session's raw "
            f"{CAMERA_FILENAME} and {SCREEN_FILENAME}."
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
        default=DEFAULT_PIP_WIDTH,
        help=f"width of the presenter overlay in pixels (default {DEFAULT_PIP_WIDTH})",
    )
    parser.add_argument(
        "--margin",
        type=int,
        default=DEFAULT_PIP_MARGIN,
        help=f"distance from the bottom-right corner in pixels (default {DEFAULT_PIP_MARGIN})",
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
    if args.pip_width < 2:
        print("Error: --pip-width must be at least 2.", file=sys.stderr)
        return 1
    if args.margin < 0:
        print("Error: --margin cannot be negative.", file=sys.stderr)
        return 1

    # Keep the output inside the session folder and never overwrite a raw file.
    output_name = Path(args.output).name
    if output_name in (CAMERA_FILENAME, SCREEN_FILENAME):
        print(
            f"Error: refusing to overwrite a raw recording ({output_name}).",
            file=sys.stderr,
        )
        return 1
    if not output_name.lower().endswith(".mp4"):
        print("Error: --output must be an .mp4 file name.", file=sys.stderr)
        return 1

    print(f"Compositing {folder} ...")
    try:
        result = composite(
            folder / SCREEN_FILENAME,
            folder / CAMERA_FILENAME,
            folder / output_name,
            pip_width=args.pip_width,
            margin=args.margin,
        )
    except CompositeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Saved {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())