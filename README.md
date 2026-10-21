# Soul Screen Recorder

A macOS app (Python) that records the screen and the presenter as two separate streams, then combines them into one video with the presenter in a picture-in-picture at the bottom right.

> **Current status (v1):** the window, the single Record/Stop button, the status indicator and the two ffmpeg captures are implemented. Record starts the camera and screen captures; Stop finalizes `camera.mp4` and `screen.mp4` in a timestamped folder and then automatically combines them into `final.mp4`: the screen as the main video, the presenter in a small bottom-right overlay, and the microphone and system audio mixed together.

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
  final.mp4     screen with the presenter overlay, mic + system audio mixed
```

In `final.mp4` the presenter is scaled to about 320 px wide and placed in the bottom-right corner with a 20 px margin. `final.mp4` is written to a temporary file first and only renamed when ffmpeg succeeds, so a failed run never leaves a broken file. If compositing fails, the app shows the **Error** status, and `camera.mp4` and `screen.mp4` are still saved.

If you start two recordings within the same minute, the second folder gets a `-2` suffix, so an earlier recording is never overwritten. The app refuses to start if less than 1 GB of disk space is free.

When a recording finishes, the **Done** status shows the folder it was saved to.

## Reliable file output

Stopping always tries to leave playable MP4 files behind, even when something goes wrong:

- **Clean stop.** On Stop, the app sends `q` to both ffmpeg processes. ffmpeg then flushes its buffers and finishes the files properly. If a process has not exited after 20 seconds, it is terminated, and then force-killed if needed.
- **Crash-resilient MP4s.** `camera.mp4` and `screen.mp4` are written as fragmented MP4 (a new playable fragment about every 2 seconds). If ffmpeg is force-closed, or the app or the Mac crashes during a recording, everything recorded up to the last fragment stays playable instead of the file being left without its index.
- **Verification after stop.** Before reporting success, the app checks that both files exist, are not empty, and can be opened by ffmpeg. If a file is missing or unreadable, the **Error** status explains which one, and `final.mp4` is not created from it.
- **Safe closing.** If you close the window while recording or processing, the app asks for confirmation. If you confirm, it stops the captures cleanly and waits for the files to finish saving (a few seconds) before quitting. `camera.mp4` and `screen.mp4` are kept, but `final.mp4` is not created on quit; create it later with `recorder.recomposite` (see below).

Quitting the app in other ways, such as force-quitting or pressing Ctrl+C in the terminal, cannot stop ffmpeg cleanly. The fragmented format means the recording up to that moment should still be playable.

## Raw files are kept

Every session folder keeps all three files: `camera.mp4`, `screen.mp4` and `final.mp4`. The raw `camera.mp4` and `screen.mp4` are never modified, deleted or overwritten by the app, including when compositing fails, so you can always create the final video again.

### Re-compositing a session

To rebuild the picture-in-picture video from the raw files of an existing session, run this from the project folder:

```bash
python3 -m recorder.recomposite recordings/2026-10-21_14-46
```

By default this replaces `final.mp4` in that folder. Options:

- `--pip-width 480` sets the overlay width in pixels (default 320)
- `--margin 30` sets the distance from the bottom-right corner in pixels (default 20)
- `--output final_large_pip.mp4` writes a different file name inside the session folder and keeps the existing `final.mp4`

The new file is written to a temporary file first and renamed only when ffmpeg succeeds, so a failed run never damages an existing `final.mp4`.

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

A small window opens with a status indicator and one button. Closing the window during a recording asks for confirmation and saves the raw files before quitting.

## How to use

1. Click **Record** to start a recording. The button changes to **Stop**.
2. Click **Stop** to finish. The app finalizes the two raw files and creates `final.mp4` while the button is disabled. Long recordings take longer to combine.
3. When processing finishes, the status shows **Done** and the button returns to **Record** so you can start again.

## Status indicators

| Status | Color | Meaning | Button |
|--------|-------|---------|--------|
| Idle - ready to record | Gray | Nothing is running; ready for a new recording. | **Record** (enabled) |
| Recording... | Red | A recording is in progress. | **Stop** (enabled) |
| Processing... | Orange | Recording has stopped and the files are being finalized and combined into `final.mp4`. Clicks are ignored. | **Processing...** (disabled) |
| Done - recording saved | Green | The last recording finished successfully. | **Record** (enabled) |
| Error - something went wrong | Dark red | Starting, stopping, or processing failed. A detail message is shown under the status. | **Record** (enabled) |

## Project layout

```
main.py                  Entry point: creates the controller and window
recorder/
  state.py               Recording states and their label/color/button styles
  controller.py          Record/Stop state machine; notifies the UI of changes
  devices.py             Finds the camera, microphone, screen and BlackHole devices
  capture.py             Starts and stops the two ffmpeg captures; writes fragmented MP4s and verifies them after stop
  session.py             Creates the timestamped session folder
  compositor.py          Builds final.mp4: PiP overlay and mixed audio via ffmpeg
  recomposite.py         Command-line tool to re-composite an existing session folder
ui/
  main_window.py         Tkinter window: status indicator, Record/Stop button, safe close handling
requirements.txt         Dependencies (none required yet)
```

## How it works

- `RecorderController.toggle()` is the single entry point for the button. It starts a recording from Idle, Done, or Error, and stops it from Recording.
- Stopping and processing run in a background thread, so the window never freezes while ffmpeg flushes the files.
- `RecorderController.shutdown()` is called when the window is closed. It stops any running capture cleanly and waits for the files to be finalized before the app exits. It does not create `final.mp4`.
- The controller notifies the window of every state change, and the window updates the indicator and button accordingly.
- On Record, `_start_capture` detects the devices, creates the session folder and launches the camera and screen ffmpeg processes back to back. On Stop, `_stop_capture` asks both to finish so the MP4 files are finalized cleanly, and then checks that each file can be opened before processing continues.
- Any device, session or capture failure is shown as the **Error** status with a detail message.
- After Stop, `_process` runs in the background thread and calls `compositor.composite()`, which runs ffmpeg with an overlay filter (presenter scaled to about 320 px, 20 px from the bottom-right corner) and mixes the microphone from `camera.mp4` with the system audio from `screen.mp4`. The raw files are never modified.