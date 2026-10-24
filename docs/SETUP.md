# Soul Screen Recorder — macOS Setup Guide

This guide walks you through installing and configuring Soul Screen Recorder on a Mac for the first time. It takes about 10 minutes. You only need to do the one-time configuration once — after that, launching the app is a single command.

---

## 1. Prerequisites

You need:

- A Mac running macOS (Ventura or newer recommended)
- [Homebrew](https://brew.sh) — the package manager used to install dependencies

If `brew` isn't installed yet, open **Terminal** and run the install command from <https://brew.sh>, then continue.

> **Where to run commands:** Everything below is typed in the **Terminal** app (or the terminal inside VS Code, if that's what you use). Navigate to the project folder first:
>
> ```bash
> cd path/to/soul-screen-recorder
> ```

---

## 2. Install dependencies

Run each of these in the project folder:

```bash
# 1. FFmpeg — records the four streams, encodes the video and builds final.mp4
brew install ffmpeg

# 2. BlackHole 2ch — routes system audio so the recorder can capture it
brew install --cask blackhole-2ch

# 3. Tkinter — the Python GUI toolkit the app uses
brew install python-tk
```

Then make the launcher executable:

```bash
chmod +x run.sh
```

---

## 3. One-time macOS configuration

macOS restricts screen, microphone, and camera access, and system audio needs to be routed through BlackHole. These steps are done once, in **System Settings** and **Audio MIDI Setup**.

### 3.1 Grant Terminal the required permissions

The app inherits permissions from the terminal you launch it from, so the *host app* (Terminal or VS Code) needs them — not the recorder itself.

1. Open **System Settings → Privacy & Security**.
2. Under **Camera** and **Microphone**: if your terminal app isn't listed, click **+**, press **Command + Shift + G**, type `/System/Applications/Utilities/`, press Return, select **Terminal.app**, click **Open**, and switch it on. (If you run commands from VS Code or another app, add *that* app instead.)
3. Under **Screen & System Audio Recording**: turn your terminal app on.
4. **Fully quit and reopen your terminal** (Command + Q, then reopen) — macOS only grants new permissions after a full restart.

> Tip: If Terminal doesn't appear in the Screen Recording list or stays "off" after restarting, reset the permission and try again:
>
> ```bash
> tccutil reset ScreenCapture com.apple.Terminal
> ```
>
> Then quit Terminal (Command + Q), reopen it, and run the app. When macOS asks for permission, click **Allow**, and quit and reopen Terminal once more.

### 3.2 Set up the audio Multi-Output Device

The recorder captures system audio through BlackHole. To keep hearing sound through your speakers *while* recording, combine both in one device:

1. Press **Command + Space**, type **Audio MIDI Setup**, press Return.
2. Click the **+** button at the bottom-left → **Create Multi-Output Device**.
3. In the device list, tick **MacBook Air Speakers** (or whatever your real speakers/headphones are) **and BlackHole 2ch**.
4. Set **Primary Device** to your **MacBook Air Speakers** (not BlackHole).
5. Tick the **Drift Correction** checkbox on the **BlackHole 2ch** row only — leave it unticked on the speakers row.
6. Right-click (or Control-click) **the Multi-Output Device** in the left list and choose **Use This Device For Sound Output** — the little speaker icon should move to it.
7. Go to **System Settings → Sound → Output** and confirm that Multi-Output Device is selected.
8. Optional cleanup: if you created extra multi-output devices while experimenting, select them and press the **–** button to delete them.

> **Note:** While the Multi-Output Device is your sound output, the volume keys won't respond — set your volume *before* you start recording.
>
> **Warning sign:** If the app tells you your output is set to BlackHole 2ch only, it means sound is going straight to BlackHole (you'd hear nothing and lose normal playback). Follow step 6 above to move the speaker icon to the Multi-Output Device.

---

## 4. Launch the app

```bash
./run.sh
```

The first run creates a Python virtual environment (`venv/`) and installs everything the app needs, then starts the recorder. Subsequent runs skip straight to the app.

> **If you have a Python virtual environment already active** (e.g. `(.venv)` shows in your prompt), run `deactivate` first so `run.sh` can build its own clean environment.

---

## 5. First recording checklist

- [ ] Terminal has Camera, Microphone, and Screen & System Audio Recording permissions
- [ ] Multi-Output Device is your active sound output
- [ ] Volume is set where you want it (volume keys won't work while recording)
- [ ] `./run.sh` launches without warnings
- [ ] There is plenty of free disk space for the recording (see below)
- [ ] After a short test recording (about 10 seconds), the session folder holds five files and `python3 -m recorder.verify <session folder> --audio` passes

### What a recording contains

Each recording gets its own timestamped folder (by default inside `recordings/`, or `~/Movies/Soul Screen Recorder` in the packaged app) with four raw files, the finished video and a sync file:

```
camera.mp4    presenter camera, video only
screen.mp4    screen, video only
mic.wav       microphone, audio only
system.wav    system audio (BlackHole), audio only
final.mp4     screen + presenter overlay, with two audio tracks
sync.json     measured start times and the alignment offsets
```

`final.mp4` has **two separate audio tracks**: **Microphone** (track 1, played by default) and **System audio** (track 2). They are not mixed, so you can switch between them or level them separately. Most players play one track at a time: in VLC choose **Audio → Audio Track** to switch, or use an editor that plays all tracks. The four raw files are never changed or deleted by the app.

**Disk space.** The two WAV files are uncompressed (about 23 MB per minute together), so recordings need more room than before. Allow roughly 2.6 GB (Low), 5.4 GB (Medium) or 10 GB (High) for a 30-minute recording including `final.mp4`. The app checks the free space before it starts and tells you how many minutes fit.

**Checking a test recording.** Replace the folder name with the one shown after **Done**:

```bash
python3 -m recorder.verify recordings/2026-10-21_14-46 --audio --lengths
```

It reports on all five files and checks that `final.mp4` has two audio tracks.

**Fixing sync afterwards.** The four captures start a fraction of a second apart. To measure a gap, clap once in view of the camera at the moment something visible and audible happens on screen, then compare the times in `camera.mp4`, `mic.wav`, `screen.mp4` and `system.wav` (offset = screen time − stream time). Re-create `final.mp4` with the offsets, each in seconds (positive delays a stream, negative makes it earlier; give only the ones you need):

```bash
python3 -m recorder.recomposite recordings/2026-10-21_14-46 --camera-offset -0.35 --mic-offset -0.12 --system-offset 0.05
```

The offsets are saved to `sync.json` and reused on later runs. Only sessions that have all four raw files can be re-composited.

---

## 6. Troubleshooting

| Problem | Fix |
| --- | --- |
| `zsh: no such file or directory: ./run.sh.` | Typo — extra period at the end. Run `./run.sh` with no trailing dot. |
| `./run.sh` isn't executable | Run `chmod +x run.sh` |
| Missing Tkinter error during install | Run `brew install python-tk`, then `deactivate` any active venv and re-run `./run.sh` |
| Installer says a reboot is required | Restart your Mac, then re-run `./run.sh` |
| App says sound output is BlackHole only | Follow §3.2 — especially "Use This Device For Sound Output" and Primary Device set to your speakers |
| Terminal permission toggle won't stick | Quit Terminal fully (Command + Q), reopen, retry. If it still fails: `tccutil reset ScreenCapture com.apple.Terminal`, restart Terminal, run the app, click **Allow** |
| Terminal is missing from a permissions list | Click **+**, press **Command + Shift + G**, go to `/System/Applications/Utilities/`, select **Terminal.app** |
| Can't find a setting | Use the **search bar** in System Settings (e.g. type "Screen Recording") |
| `final.mp4` plays only my voice, or only the system sound | It has two separate audio tracks and the player plays one at a time. Switch tracks in the player (VLC: **Audio → Audio Track**) |
| My voice, the system sound or the presenter is slightly out of step | Measure the gap with a clap and re-create the video with `python3 -m recorder.recomposite <session folder> --camera-offset <s> --mic-offset <s> --system-offset <s>` |
| Recording won't start and mentions low disk space | The four raw files plus `final.mp4` need more room than two files did. Free up space, choose another folder in Settings or pick a lower video quality |
| Recording stops with an error naming the microphone or system audio | Check that the microphone and BlackHole 2ch are connected, and that the Multi-Output Device is still your sound output (§3.2). The raw files recorded so far are kept |

---

## 7. Daily use

After setup, starting a session is just:

```bash
cd path/to/soul-screen-recorder
./run.sh
```

No other configuration needed — permissions and audio routing are remembered by macOS between runs.
