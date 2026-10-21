"""Tests for the session folder naming and the three-file verification.

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
    SCREEN_FILENAME,
    SYNC_FILENAME,
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
        """Folder with camera/screen/final files; pass camera=, screen=, final=.

        A file whose content is None is not created.
        """
        folder = self.tmp / "session"
        folder.mkdir(exist_ok=True)
        names = {
            "camera": CAMERA_FILENAME,
            "screen": SCREEN_FILENAME,
            "final": FINAL_FILENAME,
        }
        for key, name in names.items():
            content = contents.get(key, b"GOOD data")
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

    def test_creates_timestamped_folder_with_the_three_file_paths(self) -> None:
        when = datetime(2026, 10, 21, 14, 46, 5)
        session = create_session(self.root, now=when)

        self.assertEqual(session.folder, self.root / "2026-10-21_14-46")
        self.assertTrue(session.folder.is_dir())
        self.assertEqual(session.camera_path, session.folder / "camera.mp4")
        self.assertEqual(session.screen_path, session.folder / "screen.mp4")
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

    def test_missing_ffmpeg_raises_verify_error(self) -> None:
        path = self.write(self.tmp, "good.mp4", b"GOOD data")
        with self.assertRaises(verify.VerifyError):
            verify.check_file(path, str(self.tmp / "no-such-ffmpeg"))


class VerifySessionTests(FakeFfmpegTestCase):
    def test_three_playable_files_pass(self) -> None:
        folder = self.make_session_folder()
        check = verify.verify_session(folder, self.ffmpeg)

        self.assertTrue(check.ok)
        self.assertEqual(
            [f.name for f in check.files],
            [CAMERA_FILENAME, SCREEN_FILENAME, FINAL_FILENAME],
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

    def test_missing_session_folder_raises_verify_error(self) -> None:
        with self.assertRaises(verify.VerifyError):
            verify.verify_session(self.tmp / "no-such-folder", self.ffmpeg)

    def test_report_lists_pass_and_fail_lines(self) -> None:
        folder = self.make_session_folder(screen=b"NOMOOV")
        report = verify.format_report(verify.verify_session(folder, self.ffmpeg))

        self.assertIn("[PASS] camera.mp4", report)
        self.assertIn("[FAIL] screen.mp4", report)
        self.assertIn("[PASS] final.mp4", report)
        self.assertIn("1 of 3 files failed", report)

    def test_report_for_a_good_session(self) -> None:
        folder = self.make_session_folder()
        report = verify.format_report(verify.verify_session(folder, self.ffmpeg))
        self.assertIn("All 3 files are playable.", report)


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
        self.assertIn("All 3 files are playable.", out)

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