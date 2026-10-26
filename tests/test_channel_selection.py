// FILE: tests/test_channel_selection.py
"""Tests for deselecting channels (camera, screen, microphone, system audio).

A deselected channel is saved in the app settings and is ignored when a new
recording starts: it is not captured and not composited.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from recorder import capture as capture_module
from recorder.app_settings import (
    AppSettings,
    clean_settings,
    load_app_settings,
    save_app_settings,
)
from recorder.capture import CaptureError, MultiCapture
from recorder.compositor import (
    build_composite_command,
    build_filter_graph,
)


class _Device:
    def __init__(self, index: int, name: str = "dev") -> None:
        self.index = index
        self.name = name


class _Devices:
    camera = _Device(0, "camera")
    screen = _Device(1, "screen")
    microphone = _Device(2, "mic")
    system_audio = _Device(3, "BlackHole 2ch")


def _make_capture(tmp: Path, **flags) -> MultiCapture:
    return MultiCapture(
        _Devices(),
        tmp / "camera.mp4",
        tmp / "screen.mp4",
        tmp / "mic.wav",
        tmp / "system.wav",
        ffmpeg_path="ffmpeg",
        **flags,
    )


class SettingsPersistenceTests(unittest.TestCase):
    def test_defaults_record_every_channel(self) -> None:
        settings = AppSettings()
        self.assertTrue(settings.record_camera)
        self.assertTrue(settings.record_screen)
        self.assertTrue(settings.record_mic)
        self.assertTrue(settings.record_system_audio)

    def test_missing_file_gives_all_channels_on(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            settings = load_app_settings(Path(folder) / "missing.json")
        self.assertTrue(settings.record_system_audio)

    def test_deselected_channel_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            save_app_settings(AppSettings(record_system_audio=False), path)
            loaded = load_app_settings(path)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(loaded.record_system_audio)
        self.assertTrue(loaded.record_mic)
        self.assertTrue(loaded.record_screen)
        self.assertTrue(loaded.record_camera)
        self.assertIs(saved["record_system_audio"], False)

    def test_invalid_values_fall_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(
                json.dumps({"record_mic": "no", "record_camera": 0}),
                encoding="utf-8",
            )
            loaded = load_app_settings(path)
        self.assertTrue(loaded.record_mic)
        self.assertTrue(loaded.record_camera)

    def test_clean_settings_keeps_valid_bools(self) -> None:
        cleaned = clean_settings(AppSettings(record_mic=False))
        self.assertFalse(cleaned.record_mic)


class CaptureSelectionTests(unittest.TestCase):
    def test_all_streams_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cap = _make_capture(Path(folder))
        self.assertEqual(
            cap.enabled_streams, ("camera", "screen", "mic", "system")
        )
        self.assertEqual(len(cap.raw_paths), 4)

    def test_system_audio_is_not_opened_when_deselected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cap = _make_capture(Path(folder), record_system=False)
        self.assertNotIn("system", cap.enabled_streams)
        self.assertIsNone(cap._system)
        self.assertEqual(len(cap._processes), 3)
        self.assertNotIn(cap.system_path, cap.raw_paths)

    def test_only_selected_processes_are_launched(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cap = _make_capture(Path(folder), record_system=False)
            launched = []

            def fake_start(self_proc) -> None:
                launched.append(self_proc.name)
                self_proc.launch_returned_at = 1.0

            with mock.patch.object(
                capture_module._FfmpegProcess, "start", fake_start
            ), mock.patch.object(
                capture_module._FfmpegProcess, "is_running", lambda s: True
            ), mock.patch.object(capture_module.time, "sleep"):
                cap.start()
        self.assertEqual(sorted(launched), ["camera", "mic", "screen"])

    def test_nothing_selected_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(CaptureError):
                _make_capture(
                    Path(folder),
                    record_camera=False,
                    record_screen=False,
                    record_mic=False,
                    record_system=False,
                )


class CompositeSelectionTests(unittest.TestCase):
    def test_default_graph_has_two_audio_tracks(self) -> None:
        _, labels = build_filter_graph(320, 20)
        self.assertEqual(labels, ["[mic]", "[sys]"])

    def test_graph_skips_deselected_system_audio(self) -> None:
        graph, labels = build_filter_graph(320, 20, include_system=False)
        self.assertEqual(labels, ["[mic]"])
        self.assertNotIn("[sys]", graph)
        self.assertNotIn("[3:a]", graph)

    def test_inputs_are_renumbered_without_camera(self) -> None:
        graph, labels = build_filter_graph(320, 20, include_camera=False)
        self.assertEqual(labels, ["[mic]", "[sys]"])
        self.assertIn("[0:v]", graph)
        self.assertIn("[1:a]", graph)
        self.assertIn("[2:a]", graph)
        self.assertNotIn("[pip]", graph)

    def test_command_has_one_audio_track_without_system(self) -> None:
        paths = [Path(n) for n in ("s.mp4", "c.mp4", "m.wav", "y.wav", "o.mp4")]
        cmd = build_composite_command(
            "ffmpeg", *paths, include_system=False
        )
        self.assertEqual(cmd.count("-i"), 3)
        self.assertNotIn("y.wav", cmd)
        self.assertNotIn("title=System audio", cmd)
        self.assertIn("title=Microphone", cmd)

    def test_command_has_four_inputs_by_default(self) -> None:
        paths = [Path(n) for n in ("s.mp4", "c.mp4", "m.wav", "y.wav", "o.mp4")]
        cmd = build_composite_command("ffmpeg", *paths)
        self.assertEqual(cmd.count("-i"), 4)
        self.assertIn("title=System audio", cmd)


if __name__ == "__main__":
    unittest.main()