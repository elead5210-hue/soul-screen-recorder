"""Tests for the platform compatibility check (recorder/compat.py).

Run from the project folder with the standard library only:

    python3 -m unittest discover -s tests -v

The supported platform is macOS 13 or newer, on Apple Silicon and Intel
Macs, with Tk 8.6 or newer. These tests check how version text is parsed,
how the 13.0 minimum is compared, how the processor and Rosetta are told
apart, how an outdated Tk is reported, and that anything that cannot be read
(not macOS, a failing command, no Tkinter) is reported as unknown instead of
raising. No Mac is needed: the facts are passed in as a PlatformInfo, and the
system calls are replaced with fakes.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

# Make `import recorder` work when the tests are started from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recorder import compat  # noqa: E402
from recorder.compat import PlatformInfo  # noqa: E402


def mac(version=(14, 5), tk=(8, 6), machine="arm64", apple_silicon=True,
        rosetta=False):
    """The facts for a Mac; the defaults are a healthy Apple Silicon one."""
    return PlatformInfo(
        system="Darwin",
        macos_version=version,
        machine=machine,
        apple_silicon=apple_silicon,
        rosetta=rosetta,
        tk_version=tk,
    )


def codes(result):
    return [issue.code for issue in result.issues]


class ParseVersionTests(unittest.TestCase):
    def test_parses_full_and_short_versions(self):
        self.assertEqual(compat.parse_version("13.6.1"), (13, 6, 1))
        self.assertEqual(compat.parse_version("14.5"), (14, 5))
        self.assertEqual(compat.parse_version("26"), (26,))

    def test_ignores_surrounding_text(self):
        self.assertEqual(compat.parse_version("  15.0.1\n"), (15, 0, 1))
        self.assertEqual(compat.parse_version("8.6.13 (patch)"), (8, 6, 13))

    def test_unreadable_values_are_none(self):
        for value in ("", "   ", "abc", None, "v13", 0):
            with self.subTest(value=value):
                self.assertIsNone(compat.parse_version(value))

    def test_accepts_a_float_such_as_tkversion(self):
        self.assertEqual(compat.parse_version(8.6), (8, 6))

    def test_format_version_round_trips(self):
        self.assertEqual(compat.format_version((13, 6, 1)), "13.6.1")
        self.assertEqual(compat.format_version((8, 6)), "8.6")


class MinimumComparisonTests(unittest.TestCase):
    def test_minimum_is_macos_13(self):
        self.assertEqual(compat.MIN_MACOS, (13, 0))
        self.assertEqual(compat.MIN_MACOS_TEXT, "13.0")
        self.assertEqual(
            compat.parse_version(compat.MIN_MACOS_TEXT), compat.MIN_MACOS
        )

    def test_versions_of_different_lengths_compare_equal(self):
        self.assertTrue(compat.version_at_least((13,), (13, 0)))
        self.assertTrue(compat.version_at_least((13, 0), (13,)))
        self.assertTrue(compat.version_at_least((13, 0, 0), (13, 0)))

    def test_older_versions_are_below_the_minimum(self):
        for version in ((12, 7, 6), (12, 0), (11, 7), (10, 15, 7)):
            with self.subTest(version=version):
                self.assertFalse(
                    compat.version_at_least(version, compat.MIN_MACOS)
                )

    def test_minimum_and_newer_versions_pass(self):
        for version in ((13, 0), (13, 0, 1), (13, 6), (14, 5), (15, 1), (26, 0)):
            with self.subTest(version=version):
                self.assertTrue(
                    compat.version_at_least(version, compat.MIN_MACOS)
                )

    def test_minor_versions_compare_numerically_not_as_text(self):
        # 8.10 is newer than 8.6 even though "10" sorts before "6" as text.
        self.assertTrue(compat.version_at_least((8, 10), (8, 6)))

    def test_describe_macos_names_known_versions(self):
        self.assertEqual(compat.describe_macos((13, 6)), "macOS 13.6 (Ventura)")
        self.assertEqual(compat.describe_macos((14, 5)), "macOS 14.5 (Sonoma)")
        self.assertEqual(compat.describe_macos((10, 15, 7)), "macOS 10.15.7")


class ArchitectureTests(unittest.TestCase):
    def test_native_apple_silicon(self):
        self.assertEqual(
            compat.classify_architecture("arm64", False, True), (True, False)
        )

    def test_intel_mac(self):
        # On an Intel Mac neither sysctl name exists, which reads as False.
        self.assertEqual(
            compat.classify_architecture("x86_64", False, False), (False, False)
        )

    def test_intel_python_under_rosetta(self):
        self.assertEqual(
            compat.classify_architecture("x86_64", True, True), (True, True)
        )

    def test_intel_python_on_apple_silicon_without_translation_flag(self):
        # The chip is Apple Silicon even if proc_translated could not be read.
        self.assertEqual(
            compat.classify_architecture("x86_64", False, True), (True, True)
        )

    def test_arm64_python_is_never_rosetta(self):
        self.assertEqual(
            compat.classify_architecture("arm64", True, True), (True, False)
        )

    def test_unknown_machine_is_unknown(self):
        for machine in (None, "", "ppc64", "riscv64"):
            with self.subTest(machine=machine):
                self.assertEqual(
                    compat.classify_architecture(machine, False, False),
                    (None, False),
                )

    def test_machine_name_is_case_and_space_tolerant(self):
        self.assertEqual(
            compat.classify_architecture(" ARM64 ", False, False), (True, False)
        )

    def test_architecture_labels(self):
        self.assertEqual(mac().architecture_label, "Apple Silicon")
        self.assertEqual(
            mac(machine="x86_64", apple_silicon=False).architecture_label,
            "Intel",
        )
        self.assertIn(
            "Rosetta",
            mac(machine="x86_64", apple_silicon=True, rosetta=True)
            .architecture_label,
        )
        self.assertEqual(
            PlatformInfo(system="Linux", machine="aarch64").architecture_label,
            "aarch64",
        )
        self.assertEqual(PlatformInfo().architecture_label, "unknown CPU")


class EvaluateMacosTests(unittest.TestCase):
    def test_current_macos_on_apple_silicon_is_fine(self):
        result = compat.evaluate(mac(version=(14, 5)))
        self.assertTrue(result.supported)
        self.assertTrue(result.macos_supported)
        self.assertEqual(result.issues, ())
        self.assertEqual(result.message(), "")
        self.assertIsNone(result.blocking_message())
        self.assertIsNone(result.macos_message())

    def test_current_macos_on_intel_is_fine(self):
        result = compat.evaluate(
            mac(version=(13, 0), machine="x86_64", apple_silicon=False)
        )
        self.assertTrue(result.supported)
        self.assertEqual(result.issues, ())

    def test_exactly_the_minimum_is_supported(self):
        self.assertTrue(compat.evaluate(mac(version=(13, 0))).macos_supported)

    def test_macos_12_is_too_old(self):
        result = compat.evaluate(mac(version=(12, 6, 1)))
        self.assertFalse(result.supported)
        self.assertFalse(result.macos_supported)
        self.assertEqual(codes(result), [compat.MACOS_TOO_OLD])
        issue = result.issue(compat.MACOS_TOO_OLD)
        self.assertTrue(issue.blocking)

    def test_too_old_message_names_versions_and_fix(self):
        message = compat.evaluate(mac(version=(12, 6, 1))).macos_message()
        self.assertIn("macOS 12.6.1", message)
        self.assertIn("macOS 13", message)
        self.assertIn("Software Update", message)
        self.assertIn("How to fix it", message)

    def test_macos_10_15_is_too_old(self):
        self.assertFalse(compat.evaluate(mac(version=(10, 15, 7))).macos_supported)

    def test_unknown_macos_version_does_not_block(self):
        result = compat.evaluate(mac(version=None))
        self.assertTrue(result.supported)
        self.assertTrue(result.macos_supported)
        self.assertEqual(result.issues, ())

    def test_newer_than_tested_warns_but_does_not_block(self):
        newer = compat.LATEST_TESTED_MACOS_MAJOR + 1
        result = compat.evaluate(mac(version=(newer, 0)))
        self.assertTrue(result.supported)
        self.assertEqual(codes(result), [compat.MACOS_UNTESTED])
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.blocking_issues, ())
        self.assertIsNone(result.blocking_message())

    def test_latest_tested_version_has_no_warning(self):
        version = (compat.LATEST_TESTED_MACOS_MAJOR, 3)
        self.assertEqual(compat.evaluate(mac(version=version)).issues, ())


class EvaluateTkTests(unittest.TestCase):
    def test_tk_8_6_is_fine(self):
        result = compat.evaluate(mac(tk=(8, 6)))
        self.assertTrue(result.tk_supported)
        self.assertEqual(result.issues, ())

    def test_newer_tk_is_fine(self):
        self.assertTrue(compat.evaluate(mac(tk=(8, 6, 13))).tk_supported)
        self.assertTrue(compat.evaluate(mac(tk=(9, 0))).tk_supported)

    def test_tk_8_5_is_too_old(self):
        result = compat.evaluate(mac(tk=(8, 5)))
        self.assertFalse(result.supported)
        self.assertFalse(result.tk_supported)
        self.assertEqual(codes(result), [compat.TK_TOO_OLD])
        self.assertTrue(result.issue(compat.TK_TOO_OLD).blocking)

    def test_tk_message_explains_the_system_python_and_the_fix(self):
        message = compat.evaluate(mac(tk=(8, 5))).tk_message()
        self.assertIn("Tk 8.5", message)
        self.assertIn("/usr/bin/python3", message)
        self.assertIn("brew install python python-tk", message)
        self.assertIn("./run.sh", message)

    def test_tk_message_points_at_the_matching_homebrew_folder(self):
        silicon = compat.evaluate(mac(tk=(8, 5), apple_silicon=True))
        intel = compat.evaluate(
            mac(tk=(8, 5), machine="x86_64", apple_silicon=False)
        )
        self.assertIn("/opt/homebrew", silicon.tk_message())
        self.assertIn("/usr/local", intel.tk_message())

    def test_unknown_tk_does_not_block(self):
        result = compat.evaluate(mac(tk=None))
        self.assertTrue(result.supported)
        self.assertEqual(result.issues, ())

    def test_old_tk_is_reported_on_any_platform(self):
        info = PlatformInfo(system="Linux", tk_version=(8, 5))
        self.assertEqual(codes(compat.evaluate(info)), [compat.TK_TOO_OLD])


class EvaluateRosettaTests(unittest.TestCase):
    def test_rosetta_warns_but_does_not_block(self):
        result = compat.evaluate(
            mac(machine="x86_64", apple_silicon=True, rosetta=True)
        )
        self.assertTrue(result.supported)
        self.assertEqual(codes(result), [compat.RUNNING_UNDER_ROSETTA])
        self.assertFalse(result.issue(compat.RUNNING_UNDER_ROSETTA).blocking)
        self.assertIn("Rosetta", result.message())

    def test_native_macs_have_no_rosetta_warning(self):
        for info in (
            mac(),
            mac(machine="x86_64", apple_silicon=False),
        ):
            with self.subTest(machine=info.machine):
                self.assertEqual(compat.evaluate(info).issues, ())


class IssueOrderingTests(unittest.TestCase):
    def test_blocking_problems_come_before_warnings(self):
        info = mac(
            version=(12, 0),
            tk=(8, 5),
            machine="x86_64",
            apple_silicon=True,
            rosetta=True,
        )
        result = compat.evaluate(info)
        self.assertEqual(
            codes(result),
            [
                compat.MACOS_TOO_OLD,
                compat.TK_TOO_OLD,
                compat.RUNNING_UNDER_ROSETTA,
            ],
        )
        self.assertEqual(len(result.blocking_issues), 2)
        self.assertEqual(len(result.warnings), 1)

    def test_blocking_message_leaves_out_warnings(self):
        info = mac(
            version=(12, 0), machine="x86_64", apple_silicon=True, rosetta=True
        )
        result = compat.evaluate(info)
        self.assertIn("too old", result.blocking_message())
        self.assertNotIn("Rosetta", result.blocking_message())
        self.assertIn("Rosetta", result.message())
        self.assertNotIn("Rosetta", result.message(include_warnings=False))


class NotMacosTests(unittest.TestCase):
    def test_other_systems_are_unknown_not_unsupported(self):
        info = PlatformInfo(system="Linux", machine="x86_64", tk_version=(8, 6))
        result = compat.evaluate(info)
        self.assertTrue(result.supported)
        self.assertTrue(result.macos_supported)
        self.assertEqual(result.issues, ())

    def test_macos_checks_are_skipped_off_macos(self):
        # A macOS version on a non-macOS system is ignored, not judged.
        info = PlatformInfo(system="Linux", macos_version=(10, 0))
        self.assertEqual(compat.evaluate(info).issues, ())

    def test_empty_facts_are_fine(self):
        result = compat.evaluate(PlatformInfo())
        self.assertTrue(result.supported)
        self.assertEqual(result.issues, ())

    def test_detect_platform_on_a_non_mac_skips_the_mac_readings(self):
        with mock.patch.object(compat.platform, "system", return_value="Linux"), \
                mock.patch.object(compat, "_run") as run:
            info = compat.detect_platform()
        run.assert_not_called()
        self.assertEqual(info.system, "Linux")
        self.assertIsNone(info.macos_version)
        self.assertIsNone(info.apple_silicon)
        self.assertFalse(info.rosetta)


class SummaryTests(unittest.TestCase):
    def test_summary_for_a_mac(self):
        summary = compat.evaluate(mac(version=(14, 5), tk=(8, 6))).summary()
        self.assertEqual(summary, "macOS 14.5 (Sonoma), Apple Silicon, Tk 8.6")

    def test_summary_for_unknowns(self):
        summary = compat.evaluate(mac(version=None, tk=None)).summary()
        self.assertIn("version unknown", summary)
        self.assertIn("Tk not available", summary)

    def test_summary_for_another_system(self):
        summary = compat.evaluate(PlatformInfo(system="Linux")).summary()
        self.assertTrue(summary.startswith("Linux"))


class DetectionFailureTests(unittest.TestCase):
    """Anything that cannot be read is unknown; nothing may raise."""

    def test_run_returns_none_when_the_command_is_missing(self):
        with mock.patch.object(
            compat.subprocess, "run", side_effect=FileNotFoundError()
        ):
            self.assertIsNone(compat._run(["/no/such/command"]))

    def test_run_returns_none_on_timeout(self):
        with mock.patch.object(
            compat.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("sysctl", 5),
        ):
            self.assertIsNone(compat._run(["sysctl"]))

    def test_run_returns_none_on_a_failing_exit_code(self):
        failed = subprocess.CompletedProcess([], 1, stdout="1\n")
        with mock.patch.object(compat.subprocess, "run", return_value=failed):
            self.assertIsNone(compat._run(["sysctl"]))

    def test_run_returns_the_trimmed_output(self):
        done = subprocess.CompletedProcess([], 0, stdout=" 14.5 \n")
        with mock.patch.object(compat.subprocess, "run", return_value=done):
            self.assertEqual(compat._run(["sw_vers"]), "14.5")

    def test_sysctl_flag_is_false_when_the_name_does_not_exist(self):
        with mock.patch.object(compat, "_run", return_value=None):
            self.assertFalse(compat._sysctl_flag("hw.optional.arm64"))

    def test_sysctl_flag_reads_one_as_true_and_zero_as_false(self):
        with mock.patch.object(compat, "_run", return_value="1"):
            self.assertTrue(compat._sysctl_flag("sysctl.proc_translated"))
        with mock.patch.object(compat, "_run", return_value="0"):
            self.assertFalse(compat._sysctl_flag("sysctl.proc_translated"))

    def test_macos_version_comes_from_platform_when_it_is_real(self):
        with mock.patch.object(
            compat.platform, "mac_ver", return_value=("14.5", ("", "", ""), "")
        ), mock.patch.object(compat, "_sw_vers_version") as sw_vers:
            self.assertEqual(compat._detect_macos_version(), (14, 5))
        sw_vers.assert_not_called()

    def test_compatibility_mode_version_is_replaced_by_sw_vers(self):
        # A Python built for an old SDK is told 10.16 on every macOS 11+.
        with mock.patch.object(
            compat.platform, "mac_ver", return_value=("10.16", ("", "", ""), "")
        ), mock.patch.object(compat, "_sw_vers_version", return_value=(14, 5)):
            self.assertEqual(compat._detect_macos_version(), (14, 5))

    def test_compatibility_mode_version_is_unknown_if_sw_vers_fails(self):
        # Never judge a Mac as macOS 10.16 (too old) from the fake number.
        with mock.patch.object(
            compat.platform, "mac_ver", return_value=("10.16", ("", "", ""), "")
        ), mock.patch.object(compat, "_sw_vers_version", return_value=None):
            self.assertIsNone(compat._detect_macos_version())

    def test_empty_platform_version_falls_back_to_sw_vers(self):
        with mock.patch.object(
            compat.platform, "mac_ver", return_value=("", ("", "", ""), "")
        ), mock.patch.object(compat, "_sw_vers_version", return_value=(15, 1)):
            self.assertEqual(compat._detect_macos_version(), (15, 1))

    def test_everything_failing_gives_an_unknown_version(self):
        with mock.patch.object(
            compat.platform, "mac_ver", side_effect=RuntimeError("boom")
        ), mock.patch.object(compat, "_sw_vers_version", return_value=None):
            self.assertIsNone(compat._detect_macos_version())

    def test_sw_vers_is_asked_without_compatibility_mode(self):
        with mock.patch.object(compat, "_run", return_value="14.5") as run:
            self.assertEqual(compat._sw_vers_version(), (14, 5))
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["SYSTEM_VERSION_COMPAT"], "0")

    def test_missing_tkinter_gives_an_unknown_tk_version(self):
        with mock.patch.dict(sys.modules, {"tkinter": None}):
            self.assertIsNone(compat._detect_tk_version())

    def test_tk_version_is_read_from_tkinter(self):
        fake_tkinter = mock.Mock(TkVersion=8.6)
        with mock.patch.dict(sys.modules, {"tkinter": fake_tkinter}):
            self.assertEqual(compat._detect_tk_version(), (8, 6))

    def test_detect_platform_never_raises_when_everything_fails(self):
        with mock.patch.object(
            compat.platform, "system", side_effect=RuntimeError("boom")
        ), mock.patch.object(
            compat.platform, "machine", side_effect=RuntimeError("boom")
        ), mock.patch.object(compat, "_detect_tk_version", return_value=None):
            info = compat.detect_platform()
        self.assertEqual(info.system, "")
        self.assertIsNone(info.machine)
        self.assertIsNone(info.macos_version)

    def test_detect_platform_reads_a_mac(self):
        with mock.patch.object(compat.platform, "system", return_value="Darwin"), \
                mock.patch.object(compat.platform, "machine", return_value="x86_64"), \
                mock.patch.object(compat, "_detect_macos_version", return_value=(14, 5)), \
                mock.patch.object(compat, "_sysctl_flag", return_value=True), \
                mock.patch.object(compat, "_detect_tk_version", return_value=(8, 6)):
            info = compat.detect_platform()
        self.assertEqual(info.macos_version, (14, 5))
        self.assertTrue(info.apple_silicon)
        self.assertTrue(info.rosetta)
        self.assertEqual(info.tk_version, (8, 6))

    def test_check_compatibility_never_raises(self):
        with mock.patch.object(
            compat, "detect_platform", side_effect=RuntimeError("boom")
        ):
            result = compat.check_compatibility()
        self.assertTrue(result.supported)
        self.assertEqual(result.issues, ())

    def test_check_compatibility_returns_the_verdict_for_this_computer(self):
        info = mac(version=(12, 0))
        with mock.patch.object(compat, "detect_platform", return_value=info):
            result = compat.check_compatibility()
        self.assertFalse(result.supported)
        self.assertIsNotNone(result.macos_message())


class CommandLineTests(unittest.TestCase):
    def run_main(self, info):
        with mock.patch.object(compat, "detect_platform", return_value=info), \
                mock.patch("builtins.print") as printed:
            code = compat.main()
        output = "\n".join(
            " ".join(str(arg) for arg in call.args)
            for call in printed.call_args_list
        )
        return code, output

    def test_supported_mac_exits_zero(self):
        code, output = self.run_main(mac())
        self.assertEqual(code, 0)
        self.assertIn("meets the requirements", output)

    def test_unsupported_mac_exits_non_zero_with_the_fix(self):
        code, output = self.run_main(mac(version=(12, 0)))
        self.assertEqual(code, 1)
        self.assertIn("How to fix it", output)

    def test_unknown_version_still_exits_zero(self):
        code, output = self.run_main(mac(version=None))
        self.assertEqual(code, 0)
        self.assertIn("could not be determined", output)


if __name__ == "__main__":
    unittest.main()