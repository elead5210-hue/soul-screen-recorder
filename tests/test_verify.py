"""Tests for the session folder naming and the five-file verification.

Run from the project folder with the standard library only:

    python3 -m unittest discover -s tests -v

No real ffmpeg is needed: the playable-file check is run against a tiny fake
"ffmpeg" script that answers according to the first bytes of the file it is
asked to open.
"""

import contextlib
import io
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

# Make `import recorder` work when the tests are started from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recorder import session as session_module  # noqa: E402
from recorder import verify  # noqa: E402
from recorder.session import (  # noqa: E402
    CAMERA_FILENAME,
    FINAL_FILENAME,
    MIC_FILENAME,
    SCREEN_FILENAME,
    SYNC_FILENAME,
    SYSTEM_FILENAME,
    create_session,
    default_output_root,
)

# What the fake ffmpeg prints and returns for each kind of file content.
FAKE_FFMPEG_SOURCE = r'''#!{python}
import sys

args = sys.argv[1:]
path = args[args.index("-i") + 1]
with open(path, "rb") as handle:
    head = handle.read(16)

if head.startswith(b"GOOD"):
    sys.stderr.write(
        "Input #0, mov,mp4, from 'x.mp4':\n"
        "  Duration: 00:01:02.50, start: 0.000000, bitrate: 8000 kb/s\n"
        "  Stream #0:0: Video: h264, yuv420p, 1920x1080, 30 fps\n"
    )
    sys.exit(0)
if head.startswith(b"WAVOK"):
    sys.stderr.write(
        "Input #0, wav, from 'x.wav':\n"
        "  Duration: 00:01:02.50, bitrate: 1536 kb/s\n"
        "  Stream #0:0: Audio: pcm_s16le, 48000 Hz, stereo, s16, 1536 kb/s\n"
    )
    sys.exit(0)
if head.startswith(b"NOAUDIO"):
    sys.stderr.write("Stream map '0:a:0' matches no streams.\n")
    sys.exit(1)
if head.startswith(b"NOMOOV"):
    sys.stderr.write("x.mp4: moov atom not found\nInvalid data found\n")
    sys.exit(1)
if head.startswith(b"AUDIO"):
    sys.stderr.write(
        "Input #0, mov,mp4, from 'x.mp4':\n"
        "  Stream #0:0: Audio: aac\n"
        "Stream map '0:v:0' matches no streams.\n"
    )
    sys.exit(1)
if head.startswith(b"BADFRAME"):
    sys.stderr.write(
        "  Stream #0:0: Video: h264, yuv420p, 1920x1080\n"
        "[h264] error while decoding MB 0 0\n"
    )
    sys.exit(1)
sys.stderr.write("unknown test content\n")
sys.exit(1)
'''


