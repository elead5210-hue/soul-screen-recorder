#!/usr/bin/env python3
"""soul-screen-recorder: entry point.

Creates the controller and the main window, then starts the Tkinter
main loop. Run with:  python3 main.py
"""

import sys

from recorder.controller import RecorderController
from ui.main_window import MainWindow


def main() -> int:
    controller = RecorderController()
    window = MainWindow(controller)
    window.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())