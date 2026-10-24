"""Tests for the final video's picture-in-picture layout and its two audio tracks.

Run from the project folder with the standard library only:

    python3 -m unittest discover -s tests -v

These tests check the ffmpeg filter graph that compositor.py builds (the
overlay corner and margin, the two separate, unmixed audio tracks for the
microphone and system audio, the resampling and the per-stream offsets), the
four-input composite command and how verify.py classifies the volumedetect
levels it parses. A real ffmpeg is not needed: the filter
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
    """Build the filter graph for the four inputs with default settings."""
    kwargs = dict(
        pip_width=compositor.DEFAULT_PIP_WIDTH,
        margin=compositor.DEFAULT_PIP_MARGIN,
    )
    kwargs.update(overrides)
    return compositor.build_filter_graph(**kwargs)


class FilterGraphLayoutTests(unittest.TestCase):
    def test_default_overlay_is_bottom_right_with_the_margin(self) -> None:
        graph, labels = build_graph()

        self.assertIn("overlay=W-w-20:H-h-20", graph)
        self.assertEqual(labels, ["[mic]", "[sys]"])

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


class AudioTrackTests(unittest.TestCase):
    def test_mic_and_system_audio_are_two_separate_outputs(self) -> None:
        graph, labels = build_graph()

        # The microphone is track 1 and the system audio is track 2.
        self.assertEqual(labels, ["[mic]", "[sys]"])
        self.assertIn("[mic]", graph)
        self.assertIn("[sys]", graph)

    def test_the_audio_is_never_mixed(self) -> None:
        graph, _ = build_graph()

        self.assertNotIn("amix", graph)
        self.assertNotIn("alimiter", graph)

    def test_audio_comes_from_the_wav_inputs_not_the_video_files(self) -> None:
        graph, _ = build_graph()

        # Input 2 is mic.wav and input 3 is system.wav; the two video files
        # (inputs 0 and 1) carry no audio any more.
        self.assertIn("[2:a]", graph)
        self.assertIn("[3:a]", graph)
        self.assertNotIn("[0:a]", graph)
        self.assertNotIn("[1:a]", graph)

    def test_both_audio_inputs_are_resampled_to_the_same_rate(self) -> None:
        graph, _ = build_graph()

        rate = compositor.MIX_SAMPLE_RATE
        self.assertIn(
            f"[2:a]aresample={rate}:async=1:first_pts=0[mic]", graph
        )
        self.assertIn(
            f"[3:a]aresample={rate}:async=1:first_pts=0[sys]", graph
        )

    def test_the_track_titles_are_microphone_and_system_audio(self) -> None:
        self.assertEqual(compositor.MIC_TRACK_TITLE, "Microphone")
        self.assertEqual(compositor.SYSTEM_TRACK_TITLE, "System audio")


class CameraOffsetTests(unittest.TestCase):
    def test_positive_offset_delays_the_camera_video(self) -> None:
        graph, _ = build_graph(camera_offset=1.5)

        # The camera video is delayed before the overlay.
        self.assertIn("[1:v]setpts=PTS+1.500/TB,scale=320:-2[pip]", graph)

    def test_negative_offset_advances_the_camera_video(self) -> None:
        graph, _ = build_graph(camera_offset=-0.5)

        self.assertIn(
            "[1:v]trim=start=0.500,setpts=PTS-STARTPTS,scale=320:-2[pip]", graph
        )

    def test_camera_offset_does_not_shift_any_audio(self) -> None:
        # The camera file has no audio now, so its offset only moves video.
        graph, _ = build_graph(camera_offset=1.5)

        self.assertNotIn("adelay", graph)
        self.assertNotIn("atrim", graph)

    def test_zero_offset_leaves_the_graph_unshifted(self) -> None:
        graph, _ = build_graph(camera_offset=0.0)

        self.assertNotIn("setpts=PTS+", graph)
        self.assertNotIn("adelay", graph)
        self.assertNotIn("atrim", graph)
        self.assertNotIn("trim=", graph)


class StreamOffsetTests(unittest.TestCase):
    RATE = compositor.MIX_SAMPLE_RATE

    def test_positive_mic_offset_delays_only_the_microphone(self) -> None:
        graph, _ = build_graph(mic_offset=1.5)

        self.assertIn(
            f"[2:a]aresample={self.RATE}:async=1:first_pts=0,adelay=1500:all=1[mic]",
            graph,
        )
        # The system audio is left alone.
        self.assertIn(
            f"[3:a]aresample={self.RATE}:async=1:first_pts=0[sys]", graph
        )

    def test_negative_mic_offset_trims_the_start_of_the_microphone(self) -> None:
        graph, _ = build_graph(mic_offset=-0.5)

        self.assertIn(
            f"[2:a]aresample={self.RATE}:async=1:first_pts=0,"
            "atrim=start=0.500,asetpts=PTS-STARTPTS[mic]",
            graph,
        )

    def test_system_offset_shifts_only_the_system_audio(self) -> None:
        graph, _ = build_graph(system_offset=0.25)

        self.assertIn(
            f"[3:a]aresample={self.RATE}:async=1:first_pts=0,adelay=250:all=1[sys]",
            graph,
        )
        self.assertIn(
            f"[2:a]aresample={self.RATE}:async=1:first_pts=0[mic]", graph
        )

    def test_negative_system_offset_trims_the_start_of_the_system_audio(self) -> None:
        graph, _ = build_graph(system_offset=-0.25)

        self.assertIn(
            f"[3:a]aresample={self.RATE}:async=1:first_pts=0,"
            "atrim=start=0.250,asetpts=PTS-STARTPTS[sys]",
            graph,
        )

    def test_each_stream_has_its_own_independent_offset(self) -> None:
        graph, _ = build_graph(
            camera_offset=0.4, mic_offset=-0.1, system_offset=0.2
        )

        self.assertIn("[1:v]setpts=PTS+0.400/TB,scale=320:-2[pip]", graph)
        self.assertIn("atrim=start=0.100,asetpts=PTS-STARTPTS[mic]", graph)
        self.assertIn("adelay=200:all=1[sys]", graph)

    def test_the_screen_is_the_reference_and_is_never_shifted(self) -> None:
        graph, _ = build_graph(
            camera_offset=1.0, mic_offset=1.0, system_offset=1.0
        )

        self.assertIn("[0:v][pip]overlay=", graph)
        self.assertNotIn("[0:v]setpts", graph)
        self.assertNotIn("[0:v]trim", graph)

    def test_zero_audio_offsets_leave_both_tracks_unshifted(self) -> None:
        graph, _ = build_graph(mic_offset=0.0, system_offset=0.0)

        self.assertNotIn("adelay", graph)
        self.assertNotIn("atrim", graph)


def build_command(**overrides):
    """Build the composite command for the four raw files."""
    kwargs = dict(
        ffmpeg="ffmpeg",
        screen_path=Path("screen.mp4"),
        camera_path=Path("camera.mp4"),
        mic_path=Path("mic.wav"),
        system_path=Path("system.wav"),
        output=Path("final.mp4"),
    )
    kwargs.update(overrides)
    return compositor.build_composite_command(**kwargs)


def values_after(cmd, flag):
    """Every value that follows `flag` in a command, in order."""
    return [cmd[i + 1] for i, part in enumerate(cmd) if part == flag]


class CompositeCommandTests(unittest.TestCase):
    def test_command_reads_the_four_raw_files_in_order(self) -> None:
        cmd = build_command()

        self.assertEqual(
            values_after(cmd, "-i"),
            ["screen.mp4", "camera.mp4", "mic.wav", "system.wav"],
        )

    def test_command_maps_video_and_two_separate_audio_tracks(self) -> None:
        cmd = build_command()

        self.assertEqual(values_after(cmd, "-map"), ["[v]", "[mic]", "[sys]"])
        self.assertIn("aac", cmd)
        self.assertIn("-shortest", cmd)

    def test_command_does_not_mix_the_audio(self) -> None:
        cmd = build_command()

        self.assertNotIn("amix", " ".join(cmd))

    def test_audio_tracks_are_titled(self) -> None:
        cmd = build_command()

        self.assertEqual(
            values_after(cmd, "-metadata:s:a:0"), ["title=Microphone"]
        )
        self.assertEqual(
            values_after(cmd, "-metadata:s:a:1"), ["title=System audio"]
        )

    def test_the_microphone_is_the_default_track(self) -> None:
        cmd = build_command()

        self.assertEqual(values_after(cmd, "-disposition:a:0"), ["default"])
        self.assertEqual(values_after(cmd, "-disposition:a:1"), ["0"])

    def test_command_keeps_the_bottom_right_overlay_by_default(self) -> None:
        cmd = build_command()

        self.assertIn("overlay=W-w-20:H-h-20", " ".join(cmd))

    def test_per_stream_offsets_reach_the_filter_graph(self) -> None:
        cmd = build_command(camera_offset=0.4, mic_offset=0.5, system_offset=-0.2)
        graph = values_after(cmd, "-filter_complex")[0]

        self.assertIn("setpts=PTS+0.400/TB", graph)
        self.assertIn("adelay=500:all=1[mic]", graph)
        self.assertIn("atrim=start=0.200,asetpts=PTS-STARTPTS[sys]", graph)

    def test_the_output_is_the_last_argument(self) -> None:
        cmd = build_command(output=Path("final.part.mp4"))

        self.assertEqual(cmd[-1], "final.part.mp4")


class CompositeInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        for name in ("screen.mp4", "camera.mp4", "mic.wav", "system.wav"):
            (self.tmp / name).write_bytes(b"x")

    def composite(self):
        return compositor.composite(
            self.tmp / "screen.mp4",
            self.tmp / "camera.mp4",
            self.tmp / "mic.wav",
            self.tmp / "system.wav",
            self.tmp / "final.mp4",
        )

    def test_a_missing_microphone_file_is_reported_by_name(self) -> None:
        (self.tmp / "mic.wav").unlink()

        with self.assertRaises(compositor.CompositeError) as caught:
            self.composite()

        self.assertIn("microphone", str(caught.exception))
        self.assertIn("mic.wav", str(caught.exception))

    def test_an_empty_system_audio_file_is_reported_by_name(self) -> None:
        (self.tmp / "system.wav").write_bytes(b"")

        with self.assertRaises(compositor.CompositeError) as caught:
            self.composite()

        self.assertIn("system audio", str(caught.exception))
        self.assertIn("system.wav", str(caught.exception))


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