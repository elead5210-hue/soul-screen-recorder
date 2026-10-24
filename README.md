# Soul Screen Recorder

A macOS app (Python) that records the screen, the presenter's camera, the microphone and the system audio as four separate streams, then combines them into one video with the presenter in a picture-in-picture (bottom right by default; the size and corner can be changed in [Settings](#settings)).

> **Current status (v1):** the window, the single Record/Stop button, the status indicator and the four ffmpeg captures are implemented. Record starts the camera, screen, microphone and system-audio captures; Stop finalizes `camera.mp4`, `screen.mp4`, `mic.wav` and `system.wav` in a timestamped folder and then automatically combines them into `final.mp4`: the screen as the main video, the presenter in a small bottom-right overlay, and the microphone and system audio as two separate, selectable audio tracks (they are not mixed).

## Quick start

Setup is five steps, in this order. Each step links to the section with the details:

1. Install **ffmpeg** and **BlackHole 2ch** with Homebrew: [Install ffmpeg and BlackHole](#install-ffmpeg-and-blackhole).
2. Get the code and install the **Python dependencies**: [Install](#install) and [Python dependencies](#python-dependencies).
3. Create a **Multi-Output Device** in Audio MIDI Setup so system audio is recorded and you can still hear it: [Set up system audio](#set-up-system-audio-multi-output-device).
4. Allow **Camera**, **Microphone** and **Screen Recording** for the app that launches Python: [macOS permissions](#macos-permissions).
5. Start the app with `./run.sh` and click **Record**: [Run](#run) and [How to use](#how-to-use).

Steps 2 and 5 are one command: `./run.sh` creates the virtual environment on the first run, installs the Python dependencies, checks that Tkinter and ffmpeg are present and starts the app. Do steps 1, 3 and 4 once; after that, `./run.sh` is all you need.

Prefer an app you can double-click? See [Packaged app (optional)](#packaged-app-optional).

## Requirements

- macOS 13 (Ventura) or newer, on an Apple Silicon or an Intel Mac (see [Compatibility](#compatibility))
- Python 3.9 or newer with Tkinter (Tk 8.6 or newer; the Python that ships with macOS is too old, see [Compatibility](#compatibility))
- No Python packages are needed for the current version
- `ffmpeg` (external dependency, installed with Homebrew)
- The BlackHole 2ch audio driver, for system audio capture

Tkinter is included with the python.org installer. If you use Homebrew Python, install it with:

```bash
brew install python-tk
```

## Compatibility

| | Supported |
|---|-----------|
| **macOS** | macOS 13 (Ventura) or newer. macOS 26 (Tahoe) is the newest version the app is tested on; newer releases are expected to work. |
| **Mac** | Apple Silicon (M1 and later) and Intel Macs |
| **Python** | 3.9 or newer, with Tkinter on Tk 8.6 or newer |
| **Packaged app** | Same macOS minimum; see [What the packaged app runs on](#what-the-packaged-app-runs-on) for the processors |

The supported platform is defined in one place, `recorder/compat.py`. The startup check, `./run.sh`, the packaged app's `Info.plist` and `python3 -m recorder.compat` all use it, so they always agree.

### Apple Silicon and Intel

The app itself is plain Python and `ffmpeg` with VideoToolbox hardware encoding (see [Low CPU use](#low-cpu-use)), so it runs the same way on both kinds of Mac. The only difference is where Homebrew installs things:

| Mac | Homebrew folder | ffmpeg |
|-----|-----------------|--------|
| Apple Silicon | `/opt/homebrew` | `/opt/homebrew/bin/ffmpeg` |
| Intel | `/usr/local` | `/usr/local/bin/ffmpeg` |

The app looks for ffmpeg on your `PATH` and in both folders, and `./run.sh` prints the install hints that match your Mac.

An Intel build of Python on an Apple Silicon Mac runs through Rosetta. That works, but it uses more CPU than a native build, so the app reports it as a note (never as a problem that stops you). To get a native Python, install it with Homebrew (`brew install python python-tk`, which lives in `/opt/homebrew` on Apple Silicon), delete the old `venv/` folder (`rm -rf venv`) and run `./run.sh` again. If Terminal itself runs under Rosetta, select it in Finder, choose File > Get Info and untick **Open using Rosetta**.

### Python and Tk

The window needs Tk 8.6 or newer. The Python that comes with macOS (`/usr/bin/python3`) uses Tk 8.5, which draws blank or broken windows on current macOS. Use a Python from Homebrew (`brew install python python-tk`) or from python.org, which both include Tk 8.6.

### What the startup check reports

The app checks the platform before the window opens (`./run.sh` runs the same checks before starting Python). Anything that cannot be read, for example the macOS version on an unusual setup, is treated as unknown and never stops you.

| Finding | What happens |
|---------|--------------|
| macOS older than 13 | A warning dialog explains the problem and how to update. You can quit, or choose to open the app anyway. If you do, clicking **Record** shows the same message instead of recording. |
| Tk older than 8.6 | A warning dialog explains that the window may be drawn blank or broken and how to install a newer Python. You can quit or open the app anyway. |
| Intel Python on an Apple Silicon Mac (Rosetta) | No dialog. `./run.sh` and `python3 -m recorder.compat` print a note with the steps for a native Python. |
| macOS newer than the versions tested | No dialog. `python3 -m recorder.compat` prints a note; nothing needs to be done unless something goes wrong. |
| The macOS version cannot be determined | No dialog. The app carries on, and ffmpeg or macOS report any real problem. |

To see the report for your Mac at any time, run this from the project folder:

```bash
python3 -m recorder.compat
```

It prints a one-line summary and any problems with the steps to fix them, and exits with status 0 unless a problem rules your setup out:

```
macOS 14.5 (Sonoma), Apple Silicon, Tk 8.6
This computer meets the requirements.
```

### What the packaged app runs on

The packaged app declares macOS 13.0 as its minimum (`LSMinimumSystemVersion`, taken from `recorder/compat.py`). Which processors it runs on depends on the Python it is built with, because py2app copies that Python into the app:

| Python used to build | The app runs on |
|----------------------|-----------------|
| universal2 (for example the python.org installer) | Apple Silicon and Intel Macs |
| arm64 (for example Homebrew on Apple Silicon) | Apple Silicon Macs only |
| x86_64 (for example Homebrew in `/usr/local`) | Intel Macs, and Apple Silicon Macs through Rosetta |

`./build_app.sh` detects this and prints which Macs the app will run on, with a warning when it is Apple Silicon-only or Intel-only. To share the app with both kinds of Mac, build it with the universal2 Python from python.org.

### Compatibility troubleshooting

- **A dialog says macOS is too old.** Update in System Settings > General > Software Update (on macOS 12 and older: Apple menu > System Preferences > Software Update). If no update to macOS 13 or newer is offered, this Mac is too old to record with this app.
- **A dialog or `./run.sh` says Tk is too old, or the window is blank.** You are using the Python that comes with macOS. Install a newer one with `brew install python python-tk`, open a new Terminal window, delete the `venv/` folder (`rm -rf venv`) and run `./run.sh` again.
- **The packaged app does not open on an Intel Mac.** It was built with an arm64-only Python. Build it again with the universal2 Python from python.org (see above).
- **Everything is slow on an Apple Silicon Mac.** Check `python3 -m recorder.compat`: if it says Intel Python under Rosetta, switch to a native Python (see above).

The checks are covered by `tests/test_compat.py`, which needs no Mac (see [Unit tests](#unit-tests)).

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
- **Four ffmpeg processes.** Each stream is recorded by its own ffmpeg process, so a problem with one device is reported for that stream by name. The four are started back to back, so the recordings begin within a fraction of a second of each other.

  | Process | avfoundation input | Output |
  |---------|--------------------|--------|
  | Presenter | webcam (video only) | `camera.mp4` |
  | Screen | screen with cursor (video only) | `screen.mp4` |
  | Microphone | microphone (audio only) | `mic.wav` |
  | System audio | BlackHole 2ch (audio only) | `system.wav` |

  The two video files record at 30 fps and are encoded with `h264_videotoolbox` (hardware encoding, see Low CPU use). The two audio files are uncompressed 48 kHz 16-bit WAV, flushed to disk as they are recorded.
- **Control.** ffmpeg runs in the background with its standard input connected to the app. To stop, the app writes `q` to that input (see Reliable file output).
- **Log output.** ffmpeg's own log output is not shown in the terminal. It is collected in a temporary file for each process and discarded when the capture ends. If a capture fails to start or to stop cleanly, the app reads that log, explains the problem in plain words (see [Error messages](#error-messages)) and adds the last few lines of the log as detail in the **Error** message under the status.

## Low CPU use

Recording two streams at once, and combining them afterwards, stays light on the CPU because the video is encoded by the Mac's hardware encoder instead of by the CPU:

- **Capture.** Both live captures (`camera.mp4` and `screen.mp4`) use `h264_videotoolbox`.
- **Compositing.** The `final.mp4` encode uses the same hardware encoder, so combining a long recording does not max out the CPU either.
- **One place chooses the encoder.** `recorder/encoding.py` checks once per ffmpeg binary (with `ffmpeg -encoders`) that `h264_videotoolbox` is available, and both capture and compositing take their video encoder arguments from it.
- **Fallback.** Some ffmpeg builds that are not from Homebrew are built without VideoToolbox. In that case the app automatically uses the software encoder `libx264` with the `veryfast` preset, so recording still works, just with higher CPU use. If the check itself cannot run, the app assumes hardware encoding, which is what the standard Homebrew ffmpeg provides.

To check CPU use, open **Activity Monitor** (Applications > Utilities), select the **CPU** tab, and watch the four `ffmpeg` processes while recording. With hardware encoding the two video processes should each use only a small share of one core, and the two audio processes almost nothing. If they use much more, run `ffmpeg -hide_banner -encoders | grep videotoolbox`: if nothing is listed, your ffmpeg has no VideoToolbox support, so reinstall it with `brew install ffmpeg`.

## Responsive interface

The window never freezes. Everything slow runs on a background thread, and the window only draws the current status:

- **Starting.** Clicking **Record** returns immediately and the status changes to **Starting...**. The sound output check, device detection, session folder creation, ffmpeg launch and the short check that all four captures came up all happen in the background. When they finish, the status changes to **Recording...** (or to **Error** with a message if something failed).
- **Stopping and compositing.** Clicking **Stop** switches to **Processing...** at once. Finalizing the four raw files and creating `final.mp4` run in a background thread, so even a long recording that takes a while to combine does not block the window.
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

## Settings

The **Settings** section of the window (under **Devices**) lets you change how recordings look and where they are saved. Every change is saved as soon as you make it and is used from the next recording on. Nothing needs to be edited in code.

| Setting | Choices | Default |
|---------|---------|---------|
| **Presenter size** | Small (240 px), Medium (320 px), Large (480 px), Extra large (640 px): the width of the presenter overlay in `final.mp4` | Medium (320 px) |
| **Presenter corner** | Bottom right, bottom left, top right, top left | Bottom right |
| **Video quality** | Low (smaller files), Medium, High (larger files) | Medium |
| **Save recordings in** | Any folder you choose with **Browse...**; **Use default** goes back to the `recordings/` folder | `recordings/` in the folder you run the app from (`~/Movies/Soul Screen Recorder` in the packaged app) |

### Video quality

The quality preset sets the video bitrate of both captures and of `final.mp4`. Audio is not affected.

| Preset | Screen and `final.mp4` | Camera |
|--------|------------------------|--------|
| Low | 3 Mbit/s | 2 Mbit/s |
| Medium | 8 Mbit/s | 4 Mbit/s |
| High | 16 Mbit/s | 8 Mbit/s |

Higher quality means sharper video (especially small text on screen) but larger files and more disk space; Medium matches what earlier versions of the app always used. Hardware encoding is still used for every preset (see Low CPU use).

### Output folder

Each recording still gets its own timestamped folder, now inside the folder you chose (for example `~/Movies/Recordings/2026-10-21_14-46/`). The free-space check and the other folder errors apply to that folder. If the folder you chose cannot be created or written to, recording does not start and the **Error** status says so; choose another folder or click **Use default**.

### When settings can be changed

The Settings controls are disabled while the app is starting, recording or processing, so a recording can never change halfway through. They become active again when the status returns to Idle, Done or Error.

### Where your settings are saved

Settings are remembered between runs in a small JSON file next to the device choices, not in the project folder:

```
~/Library/Application Support/Soul Screen Recorder/settings.json
```

A missing or damaged file, or a value that is not valid, simply means the default for that setting, so it can never stop a recording from starting. To reset everything, delete that file.

### Settings troubleshooting

- **"Could not save your settings".** The settings folder could not be written. Check that `~/Library/Application Support` is writable; recording still works with the values shown.
- **The Settings controls are greyed out.** The app is starting, recording or processing. Wait for the status to return to Idle or Done.
- **I changed the presenter size or corner but my last video did not change.** Settings apply to the next recording. To change an existing recording, run `recorder.recomposite` (see below); it uses your saved settings unless you pass `--pip-width`, `--pip-position` or `--quality`.

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
| The disk fills up during recording or compositing | "The disk is full, so the recording could not be written. Free up some space (empty the Trash or delete files you no longer need) and record again." | Free up space. Everything recorded before the disk filled up may still be playable, and the four raw files (`camera.mp4`, `screen.mp4`, `mic.wav` and `system.wav`) are never deleted by the app. If only `final.mp4` failed, create it again with `recorder.recomposite`. |
| The recordings folder cannot be written | "The recordings folder cannot be written to. Check that the folder exists and that you have permission to save files there, or run the app from a different folder." | Run the app from a folder you can write to. |

A problem the app does not recognise is shown with its own description and the last lines of ffmpeg's log, so it is never hidden behind a generic message. Messages from the sound output check and the permission check are described in [Sound output check](#sound-output-check) and [Permission check](#permission-check).

## Where recordings are saved

Each recording gets its own timestamped folder inside the output folder. By default that is `recordings/`, created in the folder you run the app from (in the packaged app it is `~/Movies/Soul Screen Recorder`); you can choose another folder in [Settings](#settings):

```
recordings/2026-10-21_14-46/
  camera.mp4    presenter: webcam video only
  screen.mp4    screen video only
  mic.wav       microphone audio only
  system.wav    system audio only (BlackHole)
  final.mp4     screen with the presenter overlay, plus two audio tracks: Microphone and System audio
  sync.json     sync data: measured launch times and the camera, microphone and system-audio offsets (see Audio/video sync)
```

In `final.mp4` the presenter is scaled to the width chosen in Settings (about 320 px by default) and placed in the chosen corner (bottom right by default) with a 20 px margin. The microphone and the system audio are **not mixed**: `final.mp4` has two separate AAC audio tracks, titled **Microphone** (track 1, played by default) and **System audio** (track 2), so each can be selected or levelled on its own. Most players play one audio track at a time, so use the player's audio-track menu (in VLC: Audio > Audio Track) to switch, or an editor that plays all tracks. `final.mp4` is written to a temporary file first and only renamed when ffmpeg succeeds, so a failed run never leaves a broken file. If compositing fails, the app shows the **Error** status, and the four raw files are still saved.

If you start two recordings within the same minute, the second folder gets a `-2` suffix, so an earlier recording is never overwritten. The app refuses to start if less than 1 GB of disk space is free.

`sync.json` is a small text file the app writes when a recording stops cleanly. It holds the measured launch time of each of the four captures and the fine-alignment offsets (camera, microphone and system audio, each relative to the screen) used for `final.mp4` (see [Audio/video sync](#audiovideo-sync)). A session recorded by an older version of the app, with only `camera.mp4` and `screen.mp4`, still has a loadable `sync.json`, but it has no `mic.wav` or `system.wav`, so it cannot be re-composited.

When a recording finishes, the **Done** status shows the folder it was saved to. **Done** is only shown when all five files passed the playable check (see [Acceptance test](#acceptance-test-five-playable-files)).

## Reliable file output

Stopping always tries to leave playable MP4 files behind, even when something goes wrong:

- **Clean stop.** On Stop, the app sends `q` to all four ffmpeg processes. ffmpeg then flushes its buffers and finishes the files properly. If a process has not exited after 20 seconds, it is terminated, and then force-killed if needed.
- **Crash-resilient files.** `camera.mp4` and `screen.mp4` are written as fragmented MP4 (a new playable fragment about every 2 seconds). If ffmpeg is force-closed, or the app or the Mac crashes during a recording, everything recorded up to the last fragment stays playable instead of the file being left without its index. `mic.wav` and `system.wav` are written as WAV files that are flushed to disk as the sound arrives, so the sound captured so far is kept too (the file's length header is finalized on a clean stop).
- **Verification after stop.** Before reporting success, the app checks that all four raw files exist, are not empty, and can be opened by ffmpeg with the right kind of stream (video in the MP4 files, audio in the WAV files). If a file is missing or unreadable, the **Error** status explains which one, and `final.mp4` is not created from it.
- **Verification of the final video.** After compositing, the app opens `final.mp4` and decodes its first video frame too. If that fails, the **Error** status says the final video cannot be played, the four raw files are kept, and you can create it again with `recorder.recomposite`. The **Done** status is therefore only shown when all five files are playable.
- **Safe closing.** If you close the window while starting, recording or processing, the app asks for confirmation. If you confirm, it stops the captures cleanly and waits for the files to finish saving (a few seconds, with the window still responsive) before quitting. If you close the window while the captures are still starting, they are stopped as soon as they are up, so no ffmpeg process is left running. the four raw files are kept, but `final.mp4` is not created on quit; create it later with `recorder.recomposite` (see below).

Quitting the app in other ways, such as force-quitting or pressing Ctrl+C in the terminal, cannot stop ffmpeg cleanly. The fragmented format means the recording up to that moment should still be playable.

## Raw files are kept

Every session folder keeps all five files: `camera.mp4`, `screen.mp4`, `mic.wav`, `system.wav` and `final.mp4`. The four raw files (`camera.mp4`, `screen.mp4`, `mic.wav` and `system.wav`) are never modified, deleted or overwritten by the app, including when compositing fails, so you can always create the final video again.

### Re-compositing a session

To rebuild the picture-in-picture video from the raw files of an existing session, run this from the project folder:

```bash
python3 -m recorder.recomposite recordings/2026-10-21_14-46
```

By default this replaces `final.mp4` in that folder. Options:

- `--pip-width 480` sets the overlay width in pixels (default: the size saved in Settings, 320 px if none)
- `--pip-position top-left` sets the overlay corner: `bottom-right`, `bottom-left`, `top-right` or `top-left` (default: the corner saved in Settings)
- `--quality high` sets the video quality preset: `low`, `medium` or `high` (default: the quality saved in Settings)
- `--margin 30` sets the distance from the chosen corner in pixels (default 20)
- `--output final_large_pip.mp4` writes a different file name inside the session folder and keeps the existing `final.mp4`
- `--camera-offset 0.35` fine-aligns the presenter's video against the screen, in seconds (see Audio/video sync)
- `--mic-offset -0.12` fine-aligns the microphone (`mic.wav`) against the screen, in seconds
- `--system-offset 0.05` fine-aligns the system audio (`system.wav`) against the screen, in seconds

Each offset you give is saved to `sync.json` once the new video has been made; an offset you leave out uses the value already saved there (0 if none). Positive values delay that stream and negative values make it earlier. The screen is the reference and is never shifted.

All four raw files must be present: a session recorded by an older version of the app (only `camera.mp4` and `screen.mp4`) cannot be re-composited, and the tool says which file is missing. The tool refuses to write over any of the raw files, even with `--output`. The new file is written to a temporary file first and renamed only when ffmpeg succeeds, so a failed run never damages an existing `final.mp4`.

## Audio/video sync

The presenter (`camera.mp4`), the screen (`screen.mp4`), the microphone (`mic.wav`) and the system audio (`system.wav`) are recorded by four separate ffmpeg processes, so they never start at exactly the same instant.

- **Back-to-back start.** All four commands are fully built first, and the four processes are then launched one right after the other with nothing in between, so they start within a fraction of a second of each other.
- **Shared audio rate.** When `final.mp4` is made, both audio files are resampled to one shared rate with timestamp correction (`aresample` with `async`), so the microphone and system audio stay aligned over long recordings instead of drifting apart. They are then written as two separate tracks and never mixed.
- **Launch times.** The app times each launch and, after a clean stop, saves to `sync.json` how long after the first process each stream was launched (`launch_offsets_seconds`, with a value for `camera`, `screen`, `mic` and `system`; the first one launched is `0`). It also saves `launch_gap_seconds`, the older single number (positive means the screen process was launched after the camera process). These are for information and troubleshooting only and are not applied automatically, because the time ffmpeg needs to open a device varies from one recording to the next.
- **Per-stream offsets.** `camera_offset_seconds`, `mic_offset_seconds` and `system_offset_seconds` in `sync.json` are the corrections applied when `final.mp4` is made, each relative to the screen, which is the reference and is never shifted. They start at `0`, so nothing is shifted until you set them. The camera offset moves the presenter's video, the microphone offset moves `mic.wav` and the system offset moves `system.wav`. **Positive** values delay that stream (it appears or sounds later), **negative** values make it earlier.

`sync.json` looks like this:

```json
{
  "launch_gap_seconds": 0.0312,
  "launch_offsets_seconds": {
    "camera": 0.0,
    "screen": 0.0312,
    "mic": 0.0655,
    "system": 0.0701
  },
  "camera_offset_seconds": 0.0,
  "mic_offset_seconds": 0.0,
  "system_offset_seconds": 0.0
}
```

If `sync.json` is missing or damaged, the offsets are treated as `0`, so it can never stop a recording from being combined. A `sync.json` saved by the older two-file version has only `camera_offset_seconds`, which also covered the microphone (it was recorded inside `camera.mp4`); when such a file is loaded, the microphone offset takes the same value, so the alignment it described is kept.

### Measuring an offset with a clap marker

If the presenter looks out of step with what is happening on screen, measure the gap with a clap:

1. Start recording and, in view of the camera, clap your hands once at the very moment something visible and audible happens on screen (for example a click sound with a flash, a metronome or a test video with a beep). Do this near the start, and again near the end for a long recording.
2. Stop the recording and open the raw files in a video editor that shows exact times, lets you step frame by frame and shows audio waveforms (DaVinci Resolve, iMovie and similar). Put `screen.mp4`, `camera.mp4`, `mic.wav` and `system.wav` on the timeline, all starting at 0.
3. Note the time of the clap in `camera.mp4` (the frame where your hands meet) and as a spike in `mic.wav`. Note the time of the matching event in `screen.mp4` (the flash) and as a spike in `system.wav` (the beep).
4. Subtract for each stream you want to align: **offset = screen time - stream time**. For example, the clap is at 4.20 s in `camera.mp4` and the event at 3.85 s in `screen.mp4`, so the camera offset is -0.35 (the presenter has to be moved 0.35 s earlier). If the clap spike is at 4.22 s in `mic.wav`, the microphone offset is 3.85 - 4.22 = -0.37. If the beep is at 3.90 s in `system.wav`, the system offset is 3.85 - 3.90 = -0.05.

### Applying the offset

Re-create the final video with the offsets you measured (give only the ones you need):

```bash
python3 -m recorder.recomposite recordings/2026-10-21_14-46 --camera-offset -0.35 --mic-offset -0.37 --system-offset -0.05
```

The offsets are applied to the new `final.mp4` and saved to the session's `sync.json`. Later runs of `recorder.recomposite` for that session reuse each saved offset unless you pass a different `--camera-offset`, `--mic-offset` or `--system-offset`, and the app itself uses it whenever it composites that session. The raw files are never modified, so you can try different values until the result looks right. Offsets must be between -30 and 30 seconds.

### Sync troubleshooting

- **The presenter's lips move before the sound they make (or after it).** The camera and the microphone are separate recordings, so they can be slightly out of step. Measure the clap in `camera.mp4` and in `mic.wav` and set `--camera-offset` and `--mic-offset` so that both line up with the screen (see the clap method above).
- **The system audio is early or late compared to what happens on screen.** Measure the beep in `system.wav` against the flash in `screen.mp4` and use `--system-offset`.
- **The presenter is late compared to the screen.** Use a negative `--camera-offset`. If the presenter is early, use a positive one.
- **The gap is different at the start and at the end.** That is drift, not a fixed offset, and one offset value per stream corrects only a constant gap. Pick a value that suits the part of the video that matters most. To reduce drift in the system audio, tick **Drift Correction** for BlackHole 2ch in the Multi-Output Device (see System audio troubleshooting).
- **The offset is different every recording.** The time ffmpeg needs to open the camera and screen varies, so measure again for each recording that needs it.

## Install

Get the code, then use the launcher, which does the rest of the setup for you:

```bash
git clone <your-repo-url> soul-screen-recorder
cd soul-screen-recorder
./run.sh
```

On its first run `./run.sh` creates the `venv/` virtual environment and installs `requirements.txt`. On later runs it only installs again when `requirements.txt` has changed. Before starting the app it also checks that:

- The Mac runs macOS 13 or newer. If not, it stops and explains how to update. It also detects Apple Silicon vs Intel, so the Homebrew hints point at the right folder (`/opt/homebrew` or `/usr/local`), and it prints a note when Python runs under Rosetta (see [Compatibility](#compatibility)).
- `python3` is version 3.9 or newer and has Tkinter on Tk 8.6 or newer. If not, it stops and suggests `brew install python python-tk`.
- `ffmpeg` is installed (on your `PATH`, or in `/opt/homebrew/bin` or `/usr/local/bin`). If not, it stops and suggests `brew install ffmpeg` and `brew install --cask blackhole-2ch`.

If your copy of the project lost the executable permission (for example after downloading it as a zip file), run `chmod +x run.sh` once, or start it with `bash run.sh`. You can run it from any folder, for example `~/soul-screen-recorder/run.sh`, because it first moves to the project folder itself.

To set everything up by hand instead:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Python dependencies

The app uses only the Python standard library (including Tkinter), so `requirements.txt` currently lists no packages and `pip install -r requirements.txt` finishes without installing anything. Keep that step in your setup anyway: it makes the command the same if a package is ever added. The tools that do the real work, `ffmpeg` and the BlackHole driver, are not Python packages and are installed with Homebrew (see [Install ffmpeg and BlackHole](#install-ffmpeg-and-blackhole)). If the app reports that Tkinter is missing, see [Requirements](#requirements).

## Run

```bash
./run.sh
```

This is the one-command way to run the app (see [Install](#install) for what it does the first time). If you set up the virtual environment by hand, `python3 main.py` starts the app too. Anything you add after `./run.sh` is passed on to `main.py`.

A small window opens with a status indicator, one button and a **Devices** section for choosing the camera, microphone and screen (all on **Auto-detect** by default; see [Choosing devices](#choosing-devices)) and a **Settings** section for the presenter size and corner, the output folder and the video quality (see [Settings](#settings)). Closing the window during a recording asks for confirmation and saves the raw files before quitting.

## Packaged app (optional)

Instead of starting the app from a terminal, you can build a normal macOS app, **Soul Screen Recorder.app**, that opens with a double-click. This is optional: `./run.sh` does everything the packaged app does.

### Build it

From the project folder, on a Mac:

```bash
./build_app.sh
```

The script checks for Python with Tkinter, reuses the `venv/` folder from `./run.sh`, installs the build tool (py2app, listed in `requirements-build.txt`, so `requirements.txt` still lists no packages), builds the app with `setup.py` and signs it (ad hoc, no developer account needed). The result is `dist/Soul Screen Recorder.app`. Building takes about a minute. If the script is not executable, run `chmod +x build_app.sh` or start it with `bash build_app.sh`.

If the build fails, the script shows the end of the log and keeps the full log in `build.log`. To build by hand instead:

```bash
pip install -r requirements-build.txt
python3 setup.py py2app
```

### Open it

Double-click the app in Finder, or run `open "dist/Soul Screen Recorder.app"`. You can drag it to **Applications** to keep it. Because it is not signed by an Apple developer account, macOS may say it is from an unidentified developer the first time: right-click the app, choose **Open**, then click **Open**.

The app does not contain ffmpeg or BlackHole. Install them as described in [Install ffmpeg and BlackHole](#install-ffmpeg-and-blackhole) and set up the Multi-Output Device in [Set up system audio](#set-up-system-audio-multi-output-device). Apps opened from Finder do not have Homebrew on their `PATH`, so the app also looks for ffmpeg in `/opt/homebrew/bin` and `/usr/local/bin` (see [How capture works](#how-capture-works)).

### Privacy usage descriptions

macOS only lets an app use the camera and microphone if the app says why. `setup.py` puts these descriptions in the app's `Info.plist`, and macOS shows them in its permission prompts:

| Key | Text shown |
|-----|------------|
| `NSCameraUsageDescription` | Soul Screen Recorder records your camera so you can appear as the presenter in the picture-in-picture video. |
| `NSMicrophoneUsageDescription` | Soul Screen Recorder records your microphone so your voice is included in the recording. |
| `NSScreenCaptureUsageDescription` | Soul Screen Recorder records your screen (and the system audio played through BlackHole) as the main video. |

The `Info.plist` also sets the bundle identifier (`com.soulscreenrecorder.app`) and the minimum macOS version (13.0, taken from `MIN_MACOS_TEXT` in `recorder/compat.py` so it always matches the check the source version does). To change the others, edit `setup.py` and build again.

### Permissions for the packaged app

The permissions belong to the app itself, not to Terminal or your code editor:

1. The first time you record, macOS asks for **Camera** and **Microphone** access. Click **Allow**.
2. For the screen, open **System Settings > Privacy & Security > Screen & System Audio Recording**, turn on **Soul Screen Recorder**, then quit and reopen the app. If it is not in the list, click **Record** once so macOS adds it, or add it with the **+** button.
3. The window's **Permissions** note and **Open Privacy Settings** button work as before (see [Permission check](#permission-check)); in the packaged app they refer to Soul Screen Recorder.

Your device choices and Settings are saved in the same files as when you run from source (see [Where your choice is saved](#where-your-choice-is-saved) and [Where your settings are saved](#where-your-settings-are-saved)), so both ways of starting the app share them.

### Packaged app troubleshooting

- **"Soul Screen Recorder cannot be opened" or "unidentified developer".** Right-click the app, choose **Open**, then click **Open** (see above).
- **The build fails.** Read the lines the script prints and `build.log`. Check that `python3 -c "import tkinter"` works (`brew install python-tk` for Homebrew Python), then run `./build_app.sh` again; it always starts from a clean `build/` and `dist/`.
- **macOS asks for permissions again after I rebuilt the app.** Each build is a new copy of the app. If a permission seems stuck, turn it off and on again for **Soul Screen Recorder** in System Settings > Privacy & Security, then reopen the app.
- **The screen video shows only the wallpaper.** Screen Recording is off for the app. Turn it on and reopen the app (see above).
- **Recordings are not where I expect.** Unless you chose a folder in **Settings**, the packaged app saves to `~/Movies/Soul Screen Recorder` (the `recordings/` folder of a source run is relative to where you start it, which for a packaged app would be inside the app). Choose another folder with **Browse...** if you prefer (see [Output folder](#output-folder)).
- **The app says ffmpeg was not found.** Install it with `brew install ffmpeg`. A rebuild is not needed.

## How to use

1. Click **Record** to start a recording. The status briefly shows **Starting...** while the devices are set up, then the button changes to **Stop**.
2. Click **Stop** to finish. The app finalizes the four raw files and creates `final.mp4` while the button is disabled. Long recordings take longer to combine.
3. When processing finishes, the status shows **Done** and the button returns to **Record** so you can start again.

## Acceptance test: five playable files

Clicking **Record** and then **Stop** must produce five playable files in a timestamped folder: the four raw recordings and `final.mp4`. To check this on your Mac:

1. Start the app (`./run.sh`, or open the packaged app) and make sure the status is **Idle**, a Multi-Output Device is selected as the sound output, and the permissions are on.
2. Click **Record**. Wait for **Recording...**, then talk for about 10 seconds and play some sound or a video so there is something to hear on the system audio.
3. Click **Stop** and wait until the status shows **Done**. The message under it names the session folder, for example `recordings/2026-10-21_14-46`.
4. Check the folder with the verification tool:

   ```bash
   python3 -m recorder.verify recordings/2026-10-21_14-46
   ```

   It prints one line per file and exits with status 0 only if all five pass:

   ```
   Session: recordings/2026-10-21_14-46
     [PASS] camera.mp4 is playable (0:12)
     [PASS] screen.mp4 is playable (0:12)
     [PASS] mic.wav is playable (0:12)
     [PASS] system.wav is playable (0:12)
     [PASS] final.mp4 is playable (0:12)
   All 5 files are playable.
   ```

5. Open the files in QuickTime Player or VLC to see and hear them yourself. The tool proves that each file opens and decodes; run it again with `--audio` to also measure the sound levels (see [Acceptance test: final video quality](#acceptance-test-final-video-quality)), and listen for your voice (in `mic.wav` and the **Microphone** track of `final.mp4`) and the system audio (in `system.wav` and the **System audio** track of `final.mp4`). In VLC, switch tracks with Audio > Audio Track.

### What the check does

For each of `camera.mp4`, `screen.mp4`, `mic.wav`, `system.wav` and `final.mp4`, `recorder/verify.py` checks that the file exists, is not empty, opens in ffmpeg, has the stream it should (video in the MP4 files, audio in the WAV files) and that its first video frame (or the first second of audio) decodes. It only reads the files and never changes them. A failed file gets a plain-words reason: missing, empty, cannot be opened and may be unplayable, no video (or audio) stream, or the file could not be decoded.

### What Done guarantees

- When you click **Stop**, the four raw files (`camera.mp4`, `screen.mp4`, `mic.wav` and `system.wav`) are checked before compositing starts (see [Reliable file output](#reliable-file-output)).
- After compositing, `final.mp4` is checked as well.
- The **Done** status is shown only when all of that succeeded, so **Done** always means five playable files in the timestamped folder. If anything fails, the **Error** status says which file and why, and the raw files are kept.

### Unit tests

The naming of the session folders and the verification (with a fake ffmpeg, so they run anywhere, also without a camera) are covered by tests that use only the Python standard library:

```bash
python3 -m unittest discover -s tests -v
```

They check that each session gets a timestamped folder (with `-2`, `-3` ... if two start in the same minute), that the packaged app uses `~/Movies/Soul Screen Recorder` by default, and that missing, empty, index-less, wrong-stream and undecodable files are all reported as failures. The four-file layout (the session paths, the video-only and WAV command builders, the launch offsets measured for the four captures, the two-track filter graph, the per-stream offsets in `sync.json` including an old two-file `sync.json`, and the `--mic-offset` and `--system-offset` flags) is covered by `tests/test_four_channel.py`.

### If the check fails

- **A raw file (`camera.mp4`, `screen.mp4`, `mic.wav` or `system.wav`) fails.** The capture did not finish cleanly. See [Reliable file output](#reliable-file-output) and [Error messages](#error-messages); the fragmented format usually keeps what was recorded.
- **Only `final.mp4` fails.** Create it again with `python3 -m recorder.recomposite <session folder>` and run the check again.
- **"ffmpeg was not found".** Install it with `brew install ffmpeg`.

## Acceptance test: final video quality

The final video must show the presenter in the bottom-right corner, with the microphone and the system audio both clearly audible, in sync and on two separate audio tracks. Record a test session as in [Acceptance test: five playable files](#acceptance-test-five-playable-files), talking and playing some sound while you record, then:

### Manual checklist

1. Play `final.mp4` in QuickTime Player or VLC.
2. **Layout.** The presenter sits in the bottom-right corner, about 320 px wide and 20 px from the edges of the video (or the size and corner chosen in [Settings](#settings)); the screen is the main video.
3. **Audio.** `final.mp4` has two audio tracks, **Microphone** (played by default) and **System audio**. Select each in turn (in VLC: Audio > Audio Track): your voice is clearly audible on the first and whatever the Mac was playing on the second.
4. **Sync (clap test).** Clap your hands once in view of the camera at the very moment something visible and audible happens on screen (for example a click sound with a flash), near the start and again near the end for a long recording. In `final.mp4` the clap and the screen event happen together (see [Measuring an offset with a clap marker](#measuring-an-offset-with-a-clap-marker)).

### What the verify tool reports about audio levels

Run the verification tool with the `--audio` option:

```bash
python3 -m recorder.verify recordings/2026-10-21_14-46 --audio
```

Besides the playability lines, `--audio` measures the sound in each file with ffmpeg's volumedetect filter (mean and peak level) and prints one audio line per measured file or track:

- `final.mp4 audio tracks` must report exactly **two separate audio tracks** (the microphone first, then the system audio); a missing track fails the check. Each track is then measured on its own, as `final.mp4 audio (microphone)` and `final.mp4 audio (system audio)`. A silent or quiet track is only a `[WARN]` (nothing may have been playing, or nobody may have spoken), but the check fails with `[FAIL] final.mp4 audio` if both tracks are silent.
- `mic.wav audio (microphone)` and `system.wav audio (system audio)` are reported as audible, quiet or silent. Silence there is only a `[WARN]`. `camera.mp4` and `screen.mp4` are video only, so they have no sound to measure.

For example:

```
Session: recordings/2026-10-21_14-46
  [PASS] camera.mp4 is playable (0:12)
  [PASS] screen.mp4 is playable (0:12)
  [PASS] mic.wav is playable (0:12)
  [PASS] system.wav is playable (0:12)
  [PASS] final.mp4 is playable (0:12)
  [WARN] mic.wav audio (microphone) is quiet (mean -35.4 dB, peak -22.0 dB); raise the volume of the source
  [PASS] system.wav audio (system audio) is audible (mean -18.1 dB, peak -3.2 dB)
  [PASS] final.mp4 audio tracks has 2 separate audio tracks (microphone and system audio)
  [WARN] final.mp4 audio (microphone) is quiet (mean -35.0 dB, peak -21.8 dB); raise the volume of the source
  [PASS] final.mp4 audio (system audio) is audible (mean -18.0 dB, peak -3.1 dB)
All 5 files are playable.
The audio checks passed.
Check the WARN lines above.
```

The tool still exits with status 0 only when everything passed, so a `final.mp4` that does not have two audio tracks, or whose two tracks are both silent, fails it.

### Fixing quiet or out-of-sync audio

- **The audio is quiet.** Move closer to the microphone or raise its input level, and play the system sound louder. Check that the Multi-Output Device includes BlackHole 2ch and is selected as the output (see [Set up system audio (Multi-Output Device)](#set-up-system-audio-multi-output-device)). A quiet track passes with a `WARN`; if both tracks of `final.mp4` are silent the check fails, which usually means the sources were silent or the Multi-Output Device was not set up.
- **Your voice and the system audio are not in step with each other.** When the final video is made, both audio files are resampled to one shared rate with timestamp correction, so they stay aligned over long recordings. If a constant gap remains, correct it with a per-stream offset: measure it with the clap method and re-create the final video with `python3 -m recorder.recomposite <session folder> --mic-offset <seconds>` and/or `--system-offset <seconds>` (and `--camera-offset <seconds>` for the presenter's video); see [Applying the offset](#applying-the-offset).
- **The gap grows over the recording (drift).** One offset value cannot correct drift. Tick **Drift Correction** for BlackHole 2ch in the Multi-Output Device (see [System audio troubleshooting](#system-audio-troubleshooting)) and record again.

### Unit tests

The final video's layout and audio are covered by `tests/test_final_quality.py`, which uses only the Python standard library (no real ffmpeg needed). They check that the presenter overlay lands in the bottom-right corner with its margin by default and in each of the four corners when chosen, that the microphone and system audio are each resampled to one rate and kept as two separate tracks with no `amix`, that the camera, microphone and system offsets each shift only their own stream in the filter graph, and that the audio levels parsed from volumedetect are classified as audible, quiet or silent.

They run with the same command as the other tests:

```bash
python3 -m unittest discover -s tests -v
```

## Acceptance test: 30-minute stability

A 30-minute recording must complete without crashes, dropped audio or a frozen window. Several safeguards work together to make that true, and a soak test lets you prove it on your own Mac.

### What keeps a long recording safe

- **The Mac stays awake.** While recording, the app runs macOS's `caffeinate` (see `KeepAwake` in `recorder/stability.py`) so neither the display nor the system goes to sleep. A sleeping Mac stops both captures and leaves a gap in the audio. `caffeinate` is tied to the app's process, so it ends by itself even if the app crashes, and it is stopped again on Stop, on closing the window and on errors.
- **A monitor watches all four captures.** Every 5 seconds a background thread (`CaptureMonitor`) checks that all four ffmpeg processes (camera, screen, microphone and system audio) are still running, that the four raw files are still growing (a file that does not grow for 30 seconds means a stuck capture) and that the disk is not filling up. Each problem is reported once. A fatal problem stops both captures cleanly, so the raw files are finalized and kept, and the **Error** status explains what happened. Running low on disk space (under 2 GB free) is only a warning shown under the clock; the recording stops by itself, with everything so far kept, when less than 300 MB is left.
- **Disk space is checked first.** Before anything starts, the app checks that the folder you save to has room for a 30-minute recording at the chosen quality (including `final.mp4` and a 10% safety margin). If not, recording does not start and the message says how many minutes would fit. Use this table to plan:

  | Quality | Space for a 30-minute recording (all five files) |
  |---------|----------------------------------------------------|
  | Low | about 2.6 GB |
  | Medium | about 5.4 GB |
  | High | about 10.0 GB |

- **Quiet ffmpeg logging.** Every ffmpeg process runs with `-nostats` and the `warning` log level, so its temporary log file stays tiny however long the recording is, and the log of the final composite goes to a temporary file instead of a pipe that could fill up. Compositing has no time limit, so a long recording on a slower Mac is always allowed to finish.
- **Audio is not dropped.** All four captures use a larger input thread queue (`-thread_queue_size 1024`) and wall-clock timestamps, so audio is kept in step even when the Mac is busy.
- **The window stays responsive.** An elapsed-time clock under the status (for example `12:34`) is refreshed once a second with Tk's `after()`, with no extra thread. Errors from the monitor reach the window through the same state updates as every other error, so they are handled on the Tk thread.

### Manual checklist

1. Plug in the Mac, select the Multi-Output Device as the sound output and make sure the permissions are on. Choose the video quality in [Settings](#settings) and check there is enough free space (see the table above).
2. Click **Record**, then play a video or music with sound and speak now and then. Watch the clock reach `30:00`; the window should keep responding, and you can leave the Mac alone.
3. Click **Stop** and wait for **Done**. Compositing a 30-minute recording takes a few minutes.
4. Check the finished session with a minimum length and audio levels:

   ```bash
   python3 -m recorder.verify recordings/2026-10-21_14-46 --audio --min-minutes 29.5
   ```

5. Play `final.mp4` near the start, in the middle and near the end: the presenter, your voice and the system audio should all be present throughout and stay in step.

### Soak test

`recorder/soak.py` does this unattended. It presses Record through the app's own controller, records for the time you ask, presses Stop, waits for `final.mp4` and verifies the result. Run it from the project folder, with the Mac set up as for a normal recording:

```bash
python3 -m recorder.soak --minutes 30
```

For a quick trial of the setup, use a short run such as `--minutes 2`. While it records it measures, every 5 seconds (`--interval` changes this):

- the CPU use and memory of the ffmpeg processes,
- the size of `camera.mp4`, `screen.mp4`, `mic.wav` and `system.wav`, which must keep growing,
- whether the app's threads stay responsive: a heartbeat thread must wake up on time, controller calls must stay fast and the capture monitor thread must stay alive.

Afterwards it runs the verify checks, with audio levels, audio-versus-video lengths and a minimum length, and prints a report. For example:

```
Soak test: 30 minute recording
Session: recordings/2026-10-21_14-46
  [PASS] Recording started: Record reached the Recording state
  [PASS] Ran without errors: recorded 30:00 with no error
  [PASS] Finished with all files: Saved to recordings/2026-10-21_14-46
  [PASS] Low CPU: ffmpeg average 24%, peak 41% (limit 150% average)
  [PASS] Stable memory: peak 310 MB, growth +12 MB from start to end (limits 1500 MB and 300 MB)
  [PASS] All four captures kept running: at least 4 ffmpeg process(es) in every sample (expected 4)
  [PASS] Files kept growing: camera.mp4 longest quiet 5s, screen.mp4 longest quiet 5s, mic.wav longest quiet 5s, system.wav longest quiet 5s (limit 30s)
  [PASS] App stayed responsive: heartbeat at most 0.01s late, slowest controller call 0 ms, monitor thread missing in 0 of 360 samples (limit 2.0s)
  [PASS] Files verified: all checks passed (playable, audio audible, lengths match, two audio tracks in final.mp4)

PASSED: all 9 checks passed.
```

The command exits with status 0 only when every check passed, 1 when a check failed and 2 when the test could not run. Pressing Ctrl+C stops the recording cleanly and keeps the raw files. The limits can be changed with `--max-cpu`, `--max-memory-mb`, `--max-memory-growth-mb`, `--max-ui-lag` and `--max-stall`. CPU is read with `ps`, which gives a smoothed figure, so use it to tell a light hardware encode from an encoder that is using whole cores rather than as an exact number.

### Reading the audio-drop checks

Dropped audio makes the sound shorter than the video. `recorder.verify` compares the length of `final.mp4`'s audio with its video, and the length of `mic.wav` and `system.wav` with the screen recording:

```bash
python3 -m recorder.verify recordings/2026-10-21_14-46 --lengths
python3 -m recorder.verify recordings/2026-10-21_14-46 --min-minutes 30
```

`--lengths` adds one `length` line for each file with sound or video. The audio being 2 seconds or more shorter than the video (or, for `mic.wav` and `system.wav`, than the screen recording) is a `[WARN]` (some audio may have been dropped); clearly shorter (more than 5 seconds and more than 2% of the video) is a `[FAIL]`. `--min-minutes` implies `--lengths` and also fails any file shorter than the given length (10 seconds of tolerance is allowed in the soak test for start-up and stop). For example:

```
  [PASS] screen.mp4 length is 30:01 long
  [PASS] mic.wav length is 30:01 long, and it matches the screen recording length
  [WARN] system.wav length is 29:56 long, but the screen recording is 30:01, so some audio may have been dropped
  [FAIL] final.mp4 length is 12:10 long, which is shorter than the required 30:00
```

### Stability troubleshooting

- **The recording stopped by itself with an Error.** The message says which capture quit or got stuck, or that the disk is almost full. Everything recorded up to that point is kept in the session folder; create `final.mp4` from it with `recorder.recomposite`, then fix the cause (reconnect the camera, free up disk space) before recording again.
- **A warning about low disk space appears under the clock.** Free up space now. The recording continues, and stops by itself with the files kept if less than 300 MB is left.
- **Recording does not start and says only some minutes will fit.** The folder you save to has too little free space for 30 minutes at this quality. Free up space, choose another folder or pick a lower quality in [Settings](#settings).
- **The audio is shorter than the video.** Audio was dropped, usually because the Mac was overloaded or the audio device changed during the recording. Close heavy apps, use **Low** or **Medium** quality, keep the Mac plugged in and do not unplug or switch audio devices while recording.
- **The Mac went to sleep.** The Mac is kept awake while recording, but closing the lid of a laptop still sleeps it unless an external display is connected. Keep the lid open.
- **The soak test reports high CPU.** Run `ffmpeg -hide_banner -encoders | grep videotoolbox`: if nothing is listed, your ffmpeg has no hardware encoder (see [Low CPU use](#low-cpu-use)).
- **The soak test cannot start.** It needs the same setup as a normal recording; the report shows the same message as the **Error** status (permissions, sound output, devices).

### Unit tests

The disk-space estimate, the capture monitor (early exit, stalled file, low disk space, never raising) and the keep-awake helper are covered by `tests/test_stability.py`. It uses only the Python standard library, with fake processes and a fake clock, so it needs no Mac and no real waiting, and runs with the same command as the other tests:

```bash
python3 -m unittest discover -s tests -v
```

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
run.sh                   One-command launcher: creates venv/, installs requirements.txt, checks macOS 13+, the processor, Tkinter (Tk 8.6+) and ffmpeg, starts main.py
build_app.sh             One-command build of the double-clickable .app (dist/Soul Screen Recorder.app) with py2app
setup.py                 py2app configuration: app name, bundle identifier, minimum macOS version and the Camera/Microphone/Screen Recording usage descriptions
main.py                  Entry point: checks the platform (warning dialog for an old macOS or Tk), then creates the controller and window
recorder/
  state.py               Recording states (idle, starting, recording, processing, done, error) and their label/color/button styles
  controller.py          Record/Stop state machine; runs start-up, stop and compositing on background threads; lists and saves device choices; notifies the UI of changes
  devices.py             Finds the camera, microphone, screen and BlackHole devices; auto-picks real devices and honours chosen names
  device_settings.py     Loads and saves the Devices dropdown choices (devices.json in Application Support)
  app_settings.py        Loads and saves the Settings choices: presenter size and corner, output folder, video quality (settings.json in Application Support)
  encoding.py            Chooses the video encoder: h264_videotoolbox hardware encoding, or libx264 if unavailable
  audio_output.py        Detects the current sound output (Multi-Output Device, BlackHole only, or plain output)
  compat.py              The supported platform (macOS 13+, Apple Silicon and Intel, Tk 8.6+) and the check of this Mac; also python3 -m recorder.compat
  permissions.py         Detects missing Camera, Microphone and Screen Recording access (ctypes, no extra packages), builds the fix instructions and opens the matching privacy pane
  errors.py              Friendly error messages (ffmpeg missing, BlackHole missing, device not found, low or full disk) and the translation of raw ffmpeg log text and system errors into them
  capture.py             Starts and stops the four ffmpeg captures (camera, screen, microphone, system audio); writes fragmented MP4s and WAV files and verifies them after stop
  session.py             Creates the timestamped session folder with the paths of its four raw files, final.mp4 and sync.json (default folder: recordings/, or ~/Movies/Soul Screen Recorder in the packaged app)
  verify.py              Checks that a session holds five playable files (camera, screen, mic, system, final) and that final.mp4 has two audio tracks; also python3 -m recorder.verify <session folder>
  sync.py                Reads and writes a session's sync.json (launch times and the camera, microphone and system-audio offsets)
  compositor.py          Builds final.mp4: PiP overlay and two separate audio tracks (Microphone, System audio) via ffmpeg, with optional camera, microphone and system-audio offsets
  recomposite.py         Command-line tool to re-composite an existing session folder (optional --camera-offset, --mic-offset and --system-offset)
  stability.py           Long-recording safeguards: keep-awake (caffeinate), disk-space estimate and the capture monitor (early exit, stalled file, low disk)
  soak.py                Soak test: python3 -m recorder.soak --minutes 30 records unattended, measures CPU, memory, file growth and responsiveness, then verifies the files
ui/
  main_window.py         Tkinter window: status indicator, Record/Stop button, Permissions note with Open Privacy Settings button, Devices dropdowns, safe close handling that keeps the window responsive
tests/
  test_verify.py         Unit tests (standard library unittest) for the session folders and the playable-file check, using a fake ffmpeg
  test_final_quality.py  Unit tests (standard library unittest) for the final video's overlay layout, the two separate audio tracks, resampling and the audio level checks
  test_compat.py         Unit tests (standard library unittest) for the macOS version minimum, Apple Silicon/Intel/Rosetta detection, the Tk check and the never-raises behaviour
  test_stability.py      Unit tests (standard library unittest) for the disk-space estimate, the capture monitor and the keep-awake helper, using fake processes and a fake clock
  test_four_channel.py   Unit tests (standard library unittest) for the four-file session layout, the audio command builders, the launch offsets, the two-track filter graph, the per-stream sync offsets and the recomposite offset flags
docs/
  screencapturekit-evaluation.md   Evaluation of ScreenCaptureKit as a driver-free alternative to BlackHole
requirements.txt         Dependencies (none required yet)
requirements-build.txt   Build-only dependency for the packaged app (py2app)
```

## How it works

- `RecorderController.toggle()` is the single entry point for the button. It starts a recording from Idle, Done, or Error, and stops it from Recording. It only changes the state and starts a background thread, so it returns immediately; clicks during Starting or Processing are ignored.
- Starting, stopping and processing each run in a background thread, so the window never freezes while devices are detected, ffmpeg launches, or ffmpeg flushes and combines the files.
- `RecorderController.shutdown()` is called when the window is closed. It stops any running capture cleanly and waits for the files to be finalized before the app exits. It does not create `final.mp4`. The window runs it in a background thread and keeps updating while it waits, then closes. If it is called while the captures are still starting, the start-up thread stops them as soon as they are up.
- The controller notifies the window of every state change, and the window updates the indicator and button accordingly.
- On Record, the controller enters the Starting state and a background thread runs `_start_capture`, which first checks the sound output (see Sound output check), then detects the devices (using your saved choices where those devices are connected, see Choosing devices), creates the session folder and launches the camera, screen, microphone and system-audio ffmpeg processes back to back (see How capture works). The state then changes to Recording. On Stop, `_stop_capture` asks all four to finish so the MP4 files are finalized cleanly, and then checks that each file can be opened before processing continues.
- Before anything else, `_start_capture` checks the Camera, Microphone and Screen Recording permissions through `recorder/permissions.py` and fails with the exact fix steps if one is turned off. The window runs the same check in a background thread at startup, when it regains focus and after each recording, and shows the **Permissions** note with an **Open Privacy Settings** button while something is missing (see Permission check).
- Any device, session, capture or compositing failure (and any unexpected exception) goes through `recorder/errors.py` before it is shown as the **Error** status: known problems such as a missing device, a busy device or a full disk are recognised in ffmpeg's log and explained with a fix, and the window shows the first sentence as a heading with the fix steps below it (see Error messages).
- Both the captures and the final composite get their video encoder arguments from `recorder/encoding.py`, which prefers hardware encoding and falls back to `libx264` (see Low CPU use).
- After Stop, `_process` runs in the background thread and calls `compositor.composite()`, which runs ffmpeg with an overlay filter (presenter scaled to the width chosen in Settings, about 320 px by default, 20 px from the chosen corner, bottom right by default) and writes the microphone (`mic.wav`) and the system audio (`system.wav`) as two separate AAC tracks, without mixing them. The raw files are never modified.
- The four captures are launched back to back and the measured launch times are saved to `sync.json` after a clean stop. When compositing, the controller passes the session's saved camera, microphone and system-audio offsets to the compositor, which shifts each of those streams against the screen before the overlay is applied and the two audio tracks are written (see Audio/video sync).
- Before the window opens, `main.py` asks the controller for the platform check from `recorder/compat.py` and shows a warning dialog if macOS is older than 13 or Tk is older than 8.6. `_start_capture` checks the macOS version again before anything else, so an unsupported macOS never starts a recording. A version that cannot be determined never blocks (see Compatibility).