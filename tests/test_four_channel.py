"""Tests for the four-stream recording layout (no Mac or real ffmpeg needed).

Run from the project folder with the standard library only:

    python3 -m unittest discover -s tests -v

They cover the four-file Session layout, the video-only camera and screen
commands, the WAV audio command builders, the launch offsets measured by
MultiCapture, the two-track filter graph (no amix, per-stream shifts, titled
tracks), the per-stream offsets in sync.json (including loading an old
two-file sync.json) and the recomposite --mic-offset / --system-offset flags.
Everything runs against fake processes and temporary folders.
"""

import contextlib
import io
import json
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

from recorder import capture, compositor, encoding, recomposite, session, sync  # noqa: E402
from recorder.app_settings import AppSettings  # noqa: E402
from recorder.devices import Device, SelectedDevices  # noqa: E402

FFMPEG = "ffmpeg"

DEVICES = SelectedDevices(
    camera=Device(index=0, name="FaceTime HD Camera"),
    microphone=Device(index=3, name="MacBook Microphone"),
    screen=Device(index=1, name="Capture screen 0"),
    system_audio=Device(index=5, name="BlackHole 2ch"),
)


def _hardware_encoder_cache():
    """Pretend ffmpeg has the hardware encoder, so no ffmpeg is ever run."""
    return mock.patch.dict(encoding._hardware_cache, {FFMPEG: True})


class SessionLayoutTests(unittest.TestCase):
    def test_create_session_returns_all_four_raw_paths_plus_final_and_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                session.shutil, "disk_usage",
                return_value=mock.Mock(free=session.MIN_FREE_BYTES * 10),
            ):
                made = session.create_session(
                    Path(tmp), now=datetime(2026, 10, 24, 9, 30)
                )

            folder = Path(tmp) / "2026-10-24_09-30"
            self.assertTrue(folder.is_dir())
            self.assertEqual(made.folder, folder)
            self.assertEqual(made.camera_path, folder / "camera.mp4")
            self.assertEqual(made.screen_path, folder / "screen.mp4")
            self.assertEqual(made.mic_path, folder / "mic.wav")
            self.assertEqual(made.system_path, folder / "system.wav")
            self.assertEqual(made.final_path, folder / "final.mp4")
            self.assertEqual(made.sync_path, folder / "sync.json")

    def test_filename_constants(self) -> None:
        self.assertEqual(session.MIC_FILENAME, "mic.wav")
        self.assertEqual(session.SYSTEM_FILENAME, "system.wav")


class CommandBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = _hardware_encoder_cache()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_camera_and_screen_commands_are_video_only(self) -> None:
        for name, cmd, index in (
            ("camera", capture.build_camera_command(
                FFMPEG, DEVICES, Path("camera.mp4")), 0),
            ("screen", capture.build_screen_command(
                FFMPEG, DEVICES, Path("screen.mp4")), 1),
        ):
            with self.subTest(stream=name):
                self.assertIn("-an", cmd)
                # The video device is opened with no audio device.
                self.assertIn(f"{index}:none", cmd)
                self.assertNotIn("-c:a", cmd)
                # Fragmented MP4 keeps crash safety.
                self.assertIn(capture.MOVFLAGS, cmd)

    def test_audio_commands_write_crash_tolerant_wav(self) -> None:
        for name, cmd, index, output in (
            ("mic", capture.build_mic_command(
                FFMPEG, DEVICES, Path("mic.wav")), 3, "mic.wav"),
            ("system", capture.build_system_audio_command(
                FFMPEG, DEVICES, Path("system.wav")), 5, "system.wav"),
        ):
            with self.subTest(stream=name):
                self.assertEqual(cmd[0], FFMPEG)
                self.assertEqual(cmd[-1], output)
                # Audio device only, no video device and no video stream.
                self.assertIn(f"none:{index}", cmd)
                self.assertIn("-vn", cmd)
                self.assertNotIn("-c:v", cmd)
                # 48 kHz 16-bit PCM WAV.
                self.assertEqual(cmd[cmd.index("-c:a") + 1], "pcm_s16le")
                self.assertEqual(cmd[cmd.index("-ar") + 1], "48000")
                self.assertEqual(cmd[cmd.index("-f", cmd.index("-flush_packets")) + 1], "wav")
                # Flushed to disk as it is recorded.
                self.assertEqual(cmd[cmd.index("-flush_packets") + 1], "1")
                self.assertEqual(cmd[cmd.index("-rf64") + 1], "auto")

    def test_mic_and_system_use_different_devices(self) -> None:
        mic = capture.build_mic_command(FFMPEG, DEVICES, Path("m.wav"))
        system = capture.build_system_audio_command(FFMPEG, DEVICES, Path("s.wav"))

        self.assertIn("none:3", mic)
        self.assertNotIn("none:5", mic)
        self.assertIn("none:5", system)
        self.assertNotIn("none:3", system)


