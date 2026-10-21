"""Recording controller: owns the current state and notifies listeners.

The one-click Record/Stop state machine drives the capture layer: Record
creates a timestamped session folder, detects the devices and starts the
camera and screen ffmpeg captures; Stop finalizes both files. Any capture,
device or session failure is surfaced as the ERROR state with a message.
After Stop, the `_process` hook composites the two raw files into final.mp4
(screen with the presenter in a bottom-right overlay); a compositing failure
is also surfaced as the ERROR state, and the raw files are kept.
"""

import threading
from typing import Callable, List, Optional

from recorder.capture import CaptureError, DualCapture
from recorder.compositor import composite
from recorder.devices import DeviceError, detect_devices
from recorder.session import Session, SessionError, create_session
from recorder.state import RecorderState

StateListener = Callable[[RecorderState, Optional[str]], None]


class RecorderController:
    def __init__(self) -> None:
        self._state = RecorderState.IDLE
        self._message: Optional[str] = None
        self._listeners: List[StateListener] = []
        self._lock = threading.Lock()
        self._session: Optional[Session] = None
        self._capture: Optional[DualCapture] = None

    # ---- state access -------------------------------------------------

    @property
    def state(self) -> RecorderState:
        return self._state

    @property
    def session(self) -> Optional[Session]:
        """The current (or most recent) session folder and its file paths."""
        return self._session

    @property
    def message(self) -> Optional[str]:
        """Optional detail text (e.g. an error description) for the state."""
        return self._message

    # ---- listeners ----------------------------------------------------

    def add_listener(self, listener: StateListener) -> None:
        """Register a callback invoked as listener(state, message).

        Callbacks may be invoked from a background thread, so UI code
        must marshal them onto its own thread (e.g. Tk's `after`).
        """
        self._listeners.append(listener)

    def _set_state(self, state: RecorderState, message: Optional[str] = None) -> None:
        self._state = state
        self._message = message
        for listener in list(self._listeners):
            try:
                listener(state, message)
            except Exception:
                # A broken listener must never break recording.
                pass

    # ---- user actions -------------------------------------------------

    def toggle(self) -> None:
        """Single entry point for the Record/Stop button."""
        with self._lock:
            state = self._state
            if state in (
                RecorderState.IDLE,
                RecorderState.DONE,
                RecorderState.ERROR,
            ):
                self._begin_recording()
            elif state == RecorderState.RECORDING:
                self._end_recording()
            # PROCESSING: ignore clicks until finished.

    def _begin_recording(self) -> None:
        try:
            self._start_capture()
        except Exception as exc:
            self._set_state(RecorderState.ERROR, str(exc))
            return
        self._set_state(RecorderState.RECORDING)

    def _end_recording(self) -> None:
        try:
            self._stop_capture()
        except Exception as exc:
            self._set_state(RecorderState.ERROR, str(exc))
            return
        self._set_state(RecorderState.PROCESSING)
        # Process off the calling thread so the UI never freezes.
        threading.Thread(target=self._run_processing, daemon=True).start()

    def _run_processing(self) -> None:
        try:
            self._process()
        except Exception as exc:
            self._set_state(RecorderState.ERROR, str(exc))
            return
        session = self._session
        folder_note = f"Saved to {session.folder}" if session is not None else None
        self._set_state(RecorderState.DONE, folder_note)

    # ---- hooks for the capture/compositing layer ---------------------

    def _start_capture(self) -> None:
        """Create the session folder and start the camera and screen captures.

        Raises DeviceError, SessionError or CaptureError on failure; the
        caller turns these into the ERROR state.
        """
        self._session = None
        self._capture = None

        devices = detect_devices()
        session = create_session()
        capture = DualCapture(devices, session.camera_path, session.screen_path)
        capture.start()

        self._session = session
        self._capture = capture

    def _stop_capture(self) -> None:
        """Stop both captures and wait for the files to be finalized.

        Raises CaptureError if a file could not be finalized cleanly.
        """
        capture = self._capture
        self._capture = None
        if capture is None:
            raise CaptureError("No recording is in progress.")
        capture.stop()

    def _process(self) -> None:
        """Composite camera.mp4 and screen.mp4 into final.mp4.

        Raises CompositeError on failure; the caller turns it into the
        ERROR state. The raw camera.mp4 and screen.mp4 are left untouched.
        """
        session = self._session
        if session is None:
            raise RuntimeError("No recording session to process.")
        composite(session.screen_path, session.camera_path, session.final_path)