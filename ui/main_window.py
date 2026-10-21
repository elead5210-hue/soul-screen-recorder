"""Main window: a single Record/Stop button and a status indicator."""

import tkinter as tk
from tkinter import messagebox
from typing import Optional

from recorder.controller import RecorderController
from recorder.state import RecorderState, style_for


class MainWindow:
    def __init__(self, controller: RecorderController) -> None:
        self._controller = controller

        self._root = tk.Tk()
        self._root.title("Soul Screen Recorder")
        self._root.resizable(False, False)

        frame = tk.Frame(self._root, padx=24, pady=20)
        frame.pack()

        # Status indicator: a colored dot next to a text label.
        status_row = tk.Frame(frame)
        status_row.pack(pady=(0, 14))

        self._dot = tk.Canvas(
            status_row, width=16, height=16, highlightthickness=0
        )
        self._dot_item = self._dot.create_oval(2, 2, 14, 14, fill="#6b7280", outline="")
        self._dot.pack(side=tk.LEFT, padx=(0, 8))

        self._status_label = tk.Label(
            status_row, text="", font=("Helvetica", 14), width=28, anchor="w"
        )
        self._status_label.pack(side=tk.LEFT)

        # Optional detail line (e.g. an error description).
        self._detail_label = tk.Label(
            frame,
            text="",
            font=("Helvetica", 11),
            fg="#7f1d1d",
            wraplength=320,
            justify="left",
        )
        self._detail_label.pack(pady=(0, 10))

        # The single Record/Stop toggle button.
        self._button = tk.Button(
            frame,
            text="Record",
            font=("Helvetica", 16, "bold"),
            width=16,
            height=2,
            command=self._on_button_click,
        )
        self._button.pack()

        # Intercept the window close button so an in-progress recording is
        # finalized cleanly instead of being cut off mid-write.
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._controller.add_listener(self._on_state_changed)
        self._apply_state(self._controller.state, self._controller.message)

    # ---- event handling -----------------------------------------------

    def _on_button_click(self) -> None:
        self._controller.toggle()

    def _on_close(self) -> None:
        state = self._controller.state
        if state in (RecorderState.RECORDING, RecorderState.PROCESSING):
            if state == RecorderState.RECORDING:
                prompt = (
                    "A recording is in progress.\n\n"
                    "Quit now? The recording will be stopped and saved "
                    "(camera.mp4 and screen.mp4), but final.mp4 will not be "
                    "created. You can create it later with recorder.recomposite."
                )
            else:
                prompt = (
                    "The recording is still being finalized.\n\n"
                    "Quit now? The app will wait for the files to finish "
                    "saving first, but final.mp4 may not be created. You can "
                    "create it later with recorder.recomposite."
                )
            if not messagebox.askyesno(
                "Quit Soul Screen Recorder?", prompt, parent=self._root
            ):
                return

            # Show feedback while ffmpeg flushes; shutdown() blocks for a
            # few seconds until the files are finalized.
            self._button.config(state=tk.DISABLED)
            self._status_label.config(text="Saving files...", fg="#d97706")
            self._detail_label.config(text="")
            self._root.update_idletasks()

        self._controller.shutdown()
        self._root.destroy()

    def _on_state_changed(self, state: RecorderState, message: Optional[str]) -> None:
        # The controller may call us from a background thread; Tk is not
        # thread-safe, so hand the update to the Tk main loop.
        try:
            self._root.after(0, self._apply_state, state, message)
        except (tk.TclError, RuntimeError):
            # Window already closed; nothing to update.
            pass

    # ---- rendering ----------------------------------------------------

    def _apply_state(self, state: RecorderState, message: Optional[str]) -> None:
        style = style_for(state)
        self._dot.itemconfig(self._dot_item, fill=style.color)
        self._status_label.config(text=style.label, fg=style.color)
        self._button.config(
            text=style.button_text,
            state=tk.NORMAL if style.button_enabled else tk.DISABLED,
        )
        self._detail_label.config(text=message or "")

    # ---- lifecycle ----------------------------------------------------

    def run(self) -> None:
        self._root.mainloop()