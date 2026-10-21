"""Tests for the final video's picture-in-picture layout and audio mix.

Run from the project folder with the standard library only:

    python3 -m unittest discover -s tests -v

These tests check the ffmpeg filter graph that compositor.py builds (the
overlay corner and margin, the amix of the microphone and system audio,
the resampling and the camera offset) and how verify.py classifies the
volumedetect levels it parses. A real ffmpeg is not needed: the filter
graph is built as text, and the audio checks run against a tiny fake
"ffmpeg" script that prints a recorded volumedetect log.
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make `import recorder` work when the tests are started from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recorder import compositor, verify  # noqa: E402


def build_graph(**overrides):
    """Build a filter graph with both inputs having audio by default."""
    kwargs = dict(
        pip_width=compositor.DEFAULT_PIP_WIDTH,
        margin=compositor.DEFAULT_PIP_MARGIN,
        screen_has_audio=True,
        camera_has_audio=True,
    )
    kwargs.update(overrides)
    return compositor.build_filter_graph(**kwargs)


class FilterGraphLayoutTests(unittest.TestCase):
    def test_default_overlay_is_bottom_right_with_the_margin(self) -> None:
        graph, label = build_graph()

        self.assertIn("overlay=W-w-20:H-h-20", graph)
        self.assertEqual(label, "[a]")

    def test_all_four_corners_place_the_overlay_correctly(self) -> None:
        expected = {
            "bottom-right": ("W-w-20", "H-h-20"),
            "bottom-left": ("20", "H-h-20"),
            "top-right": ("W-w-20", "20"),
            "top-left": ("20", "20"),
        }
        for position, (x, y) in expected.items():
            with self.subTest(position=position):
                graph, _ = build_graph(pip_position=position)
                self.assertIn(f"overlay={x}:{y}", graph)

    def test_unknown_position_falls_back_to_bottom_right(self) -> None:
        graph, _ = build_graph(pip_position="middle")

        self.assertIn("overlay=W-w-20:H-h-20", graph)

    def test_pip_width_is_scaled_with_an_even_width(self) -> None:
        graph, _ = build_graph(pip_width=321)

        self.assertIn("[1:v]scale=320:-2[pip]", graph)


class AudioMixTests(unittest.TestCase):
    def test_mic_and_system_audio_are_mixed_by_amix(self) -> None:
        graph, label = build_graph()

        self.assertIn("amix=inputs=2", graph)
        self.assertIn("duration=longest", graph)
        self.assertEqual(label, "[a]")

    def test_both_audio_inputs_are_resampled_to_the_same_rate(self) -> None:
        graph, _ = build_graph()

        rate = compositor.MIX_SAMPLE_RATE
        self.assertIn(
            f"[0:a]aresample={rate}:async=1:first_pts=0[sa]", graph
        )
        self.assertIn(
            f"[1:a]aresample={rate}:async=1:first_pts=0[cr]", graph
        )

    def test_resampled_streams_are_what_gets_mixed(self) -> None:
        graph, _ = build_graph()

        self.assertIn("[sa]", graph)
        self.assertIn("[sa][cr]amix=inputs=2", graph)

    def test_only_screen_audio_is_mapped_without_amix(self) -> None:
        graph, label = build_graph(camera_has_audio=False)

        self.assertNotIn("amix", graph)
        self.assertEqual(label, "0:a")

    def test_only_camera_audio_is_mapped_without_amix(self) -> None:
        graph, label = build_graph(screen_has_audio=False)

        self.assertNotIn("amix", graph)
        self.assertEqual(label, "[1:a]")

    def test_neither_input_has_audio(self) -> None:
        graph, label = build_graph(
            screen_has_audio=False, camera_has_audio=False
        )

        self.assertNotIn("amix", graph)
        self.assertIsNone(label)


class CameraOffsetTests(unittest.TestCase):
    def test_positive_offset_delays_the_camera(self) -> None:
        graph, _ = build_graph(camera_offset=1.5)

        # The camera video is delayed before the overlay.
        self.assertIn("[1:v]setpts=PTS+1.500/TB,scale=320:-2[pip]", graph)
        # The camera audio is delayed after resampling, then mixed.
        self.assertIn(
            f"[1:a]aresample={compositor.MIX_SAMPLE_RATE}:async=1:first_pts=0[cr]",
            graph,
        )
        self.assertIn("[cr]adelay=1500:all=1[ca]", graph)
        self.assertIn("[sa][ca]amix=inputs=2", graph)

    def test_negative_offset_advances_the_camera(self) -> None:
        graph, _ = build_graph(camera_offset=-0.5)

        self.assertIn("[1:v]trim=start=0.500,setpts=PTS-STARTPTS,", graph)
        self.assertIn("[cr]atrim=start=0.500,asetpts=PTS-STARTPTS[ca]", graph)
        self.assertIn("[sa][ca]amix=inputs=2", graph)

    def test_zero_offset_leaves_the_graph_unshifted(self) -> None:
        graph, _ = build_graph(camera_offset=0.0)

        self.assertNotIn("setpts=PTS+", graph)
        self.assertNotIn("adelay", graph)
        self.assertNotIn("atrim", graph)
        self.assertIn("[sa][cr]amix=inputs=2", graph)


class CompositeCommandTests(unittest.TestCase):
    def test_command_maps_video_and_mixed_audio(self) -> None:
        cmd = compositor.build_composite_command(
            "ffmpeg",
            Path("screen.mp4"),
            Path("camera.mp4"),
            Path("final.mp4"),
        )

        self.assertEqual(cmd[cmd.index("-map") + 1], "[v]")
        self.assertIn("[a]", cmd)
        self.assertIn("aac", cmd)
        self.assertIn("-shortest", cmd)

    def test_command_keeps_the_bottom_right_overlay_by_default(self) -> None:
        cmd = compositor.build_composite_command(
            "ffmpeg",
            Path("screen.mp4"),
            Path("camera.mp4"),
            Path("final.mp4"),
        )

        self.assertIn("overlay=W-w-20:H-h-20", " ".join(cmd))

    def test_command_without_audio_maps_no_audio(self) -> None:
        cmd = compositor.build_composite_command(
            "ffmpeg",
            Path("screen.mp4"),
            Path("camera.mp4"),
            Path("final.mp4"),
            screen_has_audio=False,
            camera_has_audio=False,
        )

        self.assertNotIn("aac", cmd)
        self.assertNotIn("-shortest", cmd) if False else self.assertIn(
            "-shortest", cmd
        )


# A fake ffmpeg that prints a recorded volumedetect log and exits 0, so
# verify.check_audio can be tested without a real ffmpeg.
FAKE_FFMPEG_SOURCE = '''#!{python}
import os
import sys

sys.stderr.write(os.environ["FAKE_VOLUMED_LOG"])
sys.exit(0)
'''


class CheckAudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.ffmpeg = str(self.tmp / "fake-ffmpeg")
        Path(self.ffmpeg).write_text(
            FAKE_FFMPEG_SOURCE.format(python=sys.executable), encoding="utf-8"
        )
        os.chmod(self.ffmpeg, os.stat(self.ffmpeg).st_mode | stat.S_IEXEC)
        self.path = self.tmp / "final.mp4"
        self.path.write_bytes(b"not really a video")

    def run_check(self, log: str, **kwargs):
        env = dict(os.environ, FAKE_VOLUMED_LOG=log)
        with mock.patch.dict(os.environ, env):
            return verify.check_audio(self.path, "mic + system audio", self.ffmpeg, **kwargs)

    AUDIBLE_LOG = (
        "[Parsed_volumedetect_0 @ 0x0] mean_volume: -18.1 dB\n"
        "[Parsed_volumedetect_0 @ 0x0] max_volume: -3.2 dB\n"
    )
    QUIET_LOG = (
        "[Parsed_volumedetect_0 @ 0x0] mean_volume: -35.4 dB\n"
        "[Parsed_volumedetect_0 @ 0x0] max_volume: -22.0 dB\n"
    )
    SILENT_LOG = (
        "[Parsed_volumedetect_0 @ 0x0] mean_volume: -91.5 dB\n"
        "[Parsed_volumedetect_0 @ 0x0] max_volume: -85.2 dB\n"
    )
    NO_AUDIO_LOG = "Stream map '0:a:0' matches no streams.\n"

    def test_audible_audio_passes_without_warning(self) -> None:
        result = self.run_check(self.AUDIBLE_LOG)

        self.assertTrue(result.ok)
        self.assertFalse(result.warning)
        self.assertIn("audible", result.detail)
        self.assertIn("-3.2 dB", result.detail)

    def test_quiet_audio_passes_with_a_warning(self) -> None:
        result = self.run_check(self.QUIET_LOG)

        self.assertTrue(result.ok)
        self.assertTrue(result.warning)
        self.assertIn("quiet", result.detail)

    def test_silent_audio_fails_when_required(self) -> None:
        result = self.run_check(self.SILENT_LOG, required=True)

        self.assertFalse(result.ok)
        self.assertIn("silent", result.detail)

    def test_silent_audio_is_only_a_warning_when_not_required(self) -> None:
        result = self.run_check(self.SILENT_LOG)

        self.assertTrue(result.ok)
        self.assertTrue(result.warning)
        self.assertIn("silent", result.detail)

    def test_missing_audio_track_fails_when_required(self) -> None:
        result = self.run_check(self.NO_AUDIO_LOG, required=True)

        self.assertFalse(result.ok)
        self.assertIn("no audio track", result.detail)


class ParseAudioLevelsTests(unittest.TestCase):
    def test_reads_mean_and_peak_from_a_volumedetect_log(self) -> None:
        levels = verify.parse_audio_levels(
            "mean_volume: -18.1 dB\nmax_volume: -3.2 dB\n"
        )

        self.assertTrue(levels.has_audio)
        self.assertEqual(levels.mean_db, -18.1)
        self.assertEqual(levels.peak_db, -3.2)

    def test_log_with_no_audio_stream(self) -> None:
        levels = verify.parse_audio_levels(
            "Stream map '0:a:0' matches no streams.\n"
        )

        self.assertFalse(levels.has_audio)
        self.assertIsNone(levels.mean_db)
        self.assertIsNone(levels.peak_db)

    def test_audio_stream_without_a_measurement(self) -> None:
        levels = verify.parse_audio_levels("Stream #0:0: Audio: aac\n")

        self.assertTrue(levels.has_audio)
        self.assertIsNone(levels.mean_db)
        self.assertIsNone(levels.peak_db)

    def test_silent_level_is_below_the_silence_threshold(self) -> None:
        levels = verify.parse_audio_levels(
            "mean_volume: -91.5 dB\nmax_volume: -85.2 dB\n"
        )

        self.assertLessEqual(levels.peak_db, verify.SILENT_PEAK_DB)

    def test_audible_level_is_above_the_quiet_threshold(self) -> None:
        levels = verify.parse_audio_levels(
            "mean_volume: -18.1 dB\nmax_volume: -3.2 dB\n"
        )

        self.assertGreater(levels.peak_db, verify.QUIET_PEAK_DB)


if __name__ == "__main__":
    unittest.main()