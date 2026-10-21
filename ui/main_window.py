"""Main window: a single Record/Stop button and a status indicator."""

import tkinter as tk
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

        self._controller.add_listener(self._on_state_changed)
        self._apply_state(self._controller.state, self._controller.message)

    # ---- event handling -----------------------------------------------

    def _on_button_click(self) -> None:
        self._controller.toggle()

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