class _FakeProcess:
    """A stand-in for subprocess.Popen: alive unless told it exited."""

    def __init__(self, exit_code=None) -> None:
        self.exit_code = exit_code
        self.returncode = exit_code
        self.stdin = mock.Mock()

    def poll(self):
        return self.exit_code

    def wait(self, timeout=None):
        return self.exit_code if self.exit_code is not None else 0

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


def _make_capture(tmp: str) -> capture.MultiCapture:
    folder = Path(tmp)
    return capture.MultiCapture(
        DEVICES,
        folder / "camera.mp4",
        folder / "screen.mp4",
        folder / "mic.wav",
        folder / "system.wav",
        ffmpeg_path=FFMPEG,
    )


class MultiCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = _hardware_encoder_cache()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _start(self, monotonic_values, exit_codes=None):
        """Start a MultiCapture against fake processes.

        monotonic_values are returned one by one: each of the four launches
        reads the clock twice (before and after Popen), in the order camera,
        screen, mic, system. exit_codes maps a command's output file name to
        the exit code of a process that died at startup.
        """
        exit_codes = exit_codes or {}
        launched = []

        def fake_popen(cmd, **kwargs):
            proc = _FakeProcess(exit_codes.get(Path(cmd[-1]).name))
            launched.append(cmd)
            return proc

        fake_time = mock.Mock()
        fake_time.monotonic.side_effect = list(monotonic_values)
        fake_time.sleep = mock.Mock()

        with tempfile.TemporaryDirectory() as tmp:
            cap = _make_capture(tmp)
            with mock.patch.object(capture, "time", fake_time), \
                    mock.patch.object(capture.subprocess, "Popen", fake_popen):
                try:
                    cap.start()
                    error = None
                except capture.CaptureError as exc:
                    error = exc
            for proc in cap._processes:
                proc.close_log()
            return cap, launched, error

    def test_four_processes_are_launched_in_order(self) -> None:
        _, launched, error = self._start(range(8))

        self.assertIsNone(error)
        self.assertEqual(
            [Path(cmd[-1]).name for cmd in launched],
            ["camera.mp4", "screen.mp4", "mic.wav", "system.wav"],
        )

    def test_launch_offsets_are_relative_to_the_first_launch(self) -> None:
        # (start, returned) per process: camera, screen, mic, system.
        clock = [10.00, 10.00, 10.10, 10.10, 10.30, 10.30, 10.35, 10.35]
        cap, _, error = self._start(clock)

        self.assertIsNone(error)
        offsets = cap.launch_offsets_seconds
        self.assertEqual(set(offsets), set(sync.STREAM_NAMES))
        self.assertAlmostEqual(offsets["camera"], 0.0)
        self.assertAlmostEqual(offsets["screen"], 0.10)
        self.assertAlmostEqual(offsets["mic"], 0.30)
        self.assertAlmostEqual(offsets["system"], 0.35)

    def test_first_launched_stream_has_offset_zero_and_none_is_negative(self) -> None:
        # The microphone happens to be launched first here.
        clock = [5.2, 5.2, 5.3, 5.3, 5.0, 5.0, 5.4, 5.4]
        cap, _, _ = self._start(clock)

        offsets = cap.launch_offsets_seconds
        self.assertAlmostEqual(offsets["mic"], 0.0)
        self.assertTrue(all(value >= 0 for value in offsets.values()))

    def test_launch_gap_is_screen_minus_camera(self) -> None:
        clock = [1.0, 1.0, 1.25, 1.25, 1.5, 1.5, 1.6, 1.6]
        cap, _, _ = self._start(clock)

        self.assertAlmostEqual(cap.launch_gap_seconds, 0.25)

    def test_offsets_are_empty_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cap = _make_capture(tmp)
            for proc in cap._processes:
                proc.close_log()

        self.assertEqual(cap.launch_offsets_seconds, {})
        self.assertIsNone(cap.launch_gap_seconds)

    def test_raw_paths_lists_all_four_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cap = _make_capture(tmp)
            names = [path.name for path in cap.raw_paths]
            for proc in cap._processes:
                proc.close_log()

        self.assertEqual(names, ["camera.mp4", "screen.mp4", "mic.wav", "system.wav"])

    def test_a_failed_stream_is_named_in_the_start_error(self) -> None:
        _, _, error = self._start(range(8), exit_codes={"system.wav": 1})

        self.assertIsInstance(error, capture.CaptureError)
        self.assertIn("system", str(error).lower())

    def test_running_needs_all_four_processes_alive(self) -> None:
        cap, _, _ = self._start(range(8))
        # Started processes were fake and alive; the object keeps its state.
        self.assertTrue(cap.is_running())

    def test_dual_capture_alias_still_resolves(self) -> None:
        self.assertIs(capture.DualCapture, capture.MultiCapture)


