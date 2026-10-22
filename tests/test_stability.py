"""Tests for the long-recording safeguards in recorder/stability.py.

Run from the project folder with the standard library only:

    python3 -m unittest discover -s tests -v

Nothing here needs ffmpeg, a Mac or real waiting: the capture monitor is given
fake processes (plain functions), a fake clock and a fake free-space reader,
and the keep-awake helper is given a fake Popen.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make `import recorder` work when the tests are started from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recorder import stability  # noqa: E402
from recorder.stability import (  # noqa: E402
    CaptureMonitor,
    KeepAwake,
    ProblemKind,
    Watch,
)

GIB = stability.GIB
MIB = stability.MIB


class DiskSpaceEstimateTests(unittest.TestCase):
    def test_parse_bitrate(self):
        self.assertEqual(stability.parse_bitrate("8M"), 8_000_000)
        self.assertEqual(stability.parse_bitrate("160k"), 160_000)
        self.assertEqual(stability.parse_bitrate("1.5M"), 1_500_000)
        self.assertEqual(stability.parse_bitrate("500"), 500)
        self.assertEqual(stability.parse_bitrate("fast"), 0)
        self.assertEqual(stability.parse_bitrate(None), 0)

    def test_estimate_grows_with_length(self):
        short = stability.estimate_recording_bytes(10, "medium")
        long = stability.estimate_recording_bytes(30, "medium")
        self.assertGreater(short, 0)
        self.assertAlmostEqual(long / short, 3.0, places=2)

    def test_estimate_grows_with_quality(self):
        low = stability.estimate_recording_bytes(30, "low")
        medium = stability.estimate_recording_bytes(30, "medium")
        high = stability.estimate_recording_bytes(30, "high")
        self.assertLess(low, medium)
        self.assertLess(medium, high)

    def test_unknown_quality_means_the_default(self):
        self.assertEqual(
            stability.estimate_recording_bytes(30, "bogus"),
            stability.estimate_recording_bytes(30, stability.DEFAULT_QUALITY),
        )

    def test_final_video_adds_space(self):
        with_final = stability.estimate_recording_bytes(30, "medium", True)
        without = stability.estimate_recording_bytes(30, "medium", False)
        self.assertGreater(with_final, without)

    def test_estimate_includes_the_safety_margin(self):
        per_second = stability.recording_bytes_per_second("medium")
        expected = int(60 * 60 * per_second * stability.SAFETY_MARGIN)
        self.assertEqual(stability.estimate_recording_bytes(60, "medium"), expected)

    def test_bad_minutes_give_zero(self):
        self.assertEqual(stability.estimate_recording_bytes("soon"), 0)
        self.assertEqual(stability.estimate_recording_bytes(-5), 0)

    def test_minutes_of_space_matches_the_estimate(self):
        needed = stability.estimate_recording_bytes(30, "medium")
        self.assertAlmostEqual(stability.minutes_of_space(needed, "medium"), 30, places=1)
        self.assertEqual(stability.minutes_of_space(-1, "medium"), 0.0)

    def test_format_bytes(self):
        self.assertEqual(stability.format_bytes(512 * MIB), "512 MB")
        self.assertEqual(stability.format_bytes(3 * GIB), "3.0 GB")
        self.assertEqual(stability.format_bytes("many"), "unknown")

    def test_format_elapsed(self):
        self.assertEqual(stability.format_elapsed(0), "0:00")
        self.assertEqual(stability.format_elapsed(425), "7:05")
        self.assertEqual(stability.format_elapsed(3723), "1:02:03")
        self.assertEqual(stability.format_elapsed(-4), "0:00")
        self.assertEqual(stability.format_elapsed("x"), "0:00")


class SpaceCheckTests(unittest.TestCase):
    def test_enough_space(self):
        with mock.patch.object(stability, "free_bytes", return_value=500 * GIB):
            check = stability.check_space(Path("/anywhere"), 30, "medium")
        self.assertTrue(check.enough)
        self.assertEqual(check.message(), "")

    def test_not_enough_space_explains_what_fits(self):
        needed = stability.estimate_recording_bytes(30, "medium")
        with mock.patch.object(stability, "free_bytes", return_value=needed // 2):
            check = stability.check_space(Path("/anywhere"), 30, "medium")
        self.assertFalse(check.enough)
        message = check.message()
        self.assertIn("Only", message)
        self.assertIn("minute", message)
        self.assertIn("Settings", message)
        self.assertLess(check.minutes_fit, 30)

    def test_unknown_free_space_never_blocks(self):
        with mock.patch.object(stability, "free_bytes", return_value=None):
            check = stability.check_space(Path("/anywhere"), 30, "medium")
        self.assertTrue(check.enough)
        self.assertEqual(check.message(), "")

    def test_free_bytes_uses_the_nearest_existing_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = stability.free_bytes(Path(tmp) / "not" / "created" / "yet")
        self.assertIsInstance(value, int)


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class MonitorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.clock = FakeClock()
        self.free = 100 * GIB
        self.alive = {"camera": True, "screen": True}
        self.reported = []
        self.monitors = []

    def make_file(self, name: str, size: int = 100) -> Path:
        path = self.folder / name
        path.write_bytes(b"x" * size)
        return path

    def make_monitor(self, on_problem=None, **kwargs) -> CaptureMonitor:
        watches = [
            Watch(
                "camera",
                self.make_file("camera.mp4"),
                lambda: self.alive["camera"],
                explain_exit=lambda: "The camera was unplugged.",
            ),
            Watch("screen", self.make_file("screen.mp4"), lambda: self.alive["screen"]),
        ]
        monitor = CaptureMonitor(
            watches,
            on_problem or self.reported.append,
            disk_folder=self.folder,
            # The thread never ticks by itself; tests call check_once().
            interval=3600,
            stall_seconds=30,
            warn_free_bytes=2 * GIB,
            critical_free_bytes=300 * MIB,
            clock=self.clock,
            free_space=lambda _folder: self.free,
            **kwargs,
        )
        monitor.start()
        self.addCleanup(monitor.stop)
        self.monitors.append(monitor)
        return monitor

    def grow(self, name: str, extra: int = 100) -> None:
        with open(self.folder / name, "ab") as handle:
            handle.write(b"x" * extra)


class HealthyRecordingTests(MonitorTestCase):
    def test_nothing_reported_while_healthy(self):
        monitor = self.make_monitor()
        for _ in range(5):
            self.clock.now += 5
            self.grow("camera.mp4")
            self.grow("screen.mp4")
            self.assertEqual(monitor.check_once(), [])
        self.assertEqual(self.reported, [])
        self.assertEqual(monitor.problems, [])

    def test_the_thread_runs_and_stops(self):
        monitor = self.make_monitor()
        self.assertTrue(monitor.running)
        monitor.stop()
        self.assertFalse(monitor.running)
        monitor.stop()  # safe to repeat


class ProcessExitTests(MonitorTestCase):
    def test_early_exit_is_fatal_and_names_the_capture(self):
        monitor = self.make_monitor()
        self.alive["camera"] = False
        new = monitor.check_once()
        self.assertEqual(len(new), 1)
        problem = new[0]
        self.assertEqual(problem.kind, ProblemKind.PROCESS_EXITED)
        self.assertTrue(problem.fatal)
        self.assertEqual(problem.source, "camera")
        self.assertIn("camera recording stopped unexpectedly", problem.message)
        self.assertIn("The camera was unplugged.", problem.message)
        self.assertIn("kept", problem.message)
        self.assertEqual(self.reported, [problem])

    def test_a_problem_is_reported_only_once(self):
        monitor = self.make_monitor()
        self.alive["screen"] = False
        monitor.check_once()
        self.clock.now += 5
        self.assertEqual(monitor.check_once(), [])
        self.assertEqual(len(self.reported), 1)

    def test_both_processes_can_be_reported(self):
        monitor = self.make_monitor()
        self.alive["camera"] = False
        self.alive["screen"] = False
        monitor.check_once()
        self.assertEqual({p.source for p in self.reported}, {"camera", "screen"})

    def test_exit_after_stop_is_not_a_failure(self):
        monitor = self.make_monitor()
        monitor.stop()
        self.alive["camera"] = False
        self.alive["screen"] = False
        self.assertEqual(monitor.check_once(), [])
        self.assertEqual(self.reported, [])


class StallTests(MonitorTestCase):
    def test_a_file_that_stops_growing_is_reported(self):
        monitor = self.make_monitor()
        self.clock.now = 10
        self.grow("camera.mp4")  # camera keeps growing, screen does not
        self.assertEqual(monitor.check_once(), [])
        self.clock.now = 31
        self.grow("camera.mp4")
        new = monitor.check_once()
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].kind, ProblemKind.FILE_STALLED)
        self.assertTrue(new[0].fatal)
        self.assertEqual(new[0].source, "screen")
        self.assertIn("has not grown", new[0].message)

    def test_growth_resets_the_stall_timer(self):
        monitor = self.make_monitor()
        for _ in range(6):
            self.clock.now += 20
            self.grow("camera.mp4")
            self.grow("screen.mp4")
            self.assertEqual(monitor.check_once(), [])

    def test_stalled_just_below_the_limit_is_fine(self):
        monitor = self.make_monitor()
        self.clock.now = 29
        self.assertEqual(monitor.check_once(), [])

    def test_an_empty_file_is_described_as_not_written(self):
        monitor = self.make_monitor()
        (self.folder / "screen.mp4").write_bytes(b"")
        # The monitor started when screen.mp4 already had data, so restart
        # watching with an empty file.
        monitor.stop()
        fresh = self.make_monitor()
        self.clock.now += 31
        self.grow("camera.mp4")
        new = fresh.check_once()
        self.assertEqual([p.source for p in new], ["screen"])
        self.assertIn("has not been written", new[0].message)


class DiskSpaceTests(MonitorTestCase):
    def test_low_space_is_a_non_fatal_warning(self):
        monitor = self.make_monitor()
        self.free = 1 * GIB
        new = monitor.check_once()
        self.assertEqual([p.kind for p in new], [ProblemKind.LOW_DISK_SPACE])
        self.assertFalse(new[0].fatal)
        self.assertIn("running low", new[0].message)

    def test_nearly_full_disk_is_fatal(self):
        monitor = self.make_monitor()
        self.free = 100 * MIB
        new = monitor.check_once()
        self.assertEqual([p.kind for p in new], [ProblemKind.DISK_NEARLY_FULL])
        self.assertTrue(new[0].fatal)
        self.assertIn("almost full", new[0].message)

    def test_warning_then_critical_are_both_reported(self):
        monitor = self.make_monitor()
        self.free = 1 * GIB
        monitor.check_once()
        self.clock.now += 5
        self.free = 100 * MIB
        monitor.check_once()
        self.assertEqual(
            [p.kind for p in monitor.problems],
            [ProblemKind.LOW_DISK_SPACE, ProblemKind.DISK_NEARLY_FULL],
        )

    def test_unreadable_free_space_never_stops_a_recording(self):
        monitor = self.make_monitor()
        self.free = None
        self.assertEqual(monitor.check_once(), [])


class NeverRaisesTests(MonitorTestCase):
    def test_a_failing_callback_does_not_break_the_monitor(self):
        def broken(_problem):
            raise RuntimeError("listener bug")

        monitor = self.make_monitor(on_problem=broken)
        self.alive["camera"] = False
        new = monitor.check_once()  # must not raise
        self.assertEqual(len(new), 1)
        self.assertEqual(len(monitor.problems), 1)

    def test_a_failing_process_check_is_not_a_false_alarm(self):
        def explode():
            raise OSError("cannot tell")

        watches = [Watch("camera", self.make_file("camera.mp4"), explode)]
        monitor = CaptureMonitor(
            watches,
            self.reported.append,
            disk_folder=self.folder,
            interval=3600,
            clock=self.clock,
            free_space=lambda _f: 100 * GIB,
        )
        monitor.start()
        self.addCleanup(monitor.stop)
        self.assertEqual(monitor.check_once(), [])

    def test_a_failing_explanation_still_reports_the_exit(self):
        def explode():
            raise ValueError("no log")

        watches = [
            Watch("screen", self.make_file("screen.mp4"), lambda: False, explode)
        ]
        monitor = CaptureMonitor(
            watches,
            self.reported.append,
            disk_folder=self.folder,
            interval=3600,
            clock=self.clock,
            free_space=lambda _f: 100 * GIB,
        )
        monitor.start()
        self.addCleanup(monitor.stop)
        new = monitor.check_once()
        self.assertEqual(len(new), 1)
        self.assertIn("screen recording stopped unexpectedly", new[0].message)

    def test_a_failing_free_space_reader_is_ignored(self):
        def explode(_folder):
            raise OSError("disk gone")

        watches = [Watch("camera", self.make_file("camera.mp4"), lambda: True)]
        monitor = CaptureMonitor(
            watches,
            self.reported.append,
            disk_folder=self.folder,
            interval=3600,
            clock=self.clock,
            free_space=explode,
        )
        monitor.start()
        self.addCleanup(monitor.stop)
        self.assertEqual(monitor.check_once(), [])

    def test_a_missing_file_counts_as_empty_not_an_error(self):
        watches = [Watch("camera", self.folder / "gone.mp4", lambda: True)]
        monitor = CaptureMonitor(
            watches,
            self.reported.append,
            disk_folder=self.folder,
            interval=3600,
            stall_seconds=30,
            clock=self.clock,
            free_space=lambda _f: 100 * GIB,
        )
        monitor.start()
        self.addCleanup(monitor.stop)
        self.clock.now = 31
        new = monitor.check_once()  # must not raise
        self.assertEqual([p.kind for p in new], [ProblemKind.FILE_STALLED])


class FakeProc:
    """A stand-in for subprocess.Popen."""

    def __init__(self, stubborn: bool = False) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._stubborn = stubborn

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self._stubborn:
            self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise TimeoutError("still running")
        return self.returncode


class KeepAwakeTests(unittest.TestCase):
    def make(self, **kwargs):
        self.launched = []
        self.procs = []

        def popen(command, **popen_kwargs):
            proc = FakeProc(**kwargs)
            self.launched.append((command, popen_kwargs))
            self.procs.append(proc)
            return proc

        return KeepAwake(command=["caffeinate", "-d", "-i"], popen=popen)

    def test_start_launches_and_stop_ends_it(self):
        keep = self.make()
        self.assertFalse(keep.active)
        self.assertTrue(keep.start())
        self.assertTrue(keep.active)
        self.assertEqual(self.launched[0][0], ["caffeinate", "-d", "-i"])
        keep.stop()
        self.assertFalse(keep.active)
        self.assertTrue(self.procs[0].terminated)

    def test_starting_twice_launches_once(self):
        keep = self.make()
        keep.start()
        self.assertTrue(keep.start())
        self.assertEqual(len(self.launched), 1)

    def test_stop_is_safe_to_repeat_and_before_start(self):
        keep = self.make()
        keep.stop()
        keep.start()
        keep.stop()
        keep.stop()
        self.assertFalse(keep.active)

    def test_can_start_again_after_stopping(self):
        keep = self.make()
        keep.start()
        keep.stop()
        self.assertTrue(keep.start())
        self.assertEqual(len(self.launched), 2)

    def test_a_process_that_will_not_stop_is_killed(self):
        keep = self.make(stubborn=True)
        keep.start()
        keep.stop()
        self.assertTrue(self.procs[0].killed)
        self.assertFalse(keep.active)

    def test_a_process_that_already_exited_is_not_active(self):
        keep = self.make()
        keep.start()
        self.procs[0].returncode = 0
        self.assertFalse(keep.active)
        self.assertTrue(keep.start())  # launches a fresh one
        self.assertEqual(len(self.launched), 2)

    def test_missing_caffeinate_returns_false_without_raising(self):
        keep = KeepAwake(popen=lambda *a, **k: self.fail("must not launch"))
        with mock.patch.object(stability.shutil, "which", return_value=None), \
                mock.patch.object(stability.os.path, "exists", return_value=False):
            self.assertFalse(keep.start())
        self.assertFalse(keep.active)
        keep.stop()

    def test_a_launch_failure_returns_false_without_raising(self):
        def popen(*_a, **_k):
            raise OSError("cannot launch")

        keep = KeepAwake(command=["caffeinate"], popen=popen)
        self.assertFalse(keep.start())
        self.assertFalse(keep.active)

    def test_default_command_ties_caffeinate_to_this_process(self):
        keep = KeepAwake(popen=lambda *a, **k: FakeProc())
        with mock.patch.object(
            stability.shutil, "which", return_value="/usr/bin/caffeinate"
        ):
            command = keep._build_command()
        self.assertEqual(command[0], "/usr/bin/caffeinate")
        self.assertIn("-w", command)
        self.assertEqual(command[command.index("-w") + 1], str(stability.os.getpid()))

    def test_context_manager_starts_and_stops(self):
        keep = self.make()
        with keep as active:
            self.assertIs(active, keep)
            self.assertTrue(keep.active)
        self.assertFalse(keep.active)


if __name__ == "__main__":
    unittest.main()