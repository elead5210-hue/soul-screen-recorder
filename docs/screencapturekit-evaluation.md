# Evaluation: ScreenCaptureKit for system audio

This note evaluates ScreenCaptureKit as a driver-free alternative to the BlackHole 2ch approach that v1 uses to capture system audio.

## Summary

**Recommendation: keep BlackHole 2ch (with a Multi-Output Device) for v1.** Treat ScreenCaptureKit as a possible v2 improvement, once the rest of the app is stable.

## How v1 captures system audio today

- The app runs `ffmpeg` with the `avfoundation` input and records the **BlackHole 2ch** virtual audio device alongside the screen.
- To let the user still hear sound, macOS output must be set to a **Multi-Output Device** that contains both the normal speakers or headphones and BlackHole 2ch.
- Before each recording, the app checks the current sound output and shows the setup steps if it is not a Multi-Output Device.
- Everything stays a plain `ffmpeg` subprocess, with no native code and no Python packages.

## What ScreenCaptureKit offers

ScreenCaptureKit is Apple's framework for capturing screen content and application audio.

- **No driver and no Multi-Output Device.** System audio is captured directly, so there is nothing to install, nothing to configure in Audio MIDI Setup, and the user's volume keys keep working.
- **Audio is not rerouted.** The user keeps hearing sound through their normal output without any workaround.
- **Cleaner setup.** One fewer thing for the user to install and get wrong, and no restart after installing a driver.
- **Better selection.** It can capture a specific display, window or application, and can exclude the app's own sound.

## Requirements and limitations

- **macOS version.** Capturing audio through ScreenCaptureKit needs **macOS 13 (Ventura) or newer**. v1 already recommends macOS 13+, but BlackHole itself works on older versions, so ScreenCaptureKit would raise the floor for anyone relying on that.
- **ffmpeg cannot use it.** The `avfoundation` input in ffmpeg does not read ScreenCaptureKit audio. The app would need a separate native component that captures the frames and audio and hands them to ffmpeg or writes files itself.
- **Permissions.** It uses the **Screen & System Audio Recording** permission, which the app already asks for, but the permission is granted to whichever app launches the capture. A bundled helper binary would need to be signed and approved properly to avoid repeated prompts.
- **Two capture paths.** The camera and microphone would still be recorded with ffmpeg, so the app would have a mixed setup: ffmpeg for the presenter and a native helper for the screen.
- **Start-time sync.** The two streams must still start within a fraction of a second of each other. Using two different capture technologies makes this harder to guarantee and to align afterwards.

## Implementation options

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A. PyObjC** | Call ScreenCaptureKit from Python through the `pyobjc-framework-ScreenCaptureKit` package. | Stays in Python; no separate binary. | Adds Python dependencies; the framework uses callbacks and sample buffers that are awkward to bridge; encoding to MP4 must be done in Python (for example with AVFoundation writers). |
| **B. Small Swift helper** | A command-line tool, started by the app via `subprocess`, that records the screen and system audio to `screen.mp4` and stops cleanly on a signal. | Fits the existing subprocess and stop model; uses Apple's own APIs and hardware encoding directly. | Needs a Swift toolchain, a build step, code signing and shipping a binary for both Apple Silicon and Intel. |
| **C. Existing tool** | Use a third-party command-line recorder built on ScreenCaptureKit. | Least code to write. | Another external dependency to install and trust; less control over output and error handling. |

Option B is the most robust if ScreenCaptureKit is adopted, because it keeps the app's current start, stop and verify flow and only replaces the screen capture process.

## Comparison

| | BlackHole 2ch (v1) | ScreenCaptureKit |
|---|---|---|
| Driver install | Required | Not needed |
| Multi-Output Device setup | Required | Not needed |
| Volume keys | Do not work on a Multi-Output Device | Work normally |
| Works with ffmpeg only | Yes | No, needs native code |
| macOS versions | Wide support | macOS 13+ |
| Extra code to maintain | None | A native helper or PyObjC layer |
| Start-time sync with camera | Both are ffmpeg processes | Different capture technologies |
| Risk for v1 | Low; already implemented | Higher; new component and build step |

## Recommendation

1. **Keep BlackHole for v1.** It is already implemented, works with the simple ffmpeg-only design, and the app now checks the sound output and explains the setup when it is wrong.
2. **Do not add ScreenCaptureKit yet.** It would introduce native code, a build and signing step, and a second capture path, all for a setup improvement that the README and the output check already soften.
3. **Revisit after v1.** If users find the BlackHole and Multi-Output Device setup too hard, build option B (a Swift helper) behind a setting, keeping BlackHole as the fallback for older macOS versions.

## Open questions for a future spike

- Can the helper stop cleanly on a signal so the MP4 is finalized, and write fragmented MP4 like the current files?
- How close can the screen and camera start times be kept with two different capture technologies?
- Does the helper trigger its own permission prompt, or reuse the one granted to the launching app?
- Which macOS versions and architectures must the helper binary support?