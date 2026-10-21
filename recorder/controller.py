"""Recording controller: owns the current state and notifies listeners.

The one-click Record/Stop state machine drives the capture layer: Record
(STARTING state, on a background thread) checks the sound output, creates a
timestamped session folder, detects the devices and starts the camera and
screen ffmpeg captures; Stop finalizes both files on a background thread, so
the UI never waits for ffmpeg to start or flush. `shutdown()` stops any
running capture cleanly before the app exits. Any capture, device or session
failure is surfaced as the ERROR state with a message.
After Stop, the `_process` hook composites the two raw files into final.mp4
(screen with the presenter in a bottom-right overlay); a compositing failure
is also surfaced as the ERROR state, and the raw files are kept.
Before recording, the sound output is checked: system audio is only captured
(and still audible) when the Mac outputs to a Multi-Output Device that includes
BlackHole 2ch; otherwise the ERROR state explains how to set that up.
Before anything else, the Camera, Microphone and Screen Recording permissions
are checked; if one is turned off, the ERROR state explains how to turn it on,
and the controller lets the UI see what is missing and open the matching
System Settings pane without touching the permissions module.
The camera, microphone and screen are auto-detected unless the user picked
others in the Devices dropdowns; the controller lists the available devices
and loads and saves those choices, so the UI never touches ffmpeg or the
settings file.
"""

import threading
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from recorder.audio_output import OutputKind, detect_default_output
from recorder.capture import STOP_TIMEOUT_SECONDS, CaptureError, DualCapture
from recorder.compositor import composite
from recorder.device_settings import DeviceSettings, load_settings, save_settings
from recorder.devices import (
    DeviceError,
    camera_options,
    detect_devices,
    list_devices,
    microphone_options,
    screen_options,
)
from recorder.permissions import (
    Permission,
    check_permissions as detect_permissions,
    fix_instructions,
    missing_permissions as find_missing_permissions,
    open_privacy_settings as open_settings_pane,
    request_screen_recording_access,
    summary as permissions_summary,
)
from recorder.errors import friendly_message
from recorder.session import Session, SessionError, create_session
from recorder.state import RecorderState
from recorder.sync import SyncError, load_sync, record_launch_gap

StateListener = Callable[[RecorderState, Optional[str]], None]


