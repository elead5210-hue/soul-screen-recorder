# Soul Screen Recorder

A macOS app (Python) that records the screen and the presenter as two separate streams, then combines them into one video with the presenter in a picture-in-picture at the bottom right.

> **Current status (v1):** the window, the single Record/Stop button, the status indicator and the two ffmpeg captures are implemented. Record starts the camera and screen captures; Stop finalizes `camera.mp4` and `screen.mp4` in a timestamped folder. The picture-in-picture `final.mp4` is plugged in by a later goal.

## Requirements

- macOS 13 or newer (recommended)
- Python 3.9 or newer with Tkinter
- No Python packages are needed for the current version
- `ffmpeg` (external dependency, installed with Homebrew)
- The BlackHole 2ch audio driver, for system audio capture

Tkinter is included with the python.org installer. If you use Homebrew Python, install it with:

```bash
brew install python-tk
```

## Install ffmpeg and BlackHole

Capture is done by `ffmpeg` (avfoundation input, `h264_videotoolbox` hardware encoding), which is not a Python package and must be installed separately:

```bash
brew install ffmpeg
brew install --cask blackhole-2ch
```

Restart your Mac after installing BlackHole if it does not show up as an audio device.

## Set up system audio (Multi-Output Device)

BlackHole 2ch is a virtual audio device that lets the app record what your Mac is playing. On its own it is silent to you, so create a Multi-Output Device that sends sound to both your speakers or headphones and BlackHole:

1. Open **Audio MIDI Setup** (Applications > Utilities).
2. Click the **+** button at the bottom left and choose **Create Multi-Output Device**.
3. Tick your normal output (for example **MacBook Pro Speakers** or your headphones) and **BlackHole 2ch**.
4. Set your normal output as the **Primary Device** (the clock source) and tick **Drift Correction** for **BlackHole 2ch**.
5. Open **System Settings > Sound > Output** and select the new **Multi-Output Device** before recording.

The app records system audio from BlackHole 2ch, and you still hear it through your normal output. Select your normal output again in Sound settings when you are done. The volume keys do not work on a Multi-Output Device, so set the volume on your speakers or headphones.

## macOS permissions

The first time you record, macOS asks for access. Open **System Settings > Privacy & Security** and enable the app that launches Python (for example **Terminal**, **iTerm** or your IDE) under:

- **Camera**: to record the presenter
- **Microphone**: to record your voice
- **Screen & System Audio Recording**: to record the screen

Quit and reopen that app after changing a permission, because macOS only applies it to newly started processes. If a permission is missing, the capture fails to start and the app shows the **Error** status with ffmpeg's message.

## Where recordings are saved

Each recording gets its own timestamped folder inside `recordings/`, created in the folder you run the app from:

```
recordings/2026-10-21_14-46/
  camera.mp4    presenter: webcam + microphone
  screen.mp4    screen + system audio (BlackHole)
```

If you start two recordings within the same minute, the second folder gets a `-2` suffix, so an earlier recording is never overwritten. The raw files are always kept. The app refuses to start if less than 1 GB of disk space is free.

## Install

```bash
git clone <your-repo-url> soul-screen-recorder
cd soul-screen-recorder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python3 main.py
```

A small window opens with a status indicator and one button.

## How to use

1. Click **Record** to start a recording. The button changes to **Stop**.
2. Click **Stop** to finish. The app processes the recording while the button is disabled.
3. When processing finishes, the status shows **Done** and the button returns to **Record** so you can start again.

## Status indicators

| Status | Color | Meaning | Button |
|--------|-------|---------|--------|
| Idle - ready to record | Gray | Nothing is running; ready for a new recording. | **Record** (enabled) |
| Recording... | Red | A recording is in progress. | **Stop** (enabled) |
| Processing... | Orange | Recording has stopped and the files are being finalized and combined. Clicks are ignored. | **Processing...** (disabled) |
| Done - recording saved | Green | The last recording finished successfully. | **Record** (enabled) |
| Error - something went wrong | Dark red | Starting, stopping, or processing failed. A detail message is shown under the status. | **Record** (enabled) |

## Project layout

```
main.py                  Entry point: creates the controller and window
recorder/
  state.py               Recording states and their label/color/button styles
  controller.py          Record/Stop state machine; notifies the UI of changes
  devices.py             Finds the camera, microphone, screen and BlackHole devices
  capture.py             Starts and stops the two ffmpeg captures
  session.py             Creates the timestamped session folder
ui/
  main_window.py         Tkinter window: status indicator and Record/Stop button
requirements.txt         Dependencies (none required yet)
```

## How it works

- `RecorderController.toggle()` is the single entry point for the button. It starts a recording from Idle, Done, or Error, and stops it from Recording.
- Processing runs in a background thread, so the window never freezes.
- The controller notifies the window of every state change, and the window updates the indicator and button accordingly.
- On Record, `_start_capture` detects the devices, creates the session folder and launches the camera and screen ffmpeg processes back to back. On Stop, `_stop_capture` asks both to finish so the MP4 files are finalized cleanly.
- Any device, session or capture failure is shown as the **Error** status with a detail message.
- The compositing step is still an empty hook in `controller.py` (`_process`) that a later goal will fill in.