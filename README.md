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

## How capture works

The app records with plain `ffmpeg` using its `avfoundation` input, launched from Python with the standard library `subprocess` module. There are no Python capture libraries and no shell: every ffmpeg call is started with an argument list, so there is no shell quoting to go wrong.

- **Finding ffmpeg.** The app uses the first `ffmpeg` on your `PATH`. If none is found, it also tries the Homebrew locations `/opt/homebrew/bin/ffmpeg` and `/usr/local/bin/ffmpeg`, because apps launched from the Finder or an IDE may not have Homebrew on their `PATH`. If ffmpeg is not installed, the app shows an **Error** status explaining how to install it.
- **Finding the devices.** When you click Record, the app runs `ffmpeg -f avfoundation -list_devices true -i ""`, reads the list ffmpeg prints, and picks the camera, microphone, screen and BlackHole device by name, using your choices from the **Devices** section of the window where you made one (see [Choosing devices](#choosing-devices)). You do not need to edit any device indexes.
- **Two ffmpeg processes.** One ffmpeg process records the presenter (`camera.mp4`) and a second records the screen (`screen.mp4`). They are started back to back, so the two recordings begin within a fraction of a second of each other.

  | Process | avfoundation input | Output |
  |---------|--------------------|--------|
  | Presenter | webcam + microphone | `camera.mp4` |
  | Screen | screen (with cursor) + BlackHole 2ch system audio | `screen.mp4` |

  Both record at 30 fps, encode video with `h264_videotoolbox` (hardware encoding, see Low CPU use) and audio with AAC.
- **Control.** ffmpeg runs in the background with its standard input connected to the app. To stop, the app writes `q` to that input (see Reliable file output).
- **Log output.** ffmpeg's own log output is not shown in the terminal. It is collected in a temporary file for each process and discarded when the capture ends. If a capture fails to start or to stop cleanly, the app reads that log, explains the problem in plain words (see [Error messages](#error-messages)) and adds the last few lines of the log as detail in the **Error** message under the status.

## Low CPU use

Recording two streams at once, and combining them afterwards, stays light on the CPU because the video is encoded by the Mac's hardware encoder instead of by the CPU:

- **Capture.** Both live captures (`camera.mp4` and `screen.mp4`) use `h264_videotoolbox`.
- **Compositing.** The `final.mp4` encode uses the same hardware encoder, so combining a long recording does not max out the CPU either.
- **One place chooses the encoder.** `recorder/encoding.py` checks once per ffmpeg binary (with `ffmpeg -encoders`) that `h264_videotoolbox` is available, and both capture and compositing take their video encoder arguments from it.
- **Fallback.** Some ffmpeg builds that are not from Homebrew are built without VideoToolbox. In that case the app automatically uses the software encoder `libx264` with the `veryfast` preset, so recording still works, just with higher CPU use. If the check itself cannot run, the app assumes hardware encoding, which is what the standard Homebrew ffmpeg provides.

To check CPU use, open **Activity Monitor** (Applications > Utilities), select the **CPU** tab, and watch the two `ffmpeg` processes while recording. With hardware encoding they should each use only a small share of one core. If they use much more, run `ffmpeg -hide_banner -encoders | grep videotoolbox`: if nothing is listed, your ffmpeg has no VideoToolbox support, so reinstall it with `brew install ffmpeg`.

## Responsive interface

The window never freezes. Everything slow runs on a background thread, and the window only draws the current status:

- **Starting.** Clicking **Record** returns immediately and the status changes to **Starting...**. The sound output check, device detection, session folder creation, ffmpeg launch and the short check that both captures came up all happen in the background. When they finish, the status changes to **Recording...** (or to **Error** with a message if something failed).
- **Stopping and compositing.** Clicking **Stop** switches to **Processing...** at once. Finalizing `camera.mp4` and `screen.mp4` and creating `final.mp4` run in a background thread, so even a long recording that takes a while to combine does not block the window.
- **Closing.** If you confirm closing the window while the app is starting, recording or processing, the window stays responsive and shows **Saving files...** while the captures are stopped in the background. It closes by itself when the files are saved.

## Choosing devices

You never need to edit code or device indexes. By default the app finds the camera, microphone and screen by itself, and the **Devices** section of the window lets you pick a different one.

### Automatic detection

Each of the three dropdowns starts on **Auto-detect**. In that mode the app lists the avfoundation devices every time you click Record and picks:

| Device | How it is picked automatically | Skipped when auto-picking |
|--------|-------------------------------|---------------------------|
| Camera | The first camera that is not a virtual camera | Virtual cameras such as Snap Camera, ManyCam, NDI Video and Desk View (used only if they are the only cameras) |
| Microphone | The first audio input that is a real microphone | BlackHole, Multi-Output and aggregate devices, Soundflower, Loopback, Zoom's audio device and other virtual devices (used only if nothing else is connected) |
| Screen | The first screen in the list, normally your main display (`Capture screen 0`) | Nothing; every display is a valid choice |
| System audio | BlackHole 2ch, always found automatically | Not selectable |

Skipping only applies to auto-detection. If you choose a device yourself, it is always used, even a virtual camera.

### Choosing a different device

1. Open the app. The **Devices** section shows **Camera**, **Microphone** and **Screen** dropdowns and a **Refresh** button. The lists are filled in the background, so the window stays responsive while the devices are being looked up (note under the dropdowns: "Looking for devices...").
2. Open a dropdown and pick the device you want, or **Auto-detect** to go back to automatic selection. The choice is saved as soon as you select it.
3. Click **Refresh** if you plug in or remove a device while the app is open.

The dropdowns list every camera, every audio input except BlackHole (which is reserved for system audio), and every screen. They are disabled while the app is starting, recording or processing, so a recording can never change devices halfway through. They become active again when the status returns to Idle, Done or Error.

### Where your choice is saved

Your choices are remembered between runs in a small JSON file in your user folder, not in the project folder:

```
~/Library/Application Support/Soul Screen Recorder/devices.json
```

The devices are stored by name, because device numbers change when you plug devices in or out. A missing or damaged file simply means **Auto-detect** for all three, so it can never stop a recording from starting. To reset everything, choose **Auto-detect** in each dropdown or delete that file.

### If a chosen device is unplugged

The app does not fail. The saved name stays in the dropdown and a note under it says which device is not connected. When you click Record, any chosen device that is not connected is replaced by automatic detection for that recording, and your saved choice is kept. When you plug the device back in, it is used again on the next recording, even without clicking **Refresh** (Refresh only updates the dropdowns and the note).

### Device troubleshooting

- **The dropdowns only show Auto-detect, with a red note under them.** The app could not list the devices. The note says why; usually ffmpeg is not installed (`brew install ffmpeg`) or ffmpeg could not run. Fix it and click **Refresh**.
- **A camera, microphone or screen is missing from its dropdown.** Connect it, check that macOS has granted Camera, Microphone and Screen Recording permission (see macOS permissions), and click **Refresh**.
- **BlackHole 2ch is not in the Microphone list.** This is intentional: it carries the system audio and is always used for that automatically.
- **The wrong camera or microphone is used.** Choose the one you want in its dropdown instead of **Auto-detect**.
- **The dropdowns and Refresh are greyed out.** The app is starting, recording or processing, or it is still looking for devices. Wait for the status to return to Idle or Done.
- **"Could not save your choice".** The settings folder could not be written. Check that `~/Library/Application Support` is writable; recording still works with the choice you picked for this session of the app.
- **A device I unplugged is still listed.** That is the remembered choice (see above). Choose **Auto-detect** to forget it.

## Set up system audio (Multi-Output Device)

BlackHole 2ch is a virtual audio device that lets the app record what your Mac is playing. On its own it is silent to you, so create a Multi-Output Device that sends sound to both your speakers or headphones and BlackHole:

1. Open **Audio MIDI Setup** (Applications > Utilities).
2. Click the **+** button at the bottom left and choose **Create Multi-Output Device**.
3. Tick your normal output (for example **MacBook Pro Speakers** or your headphones) and **BlackHole 2ch**.
4. Set your normal output as the **Primary Device** (the clock source) and tick **Drift Correction** for **BlackHole 2ch**.
5. Open **System Settings > Sound > Output** and select the new **Multi-Output Device** before recording.

The app records system audio from BlackHole 2ch, and you still hear it through your normal output. Select your normal output again in Sound settings when you are done. The volume keys do not work on a Multi-Output Device, so set the volume on your speakers or headphones.

### Sound output check

When you click Record, the app checks where your Mac is currently sending sound (the default output in System Settings > Sound > Output):

| Current output | What happens |
|----------------|--------------|
| A Multi-Output Device | Recording starts. System audio is captured and you can still hear it. |
| Your speakers, headphones or another normal output | Recording does not start. System audio would be silent in the recording. |
| BlackHole 2ch by itself | Recording does not start. System audio would be captured, but you could not hear it. |
| Could not be determined | Recording starts without the check. |

When the check fails, the **Error** status shows a message like this:

> Sound is currently going to "MacBook Pro Speakers" only, so system audio would not be recorded. To fix this, open Audio MIDI Setup, create a Multi-Output Device that includes your speakers or headphones and BlackHole 2ch, then choose it in System Settings > Sound > Output.

Follow the steps above, select the Multi-Output Device, and click **Record** again. The check does not look inside a Multi-Output Device, so make sure BlackHole 2ch is ticked in it.

### System audio troubleshooting

- **The recording has my voice but no system audio.** Check that the Multi-Output Device is selected in System Settings > Sound > Output, that **BlackHole 2ch** is ticked in it, and that the app or video you are recording is not muted.
- **I cannot hear anything while recording.** Make sure your normal speakers or headphones are also ticked in the Multi-Output Device, and turn up the volume on the speakers or headphones themselves, because the volume keys do not work on a Multi-Output Device.
- **The app says BlackHole 2ch was not found.** Install it with `brew install --cask blackhole-2ch` and restart your Mac.
- **System audio drifts or crackles.** In the Multi-Output Device, set your normal output as the **Primary Device** and tick **Drift Correction** for BlackHole 2ch.
- **My sound is still on the Multi-Output Device after recording.** Select your normal output again in Sound settings.

A driver-free alternative using ScreenCaptureKit was evaluated and is not used in v1; see [docs/screencapturekit-evaluation.md](docs/screencapturekit-evaluation.md).

## macOS permissions

The first time you record, macOS asks for access. Open **System Settings > Privacy & Security** and enable the app that launches Python (for example **Terminal**, **iTerm** or your IDE) under:

- **Camera**: to record the presenter
- **Microphone**: to record your voice
- **Screen & System Audio Recording**: to record the screen

Quit and reopen that app after changing a permission, because macOS only applies it to newly started processes.

### Permission check

The app checks the three permissions itself, before you record, so a missing one is visible up front instead of showing up as a broken video. The check is done by `recorder/permissions.py` using the macOS system frameworks, so no extra Python packages are needed.

- **When it runs.** On a background thread when the app starts, whenever the window regains focus (for example when you come back from System Settings) and after each recording. The window never freezes while it runs.
- **Permissions note.** If Camera, Microphone or Screen Recording access is turned off, a **Permissions** note appears under the Record button. It says which permissions are off and gives the short fix: turn them on for the app that launches Python (Terminal, iTerm or your code editor), then quit and reopen that app. When everything is allowed, the note is hidden.
- **Open Privacy Settings button.** The note has an **Open Privacy Settings** button that opens the matching pane of System Settings > Privacy & Security directly. The button is disabled while the window is closing.
- **Check on Record.** The permissions are checked again when you click **Record**. If one is still off, recording does not start and the **Error** status shows the exact fix steps:
  1. Open System Settings > Privacy & Security and the pane for the missing permission (Camera, Microphone, or Screen & System Audio Recording, called Screen Recording on older macOS versions).
  2. Turn on the app that launches Python, for example Terminal, iTerm or your code editor.
  3. Quit and reopen that app, then start the recorder again.

Restarting the launching app matters most for **Screen Recording**: macOS only applies it to apps that are started afterwards, and without it the screen capture does not fail, it silently records only the desktop wallpaper. That is why the app blocks recording instead of letting you find out in the video.

A permission that macOS has not asked about yet is not reported as missing: macOS shows its normal prompt the first time the device is used. If the status cannot be read on your macOS version, the app does not block recording, and ffmpeg reports the problem itself with the **Error** status and its message.

### Permission troubleshooting

- **A Permissions note appears under the Record button.** Click **Open Privacy Settings**, turn on the app that launches Python for the permission named in the note, then quit and reopen that app. The note disappears the next time the window is checked.
- **I turned the permission on but the note is still there.** macOS only applies a new permission to apps that are started afterwards. Quit and reopen Terminal, iTerm or your editor, then start the recorder again.
- **The app I need is not in the list, or the switch cannot be changed.** Start a recording once so macOS can list the app, or add it with the **+** button. If the switch is locked, your Mac may be managed by an organization that restricts the permission.
- **The screen video shows only the wallpaper.** Screen Recording is off for the app that launches Python. Turn it on and restart that app (see above).
- **Recording fails to start with a message from ffmpeg.** Check the Camera and Microphone permissions for the launching app; if the status could not be read, the app lets ffmpeg report the problem.

## Error messages

When something goes wrong, the **Error** status shows a bold sentence saying what went wrong, followed by what to do about it. Raw ffmpeg output is only added at the end, as detail. The wording lives in `recorder/errors.py`, so the same problem always gets the same message.

| Problem | Message shown | What to do |
|---------|---------------|------------|
| ffmpeg is not installed | "ffmpeg was not found. Install it with: brew install ffmpeg" | Run `brew install ffmpeg`, then click **Record** (or **Refresh**) again. |
| BlackHole 2ch is missing | "BlackHole 2ch was not found, so system audio cannot be captured. Install it with: brew install --cask blackhole-2ch (then restart your Mac if it does not show up as an audio device)." | Install BlackHole and restart your Mac. See [Set up system audio](#set-up-system-audio-multi-output-device). |
| A camera, microphone or screen is not found | "The camera \"Name\" was not found. Connect it, make sure no other app has claimed it, then click Refresh in the Devices section or choose another one." followed by a reminder to check the matching permission | Connect the device, click **Refresh** and pick a device (or **Auto-detect**) in the Devices section. Check the permission in [macOS permissions](#macos-permissions). |
| A device exists but cannot be opened | "ffmpeg could not open the camera or microphone." (or the screen or system audio device) with the steps to check permissions and other apps | Turn on the permission for the app that launches Python and restart that app. Close other apps that use the device. |
| The device is used by another app | "The camera or microphone is being used by another app. Close the other app (a video call, for example) and try again." | Close the other app and click **Record** again. |
| The device does not support the recording settings | "The camera or microphone does not support the recording settings (30 fps). Choose a different one in the Devices section." | Pick another camera or screen in the Devices section. |
| Low disk space before recording | "Low disk space: only 512 MB free where recordings are saved (recordings), and at least 1024 MB is needed to record. Free up some space (empty the Trash or delete files you no longer need) and try again." | Free up space, then click **Record**. Nothing was recorded. |
| The disk fills up during recording or compositing | "The disk is full, so the recording could not be written. Free up some space (empty the Trash or delete files you no longer need) and record again." | Free up space. Everything recorded before the disk filled up may still be playable, and `camera.mp4` and `screen.mp4` are never deleted by the app. If only `final.mp4` failed, create it again with `recorder.recomposite`. |
| The recordings folder cannot be written | "The recordings folder cannot be written to. Check that the folder exists and that you have permission to save files there, or run the app from a different folder." | Run the app from a folder you can write to. |

A problem the app does not recognise is shown with its own description and the last lines of ffmpeg's log, so it is never hidden behind a generic message. Messages from the sound output check and the permission check are described in [Sound output check](#sound-output-check) and [Permission check](#permission-check).

## Where recordings are saved

Each recording gets its own timestamped folder inside `recordings/`, created in the folder you run the app from:

```
recordings/2026-10-21_14-46/
  camera.mp4    presenter: webcam + microphone
  screen.mp4    screen + system audio (BlackHole)
  final.mp4     screen with the presenter overlay, mic + system audio mixed
  sync.json     audio/video sync: measured launch gap and the camera offset (see Audio/video sync)
```

In `final.mp4` the presenter is scaled to about 320 px wide and placed in the bottom-right corner with a 20 px margin. `final.mp4` is written to a temporary file first and only renamed when ffmpeg succeeds, so a failed run never leaves a broken file. If compositing fails, the app shows the **Error** status, and `camera.mp4` and `screen.mp4` are still saved.

If you start two recordings within the same minute, the second folder gets a `-2` suffix, so an earlier recording is never overwritten. The app refuses to start if less than 1 GB of disk space is free.

`sync.json` is a small text file the app writes when a recording stops cleanly. It holds the measured start gap between the two captures and the fine-alignment offset used for `final.mp4` (see [Audio/video sync](#audiovideo-sync)).

When a recording finishes, the **Done** status shows the folder it was saved to.

## Reliable file output

Stopping always tries to leave playable MP4 files behind, even when something goes wrong:

- **Clean stop.** On Stop, the app sends `q` to both ffmpeg processes. ffmpeg then flushes its buffers and finishes the files properly. If a process has not exited after 20 seconds, it is terminated, and then force-killed if needed.
- **Crash-resilient MP4s.** `camera.mp4` and `screen.mp4` are written as fragmented MP4 (a new playable fragment about every 2 seconds). If ffmpeg is force-closed, or the app or the Mac crashes during a recording, everything recorded up to the last fragment stays playable instead of the file being left without its index.
- **Verification after stop.** Before reporting success, the app checks that both files exist, are not empty, and can be opened by ffmpeg. If a file is missing or unreadable, the **Error** status explains which one, and `final.mp4` is not created from it.
- **Safe closing.** If you close the window while starting, recording or processing, the app asks for confirmation. If you confirm, it stops the captures cleanly and waits for the files to finish saving (a few seconds, with the window still responsive) before quitting. If you close the window while the captures are still starting, they are stopped as soon as they are up, so no ffmpeg process is left running. `camera.mp4` and `screen.mp4` are kept, but `final.mp4` is not created on quit; create it later with `recorder.recomposite` (see below).

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
- `--camera-offset 0.35` fine-aligns the presenter against the screen, in seconds (see Audio/video sync). It is saved to `sync.json`; when you leave it out, the offset already saved there is used

The new file is written to a temporary file first and renamed only when ffmpeg succeeds, so a failed run never damages an existing `final.mp4`.

## Audio/video sync

The presenter (`camera.mp4`) and the screen (`screen.mp4`) are recorded by two separate ffmpeg processes, so they never start at exactly the same instant.

- **Back-to-back start.** Both commands are fully built first, and the two processes are then launched one right after the other with nothing in between, so they start within a fraction of a second of each other.
- **Launch gap.** The app times each launch and, after a clean stop, saves the difference to `sync.json` as `launch_gap_seconds` (positive means the screen process was launched after the camera process). It is for information and troubleshooting only and is not applied automatically, because the time ffmpeg needs to open a camera or screen varies from one recording to the next.
- **Camera offset.** `camera_offset_seconds` in `sync.json` is the correction applied when `final.mp4` is made. It starts at `0`, so nothing is shifted until you set it. It moves the presenter's video and microphone together, relative to the screen and system audio. **Positive** values delay the presenter (they appear later), **negative** values make the presenter earlier.

`sync.json` looks like this:

```json
{
  "launch_gap_seconds": 0.0312,
  "camera_offset_seconds": 0.0
}
```

If `sync.json` is missing or damaged, the offset is treated as `0`, so it can never stop a recording from being combined.

### Measuring an offset with a clap marker

If the presenter looks out of step with what is happening on screen, measure the gap with a clap:

1. Start recording and, in view of the camera, clap your hands once at the very moment something visible and audible happens on screen (for example a click sound with a flash, a metronome or a test video with a beep). Do this near the start, and again near the end for a long recording.
2. Stop the recording and open `camera.mp4` and `screen.mp4` in a video player or editor that shows exact times and lets you step frame by frame (QuickTime Player, VLC, iMovie, DaVinci Resolve and similar). A waveform view makes the clap easy to spot.
3. In `camera.mp4`, note the time of the clap (the frame where your hands meet, or the spike in the audio). In `screen.mp4`, note the time of the matching event (the flash or the beep).
4. Subtract: **offset = screen time - camera time**. For example, the clap is at 4.20 s in `camera.mp4` and the event at 3.85 s in `screen.mp4`, so the offset is -0.35 (the presenter has to be moved 0.35 s earlier).

### Applying the offset

Re-create the final video with the offset:

```bash
python3 -m recorder.recomposite recordings/2026-10-21_14-46 --camera-offset -0.35
```

The offset is applied to the new `final.mp4` and saved to the session's `sync.json`. Later runs of `recorder.recomposite` for that session reuse the saved offset unless you pass a different `--camera-offset`, and the app itself uses it whenever it composites that session. The raw files are never modified, so you can try different values until the result looks right. Offsets must be between -30 and 30 seconds.

### Sync troubleshooting

- **The presenter's lips move before the sound they make (or after it).** The microphone and camera are recorded together in `camera.mp4`, so they normally stay in step with each other. If they do not, use the clap method above on `camera.mp4` alone and check your camera and microphone settings.
- **The presenter is late compared to the screen.** Use a negative `--camera-offset`. If the presenter is early, use a positive one.
- **The gap is different at the start and at the end.** That is drift, not a fixed offset, and one `--camera-offset` value corrects only a constant gap. Pick a value that suits the part of the video that matters most. To reduce drift in the system audio, tick **Drift Correction** for BlackHole 2ch in the Multi-Output Device (see System audio troubleshooting).
- **The offset is different every recording.** The time ffmpeg needs to open the camera and screen varies, so measure again for each recording that needs it.

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

A small window opens with a status indicator, one button and a **Devices** section for choosing the camera, microphone and screen (all on **Auto-detect** by default; see [Choosing devices](#choosing-devices)). Closing the window during a recording asks for confirmation and saves the raw files before quitting.

## How to use

1. Click **Record** to start a recording. The status briefly shows **Starting...** while the devices are set up, then the button changes to **Stop**.
2. Click **Stop** to finish. The app finalizes the two raw files and creates `final.mp4` while the button is disabled. Long recordings take longer to combine.
3. When processing finishes, the status shows **Done** and the button returns to **Record** so you can start again.

## Status indicators

| Status | Color | Meaning | Button |
|--------|-------|---------|--------|
| Idle - ready to record | Gray | Nothing is running; ready for a new recording. | **Record** (enabled) |
| Starting... | Orange | **Record** was clicked and the app is checking the sound output, finding the devices and launching the captures. Clicks are ignored. | **Starting...** (disabled) |
| Recording... | Red | A recording is in progress. | **Stop** (enabled) |
| Processing... | Orange | Recording has stopped and the files are being finalized and combined into `final.mp4`. Clicks are ignored. | **Processing...** (disabled) |
| Done - recording saved | Green | The last recording finished successfully. | **Record** (enabled) |
| Error - something went wrong | Dark red | Starting, stopping, or processing failed. A detail message is shown under the status. | **Record** (enabled) |

## Project layout

```
main.py                  Entry point: creates the controller and window
recorder/
  state.py               Recording states (idle, starting, recording, processing, done, error) and their label/color/button styles
  controller.py          Record/Stop state machine; runs start-up, stop and compositing on background threads; lists and saves device choices; notifies the UI of changes
  devices.py             Finds the camera, microphone, screen and BlackHole devices; auto-picks real devices and honours chosen names
  device_settings.py     Loads and saves the Devices dropdown choices (devices.json in Application Support)
  encoding.py            Chooses the video encoder: h264_videotoolbox hardware encoding, or libx264 if unavailable
  audio_output.py        Detects the current sound output (Multi-Output Device, BlackHole only, or plain output)
  permissions.py         Detects missing Camera, Microphone and Screen Recording access (ctypes, no extra packages), builds the fix instructions and opens the matching privacy pane
  errors.py              Friendly error messages (ffmpeg missing, BlackHole missing, device not found, low or full disk) and the translation of raw ffmpeg log text and system errors into them
  capture.py             Starts and stops the two ffmpeg captures; writes fragmented MP4s and verifies them after stop
  session.py             Creates the timestamped session folder
  sync.py                Reads and writes a session's sync.json (launch gap and camera offset)
  compositor.py          Builds final.mp4: PiP overlay and mixed audio via ffmpeg, with an optional camera offset
  recomposite.py         Command-line tool to re-composite an existing session folder (optional --camera-offset)
ui/
  main_window.py         Tkinter window: status indicator, Record/Stop button, Permissions note with Open Privacy Settings button, Devices dropdowns, safe close handling that keeps the window responsive
docs/
  screencapturekit-evaluation.md   Evaluation of ScreenCaptureKit as a driver-free alternative to BlackHole
requirements.txt         Dependencies (none required yet)
```

## How it works

- `RecorderController.toggle()` is the single entry point for the button. It starts a recording from Idle, Done, or Error, and stops it from Recording. It only changes the state and starts a background thread, so it returns immediately; clicks during Starting or Processing are ignored.
- Starting, stopping and processing each run in a background thread, so the window never freezes while devices are detected, ffmpeg launches, or ffmpeg flushes and combines the files.
- `RecorderController.shutdown()` is called when the window is closed. It stops any running capture cleanly and waits for the files to be finalized before the app exits. It does not create `final.mp4`. The window runs it in a background thread and keeps updating while it waits, then closes. If it is called while the captures are still starting, the start-up thread stops them as soon as they are up.
- The controller notifies the window of every state change, and the window updates the indicator and button accordingly.
- On Record, the controller enters the Starting state and a background thread runs `_start_capture`, which first checks the sound output (see Sound output check), then detects the devices (using your saved choices where those devices are connected, see Choosing devices), creates the session folder and launches the camera and screen ffmpeg processes back to back (see How capture works). The state then changes to Recording. On Stop, `_stop_capture` asks both to finish so the MP4 files are finalized cleanly, and then checks that each file can be opened before processing continues.
- Before anything else, `_start_capture` checks the Camera, Microphone and Screen Recording permissions through `recorder/permissions.py` and fails with the exact fix steps if one is turned off. The window runs the same check in a background thread at startup, when it regains focus and after each recording, and shows the **Permissions** note with an **Open Privacy Settings** button while something is missing (see Permission check).
- Any device, session, capture or compositing failure (and any unexpected exception) goes through `recorder/errors.py` before it is shown as the **Error** status: known problems such as a missing device, a busy device or a full disk are recognised in ffmpeg's log and explained with a fix, and the window shows the first sentence as a heading with the fix steps below it (see Error messages).
- Both the captures and the final composite get their video encoder arguments from `recorder/encoding.py`, which prefers hardware encoding and falls back to `libx264` (see Low CPU use).
- After Stop, `_process` runs in the background thread and calls `compositor.composite()`, which runs ffmpeg with an overlay filter (presenter scaled to about 320 px, 20 px from the bottom-right corner) and mixes the microphone from `camera.mp4` with the system audio from `screen.mp4`. The raw files are never modified.
- The two captures are launched back to back and the measured launch gap is saved to `sync.json` after a clean stop. When compositing, the controller passes the session's saved `camera_offset_seconds` to the compositor, which shifts the presenter's video and microphone before the overlay and mix (see Audio/video sync).