@dataclass(frozen=True)
class DeviceOptions:
    """Names of the devices currently available for each dropdown."""

    cameras: List[str]
    microphones: List[str]
    screens: List[str]

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
        # Permissions found turned off by the most recent check.
        self._missing_permissions: Tuple[Permission, ...] = ()

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

    # ---- permissions --------------------------------------------------

    @property
    def missing_permissions(self) -> List[Permission]:
        """Permissions found turned off by the most recent check."""
        return list(self._missing_permissions)

    def check_permissions(self) -> List[Permission]:
        """Check Camera, Microphone and Screen Recording access.

        Returns the permissions that are turned off (an empty list if none,
        or if a status cannot be read) and remembers them in
        `missing_permissions`. Never raises.
        """
        missing = tuple(find_missing_permissions(detect_permissions()))
        self._missing_permissions = missing
        return list(missing)

    def permission_summary(self) -> str:
        """One short line about what is turned off, or '' if nothing is."""
        return permissions_summary(self._missing_permissions)

    def permission_help(self) -> str:
        """Step-by-step instructions for the missing permissions, or ''."""
        return fix_instructions(self._missing_permissions)

    def open_privacy_settings(self, permission: Optional[Permission] = None) -> bool:
        """Open the System Settings privacy pane for a permission.

        With no argument, opens the pane of the first missing permission.
        Returns False if there is nothing to open or it could not be opened.
        """
        if permission is None:
            if not self._missing_permissions:
                return False
            permission = self._missing_permissions[0]
        return open_settings_pane(permission)

    def _ensure_permissions(self) -> None:
        """Raise CaptureError with fix instructions if a permission is off.

        A permission that macOS has not asked about yet, or whose status
        cannot be read, does not block recording: macOS prompts the first
        time the device is opened.
        """
        missing = self.check_permissions()
        if not missing:
            return
        if Permission.SCREEN_RECORDING in missing:
            # Shows the one-time macOS prompt if it has not been shown yet.
            request_screen_recording_access()
        raise CaptureError(fix_instructions(missing))

    # ---- device choices -----------------------------------------------

    def list_device_options(self) -> DeviceOptions:
        """List the cameras, microphones and screens that can be chosen.

        Runs ffmpeg, which takes a moment, so call it from a background
        thread. Raises DeviceError if ffmpeg is missing or cannot list the
        devices.
        """
        devices = list_devices()
        return DeviceOptions(
            cameras=[d.name for d in camera_options(devices)],
            microphones=[d.name for d in microphone_options(devices)],
            screens=[d.name for d in screen_options(devices)],
        )

    def get_device_settings(self) -> DeviceSettings:
        """The saved device choices (all auto-detect if none were saved)."""
        return load_settings()

    def save_device_settings(self, settings: DeviceSettings) -> None:
        """Remember the device choices for next time.

        Raises SettingsError if they cannot be saved.
        """
        save_settings(settings)

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
            # STARTING / PROCESSING: ignore clicks until finished.

    def _begin_recording(self) -> None:
        # Start-up is slow (sound output check, device detection, launching
        # ffmpeg and waiting for it to come up), so it runs off the calling
        # thread. toggle() returns immediately and the UI shows STARTING.
        self._capture_done.clear()
        self._set_state(RecorderState.STARTING)
        self._worker = threading.Thread(target=self._run_start, daemon=True)
        self._worker.start()

    def _run_start(self) -> None:
        try:
            session, capture = self._start_capture()
        except Exception as exc:
            self._capture_done.set()
            # DeviceError, SessionError, CaptureError or anything unexpected:
            # always show a readable problem (and fix) under the status.
            self._set_state(RecorderState.ERROR, friendly_message(exc))
            return

        # shutdown() sets _shutting_down before it takes the lock, so either
        # it sees the capture stored here, or we see the flag and stop the
        # capture ourselves. A started capture is never left running.
        with self._lock:
            closing = self._shutting_down
            if not closing:
                self._session = session
                self._capture = capture

        if closing:
            try:
                capture.stop()
            except Exception:
                # Best effort: the app is closing.
                pass
            self._capture_done.set()
            return

        self._capture_done.set()
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
            # CaptureError, CompositeError or anything unexpected.
            self._set_state(RecorderState.ERROR, friendly_message(exc))
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

    def _start_capture(self) -> Tuple[Session, DualCapture]:
        """Create the session folder and start the camera and screen captures.

        Runs on a background thread and returns the new session and the
        running capture; the caller stores them. Raises DeviceError,
        SessionError or CaptureError on failure; the caller turns these into
        the ERROR state.
        """
        self._ensure_permissions()
        _check_audio_output()
        # load_settings never raises: a missing or damaged settings file
        # just means auto-detect. A chosen device that is not connected
        # also falls back to auto-detection.
        choices = load_settings()
        devices = detect_devices(
            camera_name=choices.camera,
            microphone_name=choices.microphone,
            screen_name=choices.screen,
        )
        session = create_session()
        capture = DualCapture(devices, session.camera_path, session.screen_path)
        capture.start()
        return session, capture

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

        # The capture stopped cleanly: keep the measured launch gap next to
        # the raw files. It is informational, so failing to save it must
        # never turn a good recording into an error.
        session = self._session
        if session is not None:
            try:
                record_launch_gap(session.sync_path, capture.launch_gap_seconds)
            except (SyncError, OSError):
                pass

    def _process(self) -> None:
        """Composite camera.mp4 and screen.mp4 into final.mp4.

        Raises CompositeError on failure; the caller turns it into the
        ERROR state. The raw camera.mp4 and screen.mp4 are left untouched.
        """
        session = self._session
        if session is None:
            raise RuntimeError("No recording session to process.")
        # load_sync never raises: a missing or damaged sync.json gives 0.
        offset = load_sync(session.sync_path).camera_offset_seconds
        composite(
            session.screen_path,
            session.camera_path,
            session.final_path,
            camera_offset=offset,
        )