class FakeFfmpegTestCase(unittest.TestCase):
    """Creates a temp folder and a fake ffmpeg for each test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.ffmpeg = str(self.tmp / "fake-ffmpeg")
        Path(self.ffmpeg).write_text(
            FAKE_FFMPEG_SOURCE.format(python=sys.executable), encoding="utf-8"
        )
        os.chmod(self.ffmpeg, os.stat(self.ffmpeg).st_mode | stat.S_IEXEC)

    def write(self, folder: Path, name: str, content: bytes) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(content)
        return path

    def make_session_folder(self, **contents: bytes) -> Path:
        """Folder with the five session files.

        Pass camera=, screen=, mic=, system= or final= to change a file's
        content. The .wav files default to a good audio file and the .mp4
        files to a good video file.

        A file whose content is None is not created.
        """
        folder = self.tmp / "session"
        folder.mkdir(exist_ok=True)
        names = {
            "camera": CAMERA_FILENAME,
            "screen": SCREEN_FILENAME,
            "mic": MIC_FILENAME,
            "system": SYSTEM_FILENAME,
            "final": FINAL_FILENAME,
        }
        for key, name in names.items():
            default = b"WAVOK data" if key in ("mic", "system") else b"GOOD data"
            content = contents.get(key, default)
            if content is not None:
                (folder / name).write_bytes(content)
        return folder


class SessionFolderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "videos"
        # The free-space check is not what is being tested here.
        patcher = mock.patch.object(session_module, "MIN_FREE_BYTES", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_creates_timestamped_folder_with_all_the_file_paths(self) -> None:
        when = datetime(2026, 10, 21, 14, 46, 5)
        session = create_session(self.root, now=when)

        self.assertEqual(session.folder, self.root / "2026-10-21_14-46")
        self.assertTrue(session.folder.is_dir())
        self.assertEqual(session.camera_path, session.folder / "camera.mp4")
        self.assertEqual(session.screen_path, session.folder / "screen.mp4")
        self.assertEqual(session.mic_path, session.folder / "mic.wav")
        self.assertEqual(session.system_path, session.folder / "system.wav")
        self.assertEqual(session.final_path, session.folder / "final.mp4")
        self.assertEqual(session.sync_path, session.folder / SYNC_FILENAME)

    def test_second_session_in_the_same_minute_gets_a_suffix(self) -> None:
        when = datetime(2026, 10, 21, 14, 46)
        first = create_session(self.root, now=when)
        second = create_session(self.root, now=when)
        third = create_session(self.root, now=when)

        self.assertEqual(first.folder.name, "2026-10-21_14-46")
        self.assertEqual(second.folder.name, "2026-10-21_14-46-2")
        self.assertEqual(third.folder.name, "2026-10-21_14-46-3")

    def test_empty_output_folder_means_the_default_folder(self) -> None:
        when = datetime(2026, 10, 21, 9, 0)
        with mock.patch.object(
            session_module, "default_output_root", return_value=self.root
        ):
            for unset in (None, "", "   "):
                session = create_session(unset, now=when)
                self.assertEqual(session.folder.parent, self.root)

    def test_default_folder_depends_on_running_as_a_packaged_app(self) -> None:
        self.assertEqual(default_output_root(), session_module.DEFAULT_OUTPUT_ROOT)
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(
                default_output_root(), session_module.PACKAGED_OUTPUT_ROOT
            )

    def test_unusable_output_folder_gives_a_session_error(self) -> None:
        blocker = Path(self._tmp.name) / "a-file"
        blocker.write_text("not a folder", encoding="utf-8")
        with self.assertRaises(session_module.SessionError):
            create_session(blocker / "inside")


class CheckFileTests(FakeFfmpegTestCase):
    def test_good_file_is_playable_and_reports_its_length(self) -> None:
        path = self.write(self.tmp, "good.mp4", b"GOOD data")
        result = verify.check_file(path, self.ffmpeg)

        self.assertTrue(result.ok)
        self.assertEqual(result.duration_seconds, 62.5)
        self.assertIn("playable", result.detail)
        self.assertIn("1:03", result.detail)  # 62.5 s rounds to 1:03

    def test_missing_file(self) -> None:
        result = verify.check_file(self.tmp / "nope.mp4", self.ffmpeg)
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "is missing")

    def test_empty_file(self) -> None:
        path = self.write(self.tmp, "empty.mp4", b"")
        result = verify.check_file(path, self.ffmpeg)
        self.assertFalse(result.ok)
        self.assertIn("empty", result.detail)

    def test_file_without_index_is_unplayable(self) -> None:
        path = self.write(self.tmp, "broken.mp4", b"NOMOOV data")
        result = verify.check_file(path, self.ffmpeg)
        self.assertFalse(result.ok)
        self.assertIn("unplayable", result.detail)

    def test_file_without_video_stream(self) -> None:
        path = self.write(self.tmp, "audio.mp4", b"AUDIO data")
        result = verify.check_file(path, self.ffmpeg)
        self.assertFalse(result.ok)
        self.assertIn("no video stream", result.detail)

    def test_file_whose_video_cannot_be_decoded(self) -> None:
        path = self.write(self.tmp, "bad.mp4", b"BADFRAME data")
        result = verify.check_file(path, self.ffmpeg)
        self.assertFalse(result.ok)
        self.assertIn("could not be decoded", result.detail)

    def test_wav_file_is_checked_as_audio(self) -> None:
        path = self.write(self.tmp, "mic.wav", b"WAVOK data")
        result = verify.check_file(path, self.ffmpeg)

        self.assertTrue(result.ok)
        self.assertEqual(result.duration_seconds, 62.5)
        self.assertIn("playable", result.detail)

    def test_wav_file_without_an_audio_stream_fails(self) -> None:
        path = self.write(self.tmp, "mic.wav", b"NOAUDIO data")
        result = verify.check_file(path, self.ffmpeg)

        self.assertFalse(result.ok)
        self.assertIn("no audio stream", result.detail)

    def test_damaged_wav_file_is_unplayable(self) -> None:
        path = self.write(self.tmp, "system.wav", b"NOMOOV data")
        result = verify.check_file(path, self.ffmpeg)

        self.assertFalse(result.ok)
        self.assertIn("unplayable", result.detail)

    def test_empty_wav_file(self) -> None:
        path = self.write(self.tmp, "system.wav", b"")
        result = verify.check_file(path, self.ffmpeg)

        self.assertFalse(result.ok)
        self.assertIn("empty", result.detail)

    def test_missing_ffmpeg_raises_verify_error(self) -> None:
        path = self.write(self.tmp, "good.mp4", b"GOOD data")
        with self.assertRaises(verify.VerifyError):
            verify.check_file(path, str(self.tmp / "no-such-ffmpeg"))


class VerifySessionTests(FakeFfmpegTestCase):
    def test_five_playable_files_pass(self) -> None:
        folder = self.make_session_folder()
        check = verify.verify_session(folder, self.ffmpeg)

        self.assertTrue(check.ok)
        self.assertEqual(
            [f.name for f in check.files],
            [
                CAMERA_FILENAME,
                SCREEN_FILENAME,
                MIC_FILENAME,
                SYSTEM_FILENAME,
                FINAL_FILENAME,
            ],
        )
        self.assertEqual(check.failed, [])

    def test_missing_final_video_fails_only_that_file(self) -> None:
        folder = self.make_session_folder(final=None)
        check = verify.verify_session(folder, self.ffmpeg)

        self.assertFalse(check.ok)
        self.assertEqual([f.name for f in check.failed], [FINAL_FILENAME])
        self.assertEqual(check.failed[0].detail, "is missing")

    def test_each_kind_of_problem_is_reported_per_file(self) -> None:
        folder = self.make_session_folder(camera=b"", screen=b"NOMOOV", final=b"GOOD")
        check = verify.verify_session(folder, self.ffmpeg)

        self.assertFalse(check.ok)
        by_name = {f.name: f for f in check.files}
        self.assertIn("empty", by_name[CAMERA_FILENAME].detail)
        self.assertIn("unplayable", by_name[SCREEN_FILENAME].detail)
        self.assertTrue(by_name[FINAL_FILENAME].ok)

    def test_missing_audio_file_fails_only_that_file(self) -> None:
        folder = self.make_session_folder(mic=None)
        check = verify.verify_session(folder, self.ffmpeg)

        self.assertFalse(check.ok)
        self.assertEqual([f.name for f in check.failed], [MIC_FILENAME])
        self.assertEqual(check.failed[0].detail, "is missing")

    def test_system_wav_without_audio_is_reported(self) -> None:
        folder = self.make_session_folder(system=b"NOAUDIO")
        check = verify.verify_session(folder, self.ffmpeg)

        self.assertFalse(check.ok)
        self.assertEqual([f.name for f in check.failed], [SYSTEM_FILENAME])
        self.assertIn("no audio stream", check.failed[0].detail)

    def test_missing_session_folder_raises_verify_error(self) -> None:
        with self.assertRaises(verify.VerifyError):
            verify.verify_session(self.tmp / "no-such-folder", self.ffmpeg)

    def test_report_lists_pass_and_fail_lines(self) -> None:
        folder = self.make_session_folder(screen=b"NOMOOV")
        report = verify.format_report(verify.verify_session(folder, self.ffmpeg))

        self.assertIn("[PASS] camera.mp4", report)
        self.assertIn("[FAIL] screen.mp4", report)
        self.assertIn("[PASS] mic.wav", report)
        self.assertIn("[PASS] system.wav", report)
        self.assertIn("[PASS] final.mp4", report)
        self.assertIn("1 of 5 files failed", report)

    def test_report_for_a_good_session(self) -> None:
        folder = self.make_session_folder()
        report = verify.format_report(verify.verify_session(folder, self.ffmpeg))
        self.assertIn("All 5 files are playable.", report)


class ExpectedFilesTests(unittest.TestCase):
    def test_expected_files_are_the_five_session_files(self) -> None:
        self.assertEqual(
            verify.EXPECTED_FILES,
            (
                CAMERA_FILENAME,
                SCREEN_FILENAME,
                MIC_FILENAME,
                SYSTEM_FILENAME,
                FINAL_FILENAME,
            ),
        )
        self.assertEqual(MIC_FILENAME, "mic.wav")
        self.assertEqual(SYSTEM_FILENAME, "system.wav")


# A second fake ffmpeg that answers every command verify.py runs (the decode
# check, the volume measurement, the track listing and the length check) for
# a scenario chosen by the first bytes of the file. Each scenario sets how
# many audio tracks the file has, the peak and mean level of each track and
# the length of its video and audio, in seconds (None = no such stream).
FAKE_MEDIA_FFMPEG_SOURCE = r'''#!@PYTHON@
import sys

LOUD = (-18.1, -3.2)
SILENT = (-91.5, -85.2)

SCENARIOS = {
    b"TWOTRACKS": dict(tracks=2, levels=[LOUD, (-20.0, -5.0)], video=60.0, audio=60.0),
    b"ONETRACK": dict(tracks=1, levels=[LOUD], video=60.0, audio=60.0),
    b"BOTHSILENT": dict(tracks=2, levels=[SILENT, SILENT], video=60.0, audio=60.0),
    b"SILENTSYS": dict(tracks=2, levels=[LOUD, SILENT], video=60.0, audio=60.0),
    b"DROPPED": dict(tracks=2, levels=[LOUD, LOUD], video=60.0, audio=40.0),
    b"VIDEO": dict(tracks=0, levels=[], video=60.0, audio=None),
    b"WAVFULL": dict(tracks=1, levels=[LOUD], video=None, audio=60.0),
    b"WAVSHORT": dict(tracks=1, levels=[LOUD], video=None, audio=30.0),
    b"WAVNEAR": dict(tracks=1, levels=[LOUD], video=None, audio=57.0),
    b"WAVSILENT": dict(tracks=1, levels=[SILENT], video=None, audio=60.0),
}

args = sys.argv[1:]
path = args[args.index("-i") + 1]
with open(path, "rb") as handle:
    head = handle.read(16)

scenario = None
for key, value in SCENARIOS.items():
    if head.startswith(key):
        scenario = value
        break
if scenario is None:
    sys.stderr.write("unknown test content\n")
    sys.exit(1)


def stamp(seconds):
    total = int(seconds)
    hours = total // 3600
    minutes = total % 3600 // 60
    return "%02d:%02d:%05.2f" % (hours, minutes, seconds - hours * 3600 - minutes * 60)


def streams_text():
    lengths = [s for s in (scenario["video"], scenario["audio"]) if s is not None]
    text = "Input #0, test, from 'x':\n"
    text += "  Duration: %s, start: 0.000000, bitrate: 8000 kb/s\n" % stamp(max(lengths))
    if scenario["video"] is not None:
        text += "  Stream #0:0: Video: h264, yuv420p, 1920x1080, 30 fps\n"
    for index in range(scenario["tracks"]):
        text += "  Stream #0:%d(und): Audio: aac, 48000 Hz, stereo\n" % (index + 1)
    return text


if "-frames:v" in args:
    if scenario["video"] is None:
        sys.stderr.write("Stream map '0:v:0' matches no streams.\n")
        sys.exit(1)
    sys.stderr.write(streams_text())
    sys.exit(0)
if "-t" in args:
    if scenario["tracks"] < 1:
        sys.stderr.write("Stream map '0:a:0' matches no streams.\n")
        sys.exit(1)
    sys.stderr.write(streams_text())
    sys.exit(0)
if "-af" in args:
    wanted = args[args.index("-map") + 1]
    index = int(wanted.split(":")[-1])
    if index >= len(scenario["levels"]):
        sys.stderr.write("Stream map '%s' matches no streams.\n" % wanted)
        sys.exit(1)
    mean, peak = scenario["levels"][index]
    sys.stderr.write("[Parsed_volumedetect_0 @ 0x0] mean_volume: %.1f dB\n" % mean)
    sys.stderr.write("[Parsed_volumedetect_0 @ 0x0] max_volume: %.1f dB\n" % peak)
    sys.exit(0)
if "copy" in args:
    wanted = args[args.index("-map") + 1]
    seconds = scenario["video"] if wanted.split(":")[1] == "v" else scenario["audio"]
    if seconds is None:
        sys.stderr.write("Stream map '%s' matches no streams.\n" % wanted)
        sys.exit(1)
    sys.stderr.write("size=N/A time=%s bitrate=N/A\n" % stamp(seconds))
    sys.exit(0)
# Anything else is the plain track listing (ffmpeg -i with no output).
sys.stderr.write(streams_text())
sys.exit(1)
'''


class FakeMediaFfmpegTestCase(FakeFfmpegTestCase):
    """Adds the scenario-driven fake ffmpeg as self.media_ffmpeg."""

    def setUp(self) -> None:
        super().setUp()
        self.media_ffmpeg = str(self.tmp / "fake-media-ffmpeg")
        Path(self.media_ffmpeg).write_text(
            FAKE_MEDIA_FFMPEG_SOURCE.replace("@PYTHON@", sys.executable),
            encoding="utf-8",
        )
        os.chmod(
            self.media_ffmpeg, os.stat(self.media_ffmpeg).st_mode | stat.S_IEXEC
        )

    def session_with(
        self,
        camera: bytes = b"VIDEO",
        screen: bytes = b"VIDEO",
        mic: bytes = b"WAVFULL",
        system: bytes = b"WAVFULL",
        final: bytes = b"TWOTRACKS",
    ) -> Path:
        """A session folder whose five files use the given scenarios."""
        folder = self.tmp / "media-session"
        folder.mkdir(exist_ok=True)
        for name, content in (
            (CAMERA_FILENAME, camera),
            (SCREEN_FILENAME, screen),
            (MIC_FILENAME, mic),
            (SYSTEM_FILENAME, system),
            (FINAL_FILENAME, final),
        ):
            (folder / name).write_bytes(content + b" data")
        return folder


class FinalAudioTests(FakeMediaFfmpegTestCase):
    def check_final(self, content: bytes):
        path = self.write(self.tmp, "final.mp4", content + b" data")
        return verify.check_final_audio(path, self.media_ffmpeg)

    def test_two_separate_tracks_pass(self) -> None:
        results = self.check_final(b"TWOTRACKS")

        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.ok for r in results))
        self.assertFalse(any(r.warning for r in results))
        self.assertIn("2 separate audio tracks", results[0].detail)
        self.assertIn("(microphone)", results[1].name)
        self.assertIn("(system audio)", results[2].name)

    def test_each_track_is_measured_on_its_own(self) -> None:
        results = self.check_final(b"TWOTRACKS")

        self.assertIn("-3.2 dB", results[1].detail)
        self.assertIn("-5.0 dB", results[2].detail)

    def test_a_single_track_fails(self) -> None:
        results = self.check_final(b"ONETRACK")

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn("1 audio track", results[0].detail)
        self.assertIn("expected 2", results[0].detail)

    def test_no_audio_track_fails(self) -> None:
        results = self.check_final(b"VIDEO")

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn("0 audio tracks", results[0].detail)

    def test_one_silent_track_is_only_a_warning(self) -> None:
        results = self.check_final(b"SILENTSYS")

        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.ok for r in results))
        self.assertFalse(results[1].warning)
        self.assertTrue(results[2].warning)
        self.assertTrue(results[2].silent)
        self.assertIn("silent", results[2].detail)

    def test_both_tracks_silent_fails(self) -> None:
        results = self.check_final(b"BOTHSILENT")

        self.assertEqual(len(results), 4)
        self.assertTrue(results[1].ok)
        self.assertTrue(results[2].ok)
        self.assertFalse(results[3].ok)
        self.assertIn("both are silent", results[3].detail)


class FiveFileSessionTests(FakeMediaFfmpegTestCase):
    def verify(self, folder: Path, **kwargs):
        return verify.verify_session(folder, self.media_ffmpeg, **kwargs)

    def test_audio_option_reports_the_wav_files_and_the_final_tracks(self) -> None:
        check = self.verify(self.session_with(), with_audio=True)
        names = [f.name for f in check.files]

        self.assertTrue(check.ok)
        self.assertEqual(
            names[:5],
            [
                CAMERA_FILENAME,
                SCREEN_FILENAME,
                MIC_FILENAME,
                SYSTEM_FILENAME,
                FINAL_FILENAME,
            ],
        )
        self.assertIn("mic.wav audio (microphone)", names)
        self.assertIn("system.wav audio (system audio)", names)
        self.assertIn("final.mp4 audio tracks", names)
        self.assertIn("final.mp4 audio (microphone)", names)
        self.assertIn("final.mp4 audio (system audio)", names)

    def test_the_video_only_files_have_no_audio_measurement(self) -> None:
        check = self.verify(self.session_with(), with_audio=True)
        names = [f.name for f in check.files]

        self.assertFalse(
            [n for n in names if n.startswith(("camera.mp4 audio", "screen.mp4 audio"))]
        )

    def test_a_silent_wav_file_is_only_a_warning(self) -> None:
        check = self.verify(self.session_with(mic=b"WAVSILENT"), with_audio=True)
        by_name = {f.name: f for f in check.files}
        mic = by_name["mic.wav audio (microphone)"]

        self.assertTrue(check.ok)
        self.assertTrue(mic.warning)
        self.assertTrue(mic.silent)

    def test_a_final_video_with_one_audio_track_fails(self) -> None:
        check = self.verify(self.session_with(final=b"ONETRACK"), with_audio=True)

        self.assertFalse(check.ok)
        self.assertEqual(
            [f.name for f in check.failed], ["final.mp4 audio tracks"]
        )

    def test_lengths_option_checks_the_wav_files_against_the_screen(self) -> None:
        check = self.verify(self.session_with(), with_lengths=True)
        by_name = {f.name: f for f in check.files}

        self.assertTrue(check.ok)
        self.assertIn(
            "matches the screen recording length", by_name["mic.wav length"].detail
        )
        self.assertIn(
            "matches the screen recording length", by_name["system.wav length"].detail
        )
        self.assertIn(
            "audio and video lengths match", by_name["final.mp4 length"].detail
        )

    def test_a_wav_file_much_shorter_than_the_screen_fails(self) -> None:
        check = self.verify(self.session_with(mic=b"WAVSHORT"), with_lengths=True)
        by_name = {f.name: f for f in check.files}

        self.assertFalse(check.ok)
        self.assertFalse(by_name["mic.wav length"].ok)
        self.assertIn("dropped", by_name["mic.wav length"].detail)
        self.assertTrue(by_name["system.wav length"].ok)

    def test_a_wav_file_slightly_shorter_than_the_screen_only_warns(self) -> None:
        check = self.verify(self.session_with(system=b"WAVNEAR"), with_lengths=True)
        by_name = {f.name: f for f in check.files}

        self.assertTrue(check.ok)
        self.assertTrue(by_name["system.wav length"].warning)
        self.assertIn("may have been dropped", by_name["system.wav length"].detail)

    def test_final_audio_shorter_than_its_video_fails(self) -> None:
        check = self.verify(self.session_with(final=b"DROPPED"), with_lengths=True)
        by_name = {f.name: f for f in check.files}

        self.assertFalse(check.ok)
        self.assertFalse(by_name["final.mp4 length"].ok)
        self.assertIn("dropped", by_name["final.mp4 length"].detail)

    def test_a_wav_length_without_a_reference_is_just_reported(self) -> None:
        path = self.write(self.tmp, "mic.wav", b"WAVFULL data")
        result = verify.check_length(path, self.media_ffmpeg)

        self.assertTrue(result.ok)
        self.assertFalse(result.warning)
        self.assertIn("1:00 long", result.detail)

    def test_min_minutes_applies_to_the_wav_files_too(self) -> None:
        check = self.verify(self.session_with(), min_minutes=5)
        by_name = {f.name: f for f in check.files}

        self.assertFalse(check.ok)
        self.assertFalse(by_name["mic.wav length"].ok)
        self.assertIn("shorter than the required", by_name["mic.wav length"].detail)

    def test_command_line_reports_on_all_five_files(self) -> None:
        folder = self.session_with()
        out = io.StringIO()
        with mock.patch.object(
            verify, "find_ffmpeg", return_value=self.media_ffmpeg
        ):
            with contextlib.redirect_stdout(out):
                code = verify.main([str(folder), "--audio", "--lengths"])
        report = out.getvalue()

        self.assertEqual(code, 0)
        for name in (
            "camera.mp4", "screen.mp4", "mic.wav", "system.wav", "final.mp4"
        ):
            self.assertIn(f"] {name} ", report)
        self.assertIn("final.mp4 audio tracks", report)


class CommandLineTests(FakeFfmpegTestCase):
    def run_main(self, folder: Path) -> "tuple[int, str, str]":
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(verify, "find_ffmpeg", return_value=self.ffmpeg):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = verify.main([str(folder)])
        return code, out.getvalue(), err.getvalue()

    def test_exit_status_0_when_all_files_are_playable(self) -> None:
        code, out, _ = self.run_main(self.make_session_folder())
        self.assertEqual(code, 0)
        self.assertIn("All 5 files are playable.", out)

    def test_exit_status_1_when_a_file_fails(self) -> None:
        code, out, _ = self.run_main(self.make_session_folder(camera=b"NOMOOV"))
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] camera.mp4", out)

    def test_exit_status_2_when_the_folder_does_not_exist(self) -> None:
        code, _, err = self.run_main(self.tmp / "no-such-folder")
        self.assertEqual(code, 2)
        self.assertIn("not found", err)


class FormatDurationTests(unittest.TestCase):
    def test_formats(self) -> None:
        self.assertEqual(verify.format_duration(None), "")
        self.assertEqual(verify.format_duration(45), "0:45")
        self.assertEqual(verify.format_duration(125), "2:05")
        self.assertEqual(verify.format_duration(3723), "1:02:03")


if __name__ == "__main__":
    unittest.main()