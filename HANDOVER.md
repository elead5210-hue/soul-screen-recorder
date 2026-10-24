# Hand-over: four-stream recording with two audio tracks

This note covers the change from two recorded files to four, what could and could not be tested without a Mac, and what to check on the first real recording.

## What changed

Before, `camera.mp4` held the presenter video and the microphone, `screen.mp4` held the screen and the system audio, and `final.mp4` mixed the two audio sources into one track. Now there are four independent ffmpeg captures:

| File | Content |
|------|---------|
| `camera.mp4` | presenter camera, video only (fragmented MP4) |
| `screen.mp4` | screen, video only (fragmented MP4) |
| `mic.wav` | microphone, 48 kHz 16-bit PCM WAV |
| `system.wav` | system audio from BlackHole, 48 kHz 16-bit PCM WAV |
| `final.mp4` | screen with the camera overlay, plus two separate AAC tracks: **Microphone** (track 1, default) and **System audio** (track 2). No `amix`. |
| `sync.json` | launch time of each stream, and the camera, microphone and system-audio offsets relative to the screen |

Main points:

- `capture.py`: `MultiCapture` replaces `DualCapture` (the old name is kept as an alias). It starts, stops and verifies all four processes and reports a failure by stream name.
- `controller.py` and `stability.py`: the monitor watches all four streams. A failure in any one stops all four cleanly and keeps the files. The disk-space estimate now counts the two WAV files and the two-track `final.mp4`.
- `compositor.py`: four inputs, each shifted by its own offset against the screen, with the audio resampled and written as two titled tracks.
- `sync.py`: per-stream launch times and offsets. An old two-file `sync.json` still loads, and its camera offset also becomes the microphone offset.
- `recomposite.py`: new `--mic-offset` and `--system-offset` flags next to `--camera-offset`. An offset that is left out uses the value saved in `sync.json`. The tool refuses to overwrite a raw file.
- `verify.py`: expects the five files, checks the WAVs for silence and length, and checks that `final.mp4` has exactly two audio tracks.
- `soak.py`: now expects four ffmpeg processes and samples all four files.
- Tests: the existing suites were updated and `tests/test_four_channel.py` is new. `README.md` and `docs/SETUP.md` describe the new layout.

Sessions recorded by the old version have no `mic.wav` or `system.wav`, so they cannot be re-composited.

## What was tested here

Everything that does not need a Mac or a device: the command builders, the filter graph and composite command, the session layout, the sync model and its migration of old files, the `recomposite` flags, the monitor and disk estimate, the verify logic, and the soak report. These run with fake processes and a fake clock:

```bash
python3 -m unittest discover -s tests -v
```

## What could not be tested here

None of this has run against real hardware, so treat the first recordings as the real test.

1. **Live avfoundation capture.** The commands were checked as text only. Not confirmed: that avfoundation accepts `index:none` for video-only and `none:index` for audio-only on your devices, that the WAV flags (`-flush_packets`, `-rf64 auto`) behave as intended, and that four processes can open their devices at the same time.
2. **Real-world sync.** The launch times are measured, but the delay before each device actually delivers data is not known. Whether the camera, microphone and system audio line up without offsets, how large the gaps are, and whether they stay constant between recordings is unknown. Over a long recording, drift between the WAV files and the video is also unverified.
3. **Hardware encoding.** `h264_videotoolbox` for capture and compositing was not exercised, nor were CPU use and memory with four processes.
4. **Real ffmpeg output.** `final.mp4` was never produced by a real ffmpeg: the two audio tracks, their titles, the default track and the `-shortest` behaviour need checking in a player. The verify tool's parsing of real `volumedetect` and stream output is untested.
5. **Permissions and system audio.** Camera, Microphone and Screen Recording prompts, the Multi-Output Device check and BlackHole capture were not run.
6. **Long recordings.** The 30-minute soak test and the disk-space table (about 2.6, 5.4 and 10 GB for Low, Medium and High, including `final.mp4`) were not run.
7. **Packaged app.** `./build_app.sh` and the double-clickable app were not rebuilt or opened.

## First recording on the Mac

Do these in order and stop at the first failure.

1. Run `python3 -m unittest discover -s tests` and confirm it passes on the Mac as well.
2. Check that ffmpeg, BlackHole 2ch and the permissions are in place, and that the Multi-Output Device is your sound output (`docs/SETUP.md`, sections 2 and 3).
3. Start with `./run.sh`, press **Record** and wait for **Recording...**. The status should not drop to **Error**. In Activity Monitor you should see four `ffmpeg` processes.
4. **Clap test.** Facing the camera, with something visible and audible on screen (a test video with a flash and a beep, or a click that makes something flash), clap once at the moment it happens. Do this near the start, talk for about a minute while sound plays, then clap and trigger the event again near the end. Press **Stop** and wait for **Done**.
5. Check the files:

   ```bash
   python3 -m recorder.verify recordings/<session folder> --audio --lengths
   ```

   Expect five playable files, two audio tracks in `final.mp4`, and no `[FAIL]` lines. A `[WARN]` for silence in `mic.wav` or `system.wav` means that source was quiet.
6. Open `final.mp4` in VLC. Under Audio > Audio Track, check that **Microphone** has your voice and **System audio** has the sound that was playing.
7. In `final.mp4`, check the clap against the screen event, near the start and near the end:
   - The clap in the video should match the clap in the Microphone track.
   - The beep in the System audio track should match the flash.
   - If they are off by a roughly constant amount, measure each gap (offset = screen time − stream time) in the raw files and re-create the video, giving only the offsets you need:

     ```bash
     python3 -m recorder.recomposite recordings/<session folder> --camera-offset <s> --mic-offset <s> --system-offset <s>
     ```

   - If the gap differs between the start and the end, that is drift. One offset cannot fix it, so note the numbers.
8. Repeat the clap test two or three times. If the measured gaps change from recording to recording, the offsets cannot be fixed values and the launch measurements will need a better approach.
9. Optional: run a short soak test with `python3 -m recorder.soak --minutes 2`, then the full `--minutes 30` run. Check CPU, memory and that the disk-space figures are reasonable.
10. Optional: rebuild the packaged app with `./build_app.sh` and repeat steps 3 to 6 from the app.

Please report back what you measure in step 7 (the camera, microphone and system-audio gaps and whether they were constant) and anything that fails in steps 3 to 6.