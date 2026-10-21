"""Recording controller: owns the current state and notifies listeners.

The one-click Record/Stop state machine drives the capture layer: Record
creates a timestamped session folder, detects the devices and starts the
camera and screen ffmpeg captures; Stop finalizes both files on a background
thread, so the UI never waits for ffmpeg to flush. `shutdown()` stops any
running capture cleanly before the app exits. Any capture, device or session
failure is surfaced as the ERROR state with a message.
After Stop, the `_process` hook composites the two raw files into final.mp4
(screen with the presenter in a bottom-right overlay); a compositing failure
is also surfaced as the ERROR state, and the raw files are kept.
Before recording, the sound output is checked: system audio is only captured
(and still audible) when the Mac outputs to a Multi-Output Device that includes
BlackHole 2ch; otherwise the ERROR state explains how to set that up.
"""

import threading
from typing import Callable, List, Optional

from recorder.audio_output import OutputKind, detect_default_output
from recorder.capture import STOP_TIMEOUT_SECONDS, CaptureError, DualCapture
from recorder.compositor import composite
from recorder.devices import DeviceError, detect_devices
from recorder.session import Session, SessionError, create_session
from recorder.state import RecorderState

StateListener = Callable[[RecorderState, Optional[str]], None]

_MULTI_OUTPUT_STEPS = (
    "To fix this, open Audio MIDI Setup, create a Multi-Output Device that "
    "includes your speakers or headphones and BlackHole 2ch, then choose it "
    "in System Settings > Sound > Output."
)


def _check_audio_output() -> None:
    """Raise CaptureError if system audio would be silent or inaudible.

    Does nothing when the output is a Multi-Output Device or when it cannot
    be determined, so a failed check never blocks a recording by itself.
    """
    output = detect_default_output()
    name = output.name or "the current output"
    if output.kind == OutputKind.PLAIN_OUTPUT:
        raise CaptureError(
            f"Sound is currently going to \"{name}\" only, so system audio "
            f"would not be recorded. {_MULTI_OUTPUT_STEPS}"
        )
    if output.kind == OutputKind.BLACKHOLE_ONLY:
        raise CaptureError(
            f"Sound is currently going to \"{name}\" only, so you would not "
            f"be able to hear system audio while recording. "
            f"{_MULTI_OUTPUT_STEPS}"
        )


class RecorderController:
    def __init__(self) -> None:
        self._state = RecorderState.IDLE
        self._message: Optional[str] = None
        self._listeners: List[StateListener] = []
        self._lock = threading.Lock()
        self._session: Optional[Session] = None
        self._capture: Optional[DualCapture] = None
        self._worker: Optional[threading.Thread] = None
        # Set whenever no capture is being stopped (cleared while Stop is
        # waiting for ffmpeg to finalize the files).
        self._capture_done = threading.Event()
        self._capture_done.set()
        self._shutting_down = False

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
        self._set_state(RecorderState.PROCESSING)
        self._capture_done.clear()
        # Stop and finalize off the calling thread so the UI never freezes
        # while ffmpeg flushes the files.
        self._worker = threading.Thread(target=self._run_processing, daemon=True)
        self._worker.start()

    def _run_processing(self) -> None:
        try:
            try:
                self._stop_capture()
            finally:
                self._capture_done.set()
            if self._shutting_down:
                # The app is closing: the raw files are finalized and kept,
                # and can be combined later with recorder.recomposite.
                return
            self._process()
        except Exception as exc:
            self._set_state(RecorderState.ERROR, str(exc))
            return
        session = self._session
        folder_note = f"Saved to {session.folder}" if session is not None else None
        self._set_state(RecorderState.DONE, folder_note)

    def shutdown(self) -> None:
        """Cleanly stop any running capture before the app exits.

        If a recording is in progress, both ffmpeg processes are asked to
        finish so camera.mp4 and screen.mp4 are finalized and playable. If
        Stop was already clicked, this waits for that finalization to end.
        final.mp4 is not created on shutdown; use recorder.recomposite for
        that. Blocks for up to a few seconds while ffmpeg flushes.
        """
        self._shutting_down = True
        with self._lock:
            capture = self._capture
            self._capture = None
        if capture is not None:
            try:
                capture.stop()
            except Exception:
                # Best effort: the app is closing and there is nowhere
                # left to show an error.
                pass
        self._capture_done.wait(timeout=STOP_TIMEOUT_SECONDS * 2 + 15)

    # ---- hooks for the capture/compositing layer ---------------------

    def _start_capture(self) -> None:
        """Create the session folder and start the camera and screen captures.

        Raises DeviceError, SessionError or CaptureError on failure; the
        caller turns these into the ERROR state.
        """
        self._session = None
        self._capture = None

        _check_audio_output()
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
        with self._lock:
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