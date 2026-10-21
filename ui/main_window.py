"""Main window: a single Record/Stop button and a status indicator."""

import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, Optional

from recorder.controller import DeviceOptions, RecorderController
from recorder.device_settings import DeviceSettings, SettingsError
from recorder.devices import AUTO_CHOICE
from recorder.state import RecorderState, style_for

# Width (in pixels) of the window's content and of the wrapped message text.
_CONTENT_WIDTH = 420
# Longest message body shown; the rest is cut so the window stays a sane size.
_MAX_BODY_CHARS = 900


class MainWindow:
    def __init__(self, controller: RecorderController) -> None:
        self._controller = controller
        # Set once the user confirmed closing; state updates are then ignored
        # so they cannot overwrite the "Saving files..." feedback.
        self._closing = False
        self._shutdown_thread: Optional[threading.Thread] = None
        # True while the device list is being loaded on a background thread.
        self._loading_devices = False
        # Permission checks run on a background thread; a request that arrives
        # while one is running is repeated afterwards so the note stays current.
        self._checking_permissions = False
        self._recheck_permissions = False

        self._root = tk.Tk()
        self._root.title("Soul Screen Recorder")
        self._root.resizable(False, False)

        frame = tk.Frame(self._root, padx=24, pady=20)
        frame.pack()

        # Fixed minimum width, so a long error message wraps inside the same
        # width instead of making the window jump wider.
        tk.Frame(frame, width=_CONTENT_WIDTH, height=1).pack()

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

        # Optional message under the status. For an error, the first sentence
        # (what went wrong) is a bold heading, and the rest (how to fix it,
        # and what ffmpeg said) is the body below it.
        self._detail_heading = tk.Label(
            frame,
            text="",
            font=("Helvetica", 11, "bold"),
            fg="#7f1d1d",
            wraplength=_CONTENT_WIDTH,
            justify="left",
            anchor="w",
        )
        self._heading_visible = False
        self._detail_label = tk.Label(
            frame,
            text="",
            font=("Helvetica", 11),
            fg="#7f1d1d",
            wraplength=_CONTENT_WIDTH,
            justify="left",
            anchor="w",
        )
        self._detail_label.pack(anchor="w", pady=(0, 10))

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

        # Devices section: pick a camera, microphone and screen, or leave
        # each on Auto-detect. The lists are filled in on a background thread.
        devices_frame = tk.LabelFrame(frame, text="Devices", padx=10, pady=8)
        devices_frame.pack(fill=tk.X, pady=(16, 0))
        devices_frame.columnconfigure(1, weight=1)

        self._device_vars: Dict[str, tk.StringVar] = {}
        self._device_boxes: Dict[str, ttk.Combobox] = {}
        for row, (key, title) in enumerate(
            (
                ("camera", "Camera"),
                ("microphone", "Microphone"),
                ("screen", "Screen"),
            )
        ):
            tk.Label(devices_frame, text=title, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=3
            )
            var = tk.StringVar(value=AUTO_CHOICE)
            box = ttk.Combobox(
                devices_frame,
                textvariable=var,
                values=[AUTO_CHOICE],
                state="readonly",
                width=30,
            )
            box.grid(row=row, column=1, sticky="ew", pady=3)
            box.bind("<<ComboboxSelected>>", self._on_device_choice)
            self._device_vars[key] = var
            self._device_boxes[key] = box

        self._refresh_button = tk.Button(
            devices_frame, text="Refresh", command=self._load_devices
        )
        self._refresh_button.grid(row=3, column=0, sticky="w", pady=(6, 0))

        self._devices_note = tk.Label(
            devices_frame,
            text="",
            font=("Helvetica", 10),
            fg="#6b7280",
            wraplength=240,
            justify="left",
            anchor="w",
        )
        self._devices_note.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        # Permissions note: only shown while Camera, Microphone or Screen
        # Recording access is turned off, so the problem is visible before
        # the user clicks Record.
        self._permissions_frame = tk.LabelFrame(
            frame, text="Permissions", padx=10, pady=8
        )
        self._permissions_label = tk.Label(
            self._permissions_frame,
            text="",
            font=("Helvetica", 11),
            fg="#7f1d1d",
            wraplength=320,
            justify="left",
            anchor="w",
        )
        self._permissions_label.pack(fill=tk.X)
        self._privacy_button = tk.Button(
            self._permissions_frame,
            text="Open Privacy Settings",
            command=self._on_open_privacy_settings,
        )
        self._privacy_button.pack(anchor="w", pady=(8, 0))
        self._permissions_visible = False
        self._devices_frame = devices_frame

        # Intercept the window close button so an in-progress recording is
        # finalized cleanly instead of being cut off mid-write.
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._controller.add_listener(self._on_state_changed)
        self._apply_state(self._controller.state, self._controller.message)
        self._load_devices()

        # Re-check permissions whenever the window regains focus (for example
        # after the user came back from System Settings).
        self._root.bind("<FocusIn>", self._on_focus_in)
        self._check_permissions()

    # ---- event handling -----------------------------------------------

    def _on_button_click(self) -> None:
        self._controller.toggle()

    def _on_close(self) -> None:
        if self._closing:
            return
        state = self._controller.state
        if state in (
            RecorderState.STARTING,
            RecorderState.RECORDING,
            RecorderState.PROCESSING,
        ):
            if state in (RecorderState.STARTING, RecorderState.RECORDING):
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

            # Show feedback while ffmpeg flushes the files.
            self._closing = True
            self._button.config(state=tk.DISABLED)
            self._update_device_controls()
            self._update_permission_controls()
            self._status_label.config(text="Saving files...", fg="#d97706")
            self._set_detail("", "", False)

        self._closing = True
        # shutdown() can take a few seconds while ffmpeg flushes, so run it
        # on a background thread and keep the Tk loop running; the window is
        # destroyed only when it has finished.
        self._shutdown_thread = threading.Thread(
            target=self._controller.shutdown, daemon=True
        )
        self._shutdown_thread.start()
        self._poll_shutdown()

    def _poll_shutdown(self) -> None:
        thread = self._shutdown_thread
        if thread is not None and thread.is_alive():
            self._root.after(100, self._poll_shutdown)
            return
        self._root.destroy()

    # ---- device choices -----------------------------------------------

    def _update_device_controls(self) -> None:
        """Enable the dropdowns only when idle and not loading the list."""
        busy = self._closing or self._controller.state in (
            RecorderState.STARTING,
            RecorderState.RECORDING,
            RecorderState.PROCESSING,
        )
        enabled = not busy and not self._loading_devices
        for box in self._device_boxes.values():
            box.config(state="readonly" if enabled else "disabled")
        self._refresh_button.config(state=tk.NORMAL if enabled else tk.DISABLED)

    def _load_devices(self) -> None:
        """Fill the dropdowns without blocking the UI (ffmpeg takes a moment)."""
        if self._loading_devices or self._closing:
            return
        self._loading_devices = True
        self._devices_note.config(text="Looking for devices...", fg="#6b7280")
        self._update_device_controls()
        threading.Thread(target=self._device_worker, daemon=True).start()

    def _device_worker(self) -> None:
        options: Optional[DeviceOptions] = None
        settings = DeviceSettings()
        error: Optional[str] = None
        try:
            settings = self._controller.get_device_settings()
            options = self._controller.list_device_options()
        except Exception as exc:  # shown to the user, never fatal
            error = str(exc) or "Could not list the devices."
        try:
            self._root.after(0, self._apply_devices, options, settings, error)
        except (tk.TclError, RuntimeError):
            # Window already closed; nothing to update.
            pass

    def _apply_devices(
        self,
        options: Optional[DeviceOptions],
        settings: DeviceSettings,
        error: Optional[str],
    ) -> None:
        self._loading_devices = False
        if self._closing:
            return
        saved = {
            "camera": settings.camera,
            "microphone": settings.microphone,
            "screen": settings.screen,
        }
        available = {
            "camera": options.cameras if options else [],
            "microphone": options.microphones if options else [],
            "screen": options.screens if options else [],
        }
        missing = []
        for key, box in self._device_boxes.items():
            names = list(available[key])
            choice = saved[key] or AUTO_CHOICE
            if choice != AUTO_CHOICE and choice not in names:
                # Keep the remembered choice visible; recording falls back
                # to auto-detection while the device is not connected.
                names.append(choice)
                if options is not None:
                    missing.append(choice)
            box.config(values=[AUTO_CHOICE] + names)
            self._device_vars[key].set(choice)

        if error:
            self._devices_note.config(text=error, fg="#7f1d1d")
        elif missing:
            self._devices_note.config(
                text="Not connected: "
                + ", ".join(missing)
                + ". Auto-detect will be used instead.",
                fg="#d97706",
            )
        else:
            self._devices_note.config(text="", fg="#6b7280")
        self._update_device_controls()

    def _on_device_choice(self, _event: Optional[tk.Event] = None) -> None:
        settings = DeviceSettings(
            camera=self._device_vars["camera"].get() or AUTO_CHOICE,
            microphone=self._device_vars["microphone"].get() or AUTO_CHOICE,
            screen=self._device_vars["screen"].get() or AUTO_CHOICE,
        )
        try:
            self._controller.save_device_settings(settings)
        except SettingsError as exc:
            self._devices_note.config(
                text=f"Could not save your choice: {exc}", fg="#7f1d1d"
            )
        else:
            self._devices_note.config(text="", fg="#6b7280")

    # ---- permissions --------------------------------------------------

    def _on_focus_in(self, event: Optional[tk.Event] = None) -> None:
        # <FocusIn> is also delivered for child widgets; react to the window only.
        if event is not None and event.widget is not self._root:
            return
        self._check_permissions()

    def _check_permissions(self) -> None:
        """Check the privacy permissions without blocking the UI."""
        if self._closing:
            return
        if self._checking_permissions:
            self._recheck_permissions = True
            return
        self._checking_permissions = True
        threading.Thread(target=self._permission_worker, daemon=True).start()

    def _permission_worker(self) -> None:
        missing = None
        summary = ""
        try:
            missing = self._controller.check_permissions()
            if missing:
                summary = self._controller.permission_summary()
        except Exception:  # never fatal; recording reports the problem itself
            missing = None
        try:
            self._root.after(0, self._apply_permissions, missing, summary)
        except (tk.TclError, RuntimeError):
            # Window already closed; nothing to update.
            pass

    def _apply_permissions(self, missing, summary: str) -> None:
        self._checking_permissions = False
        if self._closing:
            return
        if missing:
            self._permissions_label.config(
                text=(
                    f"{summary} Turn it on for the app that launches Python "
                    "(Terminal, iTerm or your code editor), then quit and "
                    "reopen that app."
                )
            )
            if not self._permissions_visible:
                self._permissions_frame.pack(
                    fill=tk.X, pady=(16, 0), before=self._devices_frame
                )
                self._permissions_visible = True
        elif self._permissions_visible:
            self._permissions_frame.pack_forget()
            self._permissions_visible = False
        self._update_permission_controls()
        if self._recheck_permissions:
            self._recheck_permissions = False
            self._check_permissions()

    def _update_permission_controls(self) -> None:
        """The settings button is disabled while the window is closing."""
        self._privacy_button.config(
            state=tk.DISABLED if self._closing else tk.NORMAL
        )

    def _on_open_privacy_settings(self) -> None:
        if self._closing:
            return
        threading.Thread(
            target=self._controller.open_privacy_settings, daemon=True
        ).start()

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
        if self._closing:
            return
        style = style_for(state)
        self._dot.itemconfig(self._dot_item, fill=style.color)
        self._status_label.config(text=style.label, fg=style.color)
        self._button.config(
            text=style.button_text,
            state=tk.NORMAL if style.button_enabled else tk.DISABLED,
        )
        self._show_message(state, message)
        self._update_device_controls()
        if state in (RecorderState.DONE, RecorderState.ERROR):
            # A recording just ended (or failed): re-check the permissions.
            self._check_permissions()

    def _show_message(self, state: RecorderState, message: Optional[str]) -> None:
        """Show the state's message; errors get a heading plus a body."""
        text = (message or "").strip()
        if not text:
            self._set_detail("", "", False)
            return
        if state != RecorderState.ERROR:
            self._set_detail("", text, False)
            return

        first_line, _, rest = text.partition("\n")
        # The first sentence says what went wrong; what follows says what to do.
        sentences = re.split(r"(?<=[.!?])\s+", first_line.strip(), maxsplit=1)
        heading = sentences[0]
        body_parts = [sentences[1]] if len(sentences) > 1 else []
        if rest.strip():
            body_parts.append(rest.strip())
        self._set_detail(heading, "\n".join(body_parts), True)

    def _set_detail(self, heading: str, body: str, is_error: bool) -> None:
        if len(body) > _MAX_BODY_CHARS:
            body = body[:_MAX_BODY_CHARS].rstrip() + "..."
        if heading:
            self._detail_heading.config(text=heading)
            if not self._heading_visible:
                self._detail_heading.pack(
                    before=self._detail_label, anchor="w", pady=(0, 4)
                )
                self._heading_visible = True
        elif self._heading_visible:
            self._detail_heading.pack_forget()
            self._heading_visible = False
        self._detail_label.config(
            text=body, fg="#374151" if is_error else "#7f1d1d"
        )

    # ---- lifecycle ----------------------------------------------------

    def run(self) -> None:
        self._root.mainloop()