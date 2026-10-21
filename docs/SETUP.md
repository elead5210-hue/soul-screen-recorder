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
# 1. FFmpeg — handles video encoding
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

---

## 7. Daily use

After setup, starting a session is just:

```bash
cd path/to/soul-screen-recorder
./run.sh
```

No other configuration needed — permissions and audio routing are remembered by macOS between runs.
