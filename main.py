#!/usr/bin/env python3
"""soul-screen-recorder: entry point.

Creates the controller and the main window, then starts the Tkinter
main loop. Run with:  python3 main.py

Before the window opens, the platform is checked (see recorder.compat). If
macOS is older than the supported minimum, or Tk is too old to draw the
window (such as Tk 8.5 from the Python that ships with macOS), a warning
dialog explains the problem and how to fix it, and the user can quit or open
the app anyway. A newer-than-tested macOS, Python running under Rosetta, or a
version that cannot be determined never shows a dialog.
"""

import sys

from recorder.controller import RecorderController
from ui.main_window import MainWindow


def _confirm_continue(message: str) -> bool:
    """Show the problems in a warning dialog; True if the app should open.

    If the dialog cannot be shown (no display, broken Tk), the message has
    already been printed to the terminal, so the app just carries on.
    """
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        try:
            return bool(
                messagebox.askyesno(
                    "Soul Screen Recorder",
                    message + "\n\nOpen the app anyway?",
                    icon="warning",
                    default="no",
                    parent=root,
                )
            )
        finally:
            root.destroy()
    except Exception:
        return True


def _platform_ok(controller: RecorderController) -> bool:
    """Check the platform; False if the user chose to quit after a warning."""
    message = controller.get_compatibility().blocking_message()
    if message is None:
        return True
    print(message, file=sys.stderr)
    return _confirm_continue(message)


def main() -> int:
    controller = RecorderController()
    if not _platform_ok(controller):
        return 1
    window = MainWindow(controller)
    window.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())