class TwoTrackFilterGraphTests(unittest.TestCase):
    def build(self, **kwargs):
        kwargs.setdefault("pip_width", compositor.DEFAULT_PIP_WIDTH)
        kwargs.setdefault("margin", compositor.DEFAULT_PIP_MARGIN)
        return compositor.build_filter_graph(**kwargs)

    def test_audio_is_never_mixed(self) -> None:
        graph, labels = self.build(mic_offset=0.2, system_offset=-0.1)

        self.assertNotIn("amix", graph)
        self.assertNotIn("amerge", graph)
        self.assertEqual(labels, ["[mic]", "[sys]"])

    def test_each_audio_input_is_resampled_to_its_own_output(self) -> None:
        graph, _ = self.build()
        rate = compositor.MIX_SAMPLE_RATE

        self.assertIn(f"[2:a]aresample={rate}:async=1:first_pts=0[mic]", graph)
        self.assertIn(f"[3:a]aresample={rate}:async=1:first_pts=0[sys]", graph)

    def test_zero_offsets_add_no_shift_filters(self) -> None:
        graph, _ = self.build()

        for token in ("adelay", "atrim", "setpts=PTS+", "trim="):
            with self.subTest(token=token):
                self.assertNotIn(token, graph)

    def test_positive_mic_offset_delays_only_the_mic(self) -> None:
        graph, _ = self.build(mic_offset=0.25)

        self.assertIn("[2:a]aresample=48000:async=1:first_pts=0,adelay=250:all=1[mic]", graph)
        self.assertIn("[3:a]aresample=48000:async=1:first_pts=0[sys]", graph)

    def test_negative_system_offset_trims_only_the_system_audio(self) -> None:
        graph, _ = self.build(system_offset=-0.4)

        self.assertIn(
            "[3:a]aresample=48000:async=1:first_pts=0,"
            "atrim=start=0.400,asetpts=PTS-STARTPTS[sys]",
            graph,
        )
        self.assertIn("[2:a]aresample=48000:async=1:first_pts=0[mic]", graph)

    def test_offsets_are_independent_for_each_stream(self) -> None:
        graph, _ = self.build(camera_offset=0.5, mic_offset=-0.1, system_offset=0.3)

        # Camera video is delayed, microphone is advanced, system is delayed.
        self.assertIn("[1:v]setpts=PTS+0.500/TB,scale=", graph)
        self.assertIn("atrim=start=0.100,asetpts=PTS-STARTPTS[mic]", graph)
        self.assertIn("adelay=300:all=1[sys]", graph)

    def test_screen_is_the_unshifted_reference(self) -> None:
        graph, _ = self.build(camera_offset=0.5, mic_offset=0.2, system_offset=0.3)

        self.assertIn("[0:v][pip]overlay=", graph)
        self.assertNotIn("[0:v]setpts", graph)
        self.assertNotIn("[0:v]trim", graph)

    def test_camera_overlay_is_still_picture_in_picture(self) -> None:
        graph, _ = self.build()

        self.assertIn("[1:v]scale=320:-2[pip]", graph)
        self.assertIn("overlay=W-w-20:H-h-20,format=yuv420p[v]", graph)


class CompositeCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = _hardware_encoder_cache()
        patcher.start()
        self.addCleanup(patcher.stop)

    def command(self, **kwargs):
        return compositor.build_composite_command(
            FFMPEG,
            Path("screen.mp4"),
            Path("camera.mp4"),
            Path("mic.wav"),
            Path("system.wav"),
            Path("final.mp4"),
            **kwargs,
        )

    def test_inputs_are_screen_camera_mic_system_in_that_order(self) -> None:
        cmd = self.command()
        inputs = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-i"]

        self.assertEqual(inputs, ["screen.mp4", "camera.mp4", "mic.wav", "system.wav"])

    def test_two_audio_tracks_are_mapped_separately(self) -> None:
        cmd = self.command()
        maps = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-map"]

        self.assertEqual(maps, ["[v]", "[mic]", "[sys]"])
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")

    def test_tracks_are_titled_and_the_mic_is_the_default(self) -> None:
        cmd = self.command()

        self.assertEqual(cmd[cmd.index("-metadata:s:a:0") + 1], "title=Microphone")
        self.assertEqual(cmd[cmd.index("-metadata:s:a:1") + 1], "title=System audio")
        self.assertEqual(cmd[cmd.index("-disposition:a:0") + 1], "default")
        self.assertEqual(cmd[cmd.index("-disposition:a:1") + 1], "0")

    def test_offsets_reach_the_filter_graph(self) -> None:
        cmd = self.command(camera_offset=0.1, mic_offset=0.2, system_offset=-0.3)
        graph = cmd[cmd.index("-filter_complex") + 1]

        self.assertIn("setpts=PTS+0.100/TB", graph)
        self.assertIn("adelay=200:all=1[mic]", graph)
        self.assertIn("atrim=start=0.300,asetpts=PTS-STARTPTS[sys]", graph)

    def test_composite_requires_all_four_inputs(self) -> None:
        names = {
            "screen": "screen.mp4",
            "camera": "camera.mp4",
            "microphone": "mic.wav",
            "system audio": "system.wav",
        }
        for missing, filename in names.items():
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                for name in names.values():
                    if name != filename:
                        (folder / name).write_bytes(b"data")

                with self.assertRaises(compositor.CompositeError) as caught:
                    compositor.composite(
                        folder / "screen.mp4",
                        folder / "camera.mp4",
                        folder / "mic.wav",
                        folder / "system.wav",
                        folder / "final.mp4",
                        ffmpeg_path=FFMPEG,
                    )

                self.assertIn(missing, str(caught.exception))
                self.assertIn(filename, str(caught.exception))


class SyncOffsetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sync.json"

    def test_defaults_when_the_file_is_missing(self) -> None:
        info = sync.load_sync(self.path)

        self.assertEqual(info.camera_offset_seconds, 0.0)
        self.assertEqual(info.mic_offset_seconds, 0.0)
        self.assertEqual(info.system_offset_seconds, 0.0)
        self.assertEqual(info.launch_offsets_seconds, {})
        self.assertIsNone(info.launch_gap_seconds)

    def test_save_and_load_round_trip(self) -> None:
        info = sync.SyncInfo(
            launch_gap_seconds=0.12,
            camera_offset_seconds=0.35,
            mic_offset_seconds=-0.1,
            system_offset_seconds=0.05,
            launch_offsets_seconds={"camera": 0.0, "screen": 0.12, "mic": 0.3, "system": 0.31},
        )

        sync.save_sync(self.path, info)
        loaded = sync.load_sync(self.path)

        self.assertEqual(loaded, info)

    def test_saved_file_has_the_per_stream_keys(self) -> None:
        sync.save_sync(self.path, sync.SyncInfo(mic_offset_seconds=0.2))
        data = json.loads(self.path.read_text(encoding="utf-8"))

        for key in (
            "camera_offset_seconds",
            "mic_offset_seconds",
            "system_offset_seconds",
            "launch_offsets_seconds",
            "launch_gap_seconds",
        ):
            with self.subTest(key=key):
                self.assertIn(key, data)
        self.assertEqual(data["mic_offset_seconds"], 0.2)

    def test_old_two_file_sync_json_still_loads(self) -> None:
        self.path.write_text(
            json.dumps({"launch_gap_seconds": 0.08, "camera_offset_seconds": 0.4}),
            encoding="utf-8",
        )

        info = sync.load_sync(self.path)

        self.assertEqual(info.camera_offset_seconds, 0.4)
        # The old microphone was inside camera.mp4, so it keeps that offset.
        self.assertEqual(info.mic_offset_seconds, 0.4)
        self.assertEqual(info.system_offset_seconds, 0.0)
        self.assertEqual(info.launch_gap_seconds, 0.08)
        self.assertEqual(info.launch_offsets_seconds, {})

    def test_old_file_without_any_offset_loads_as_zero(self) -> None:
        self.path.write_text(json.dumps({"launch_gap_seconds": None}), encoding="utf-8")

        info = sync.load_sync(self.path)

        self.assertEqual(info.camera_offset_seconds, 0.0)
        self.assertEqual(info.mic_offset_seconds, 0.0)

    def test_explicit_mic_offset_wins_over_the_camera_value(self) -> None:
        self.path.write_text(
            json.dumps({"camera_offset_seconds": 0.4, "mic_offset_seconds": 0.0}),
            encoding="utf-8",
        )

        self.assertEqual(sync.load_sync(self.path).mic_offset_seconds, 0.0)

    def test_damaged_file_gives_defaults(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")

        self.assertEqual(sync.load_sync(self.path), sync.SyncInfo())

    def test_unusable_values_fall_back_to_zero(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "camera_offset_seconds": "soon",
                    "mic_offset_seconds": 999,
                    "system_offset_seconds": None,
                    "launch_offsets_seconds": {"mic": "x", "screen": 0.2, "bogus": 1},
                }
            ),
            encoding="utf-8",
        )

        info = sync.load_sync(self.path)

        self.assertEqual(info.camera_offset_seconds, 0.0)
        self.assertEqual(info.mic_offset_seconds, 0.0)
        self.assertEqual(info.system_offset_seconds, 0.0)
        self.assertEqual(info.launch_offsets_seconds, {"screen": 0.2})

    def test_set_stream_offset_keeps_the_other_values(self) -> None:
        sync.save_sync(
            self.path,
            sync.SyncInfo(
                camera_offset_seconds=0.1,
                mic_offset_seconds=0.2,
                system_offset_seconds=0.3,
                launch_offsets_seconds={"mic": 0.25},
            ),
        )

        info = sync.set_stream_offset(self.path, "system", -0.5)

        self.assertEqual(info.system_offset_seconds, -0.5)
        self.assertEqual(info.camera_offset_seconds, 0.1)
        self.assertEqual(info.mic_offset_seconds, 0.2)
        self.assertEqual(info.launch_offsets_seconds, {"mic": 0.25})
        self.assertEqual(sync.load_sync(self.path), info)

    def test_set_stream_offset_rejects_unknown_streams_and_bad_values(self) -> None:
        with self.assertRaises(sync.SyncError):
            sync.set_stream_offset(self.path, "screen", 0.1)
        with self.assertRaises(sync.SyncError):
            sync.set_stream_offset(self.path, "mic", sync.MAX_OFFSET_SECONDS + 1)
        with self.assertRaises(sync.SyncError):
            sync.set_stream_offset(self.path, "mic", float("nan"))
        self.assertFalse(self.path.exists())

    def test_record_launch_offsets_keeps_saved_alignment_offsets(self) -> None:
        sync.set_stream_offset(self.path, "mic", 0.15)

        info = sync.record_launch_offsets(
            self.path,
            {"camera": 0.0, "screen": 0.1, "mic": 0.2, "system": 0.25},
            launch_gap_seconds=0.1,
        )

        self.assertEqual(info.mic_offset_seconds, 0.15)
        self.assertEqual(info.launch_gap_seconds, 0.1)
        self.assertEqual(
            sync.load_sync(self.path).launch_offsets_seconds,
            {"camera": 0.0, "screen": 0.1, "mic": 0.2, "system": 0.25},
        )

    def test_set_camera_offset_still_works(self) -> None:
        info = sync.set_camera_offset(self.path, 0.6)

        self.assertEqual(info.camera_offset_seconds, 0.6)
        self.assertEqual(info.mic_offset_seconds, 0.0)


class RecompositeFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        for name in recomposite.RAW_FILENAMES:
            (self.folder / name).write_bytes(b"raw")

    def run_main(self, *args, saved=None):
        """Run recomposite.main with composite() faked; return (code, kwargs)."""
        if saved is not None:
            (self.folder / "sync.json").write_text(json.dumps(saved), encoding="utf-8")
        fake = mock.Mock(return_value=self.folder / "final.mp4")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(recomposite, "composite", fake), \
                mock.patch.object(
                    recomposite, "load_app_settings",
                    return_value=AppSettings(),
                ), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = recomposite.main([str(self.folder), *args])
        self.last_stdout, self.last_stderr = out.getvalue(), err.getvalue()
        kwargs = fake.call_args.kwargs if fake.called else None
        return code, kwargs

    def saved_sync(self):
        return json.loads((self.folder / "sync.json").read_text(encoding="utf-8"))

    def test_mic_and_system_flags_are_passed_to_composite(self) -> None:
        code, kwargs = self.run_main("--mic-offset", "-0.12", "--system-offset", "0.05")

        self.assertEqual(code, 0)
        self.assertEqual(kwargs["mic_offset"], -0.12)
        self.assertEqual(kwargs["system_offset"], 0.05)
        self.assertEqual(kwargs["camera_offset"], 0.0)

    def test_all_four_raw_files_are_read(self) -> None:
        fake = mock.Mock(return_value=self.folder / "final.mp4")
        with mock.patch.object(recomposite, "composite", fake), \
                mock.patch.object(
                    recomposite, "load_app_settings", return_value=AppSettings()
                ), \
                contextlib.redirect_stdout(io.StringIO()):
            recomposite.main([str(self.folder)])

        args = fake.call_args.args
        self.assertEqual(
            [Path(arg).name for arg in args[:5]],
            ["screen.mp4", "camera.mp4", "mic.wav", "system.wav", "final.mp4"],
        )

    def test_given_offsets_are_saved_after_the_video_is_made(self) -> None:
        code, _ = self.run_main("--mic-offset", "0.2", "--system-offset", "-0.3")

        self.assertEqual(code, 0)
        data = self.saved_sync()
        self.assertEqual(data["mic_offset_seconds"], 0.2)
        self.assertEqual(data["system_offset_seconds"], -0.3)

    def test_omitted_offsets_use_the_saved_values_and_are_not_rewritten(self) -> None:
        saved = {
            "camera_offset_seconds": 0.1,
            "mic_offset_seconds": 0.2,
            "system_offset_seconds": 0.3,
        }
        code, kwargs = self.run_main("--mic-offset", "0.5", saved=saved)

        self.assertEqual(code, 0)
        self.assertEqual(kwargs["camera_offset"], 0.1)
        self.assertEqual(kwargs["mic_offset"], 0.5)
        self.assertEqual(kwargs["system_offset"], 0.3)
        data = self.saved_sync()
        self.assertEqual(data["mic_offset_seconds"], 0.5)
        self.assertEqual(data["camera_offset_seconds"], 0.1)
        self.assertEqual(data["system_offset_seconds"], 0.3)

    def test_old_two_file_sync_json_is_used_for_camera_and_mic(self) -> None:
        code, kwargs = self.run_main(saved={"camera_offset_seconds": 0.4})

        self.assertEqual(code, 0)
        self.assertEqual(kwargs["camera_offset"], 0.4)
        self.assertEqual(kwargs["mic_offset"], 0.4)
        self.assertEqual(kwargs["system_offset"], 0.0)

    def test_nothing_is_saved_when_no_offset_is_given(self) -> None:
        code, _ = self.run_main()

        self.assertEqual(code, 0)
        self.assertFalse((self.folder / "sync.json").exists())

    def test_bad_offset_is_rejected_without_compositing(self) -> None:
        code, kwargs = self.run_main("--system-offset", "999")

        self.assertEqual(code, 1)
        self.assertIsNone(kwargs)
        self.assertIn("system", self.last_stderr)

    def test_failed_composite_does_not_save_offsets(self) -> None:
        fake = mock.Mock(side_effect=compositor.CompositeError("boom"))
        with mock.patch.object(recomposite, "composite", fake), \
                mock.patch.object(
                    recomposite, "load_app_settings", return_value=AppSettings()
                ), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            code = recomposite.main([str(self.folder), "--mic-offset", "0.2"])

        self.assertEqual(code, 1)
        self.assertFalse((self.folder / "sync.json").exists())

    def test_output_may_not_overwrite_any_raw_file(self) -> None:
        for name in ("mic.wav", "system.wav", "camera.mp4", "screen.mp4"):
            with self.subTest(name=name):
                code, kwargs = self.run_main("--output", name)

                self.assertEqual(code, 1)
                self.assertIsNone(kwargs)
                self.assertIn("raw recording", self.last_stderr)


if __name__ == "__main__":
    unittest.main()