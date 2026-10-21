"""Recording states and how each one is presented in the UI."""

from enum import Enum
from typing import NamedTuple


class RecorderState(Enum):
    IDLE = "idle"
    STARTING = "starting"
    RECORDING = "recording"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class StateStyle(NamedTuple):
    label: str          # text shown in the status indicator
    color: str          # indicator color (Tk color name or hex)
    button_text: str    # text shown on the Record/Stop button
    button_enabled: bool  # whether the button can be clicked in this state


STATE_STYLES = {
    RecorderState.IDLE: StateStyle(
        label="Idle - ready to record",
        color="#6b7280",
        button_text="Record",
        button_enabled=True,
    ),
    RecorderState.STARTING: StateStyle(
        label="Starting...",
        color="#d97706",
        button_text="Starting...",
        button_enabled=False,
    ),
    RecorderState.RECORDING: StateStyle(
        label="Recording...",
        color="#dc2626",
        button_text="Stop",
        button_enabled=True,
    ),
    RecorderState.PROCESSING: StateStyle(
        label="Processing...",
        color="#d97706",
        button_text="Processing...",
        button_enabled=False,
    ),
    RecorderState.DONE: StateStyle(
        label="Done - recording saved",
        color="#16a34a",
        button_text="Record",
        button_enabled=True,
    ),
    RecorderState.ERROR: StateStyle(
        label="Error - something went wrong",
        color="#7f1d1d",
        button_text="Record",
        button_enabled=True,
    ),
}


def style_for(state: RecorderState) -> StateStyle:
    """Return the presentation style for a given state."""
    return STATE_STYLES[state]