"""Which Macs the recorder supports, and a check that this one qualifies.

Supported platform:

- macOS 13 (Ventura) or newer. This is the oldest version the app is built
  and tested for; the packaged .app declares the same minimum.
- Apple Silicon (arm64) and Intel (x86_64) Macs. An Intel build of Python
  running on an Apple Silicon Mac (through Rosetta) works too, but is slower,
  so it is reported as a warning.
- Tk 8.6 or newer for the window. The Python that ships with macOS uses
  Tk 8.5, which draws blank or broken windows on current macOS.

`check_compatibility()` gathers the facts and returns a `CompatibilityResult`
with a clear message and fix steps for every problem found. Nothing in this
module raises: if a fact cannot be read (not macOS, a failing command, no
Tkinter), it is simply unknown, and unknown never blocks. Callers should let
the app carry on, and ffmpeg or macOS will report any real problem.

The checks are split so they can be tested without a Mac:

- `detect_platform()` reads the raw facts into a `PlatformInfo`
- `evaluate(info)` turns facts into issues (pure, no system access)

Only the standard library is used, and no other module of the app is
imported, so this file is also safe to import from setup.py. Run
`python3 -m recorder.compat` to print the report for this Mac.
"""

import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

Version = Tuple[int, ...]

# ---- the supported platform --------------------------------------------

# Oldest supported macOS, as a tuple for comparing and as text for Info.plist.
MIN_MACOS: Version = (13, 0)
MIN_MACOS_TEXT = "13.0"
MIN_MACOS_NAME = "macOS 13 (Ventura)"

# Newest macOS major version the app has been tested on. Newer versions are
# expected to work, but are reported as a (non-blocking) note.
LATEST_TESTED_MACOS_MAJOR = 26

# Oldest Tk that draws the window correctly on current macOS.
MIN_TK: Version = (8, 6)

_MACOS_NAMES = {
    11: "Big Sur",
    12: "Monterey",
    13: "Ventura",
    14: "Sonoma",
    15: "Sequoia",
    26: "Tahoe",
}

# Issue codes.
MACOS_TOO_OLD = "macos_too_old"
TK_TOO_OLD = "tk_too_old"
RUNNING_UNDER_ROSETTA = "running_under_rosetta"
MACOS_UNTESTED = "macos_untested"

_COMMAND_TIMEOUT = 5  # seconds, for sysctl and sw_vers


# ---- versions ----------------------------------------------------------

def parse_version(text: object) -> Optional[Version]:
    """Turn text like 13.6.1 into (13, 6, 1); None for anything unreadable."""
    try:
        if not text:
            return None
        match = re.match(r"\s*(\d+(?:\.\d+)*)", str(text))
        if not match:
            return None
        return tuple(int(part) for part in match.group(1).split("."))
    except Exception:
        return None


def format_version(version: Version) -> str:
    return ".".join(str(part) for part in version)


def version_at_least(version: Version, minimum: Version) -> bool:
    """Compare versions of different lengths: (13,) is the same as (13, 0)."""
    size = max(len(version), len(minimum))
    padded = tuple(version) + (0,) * (size - len(version))
    padded_min = tuple(minimum) + (0,) * (size - len(minimum))
    return padded >= padded_min


def describe_macos(version: Version) -> str:
    """Name a version: macOS 14.5 (Sonoma), or just macOS 12.6 if unnamed."""
    text = f"macOS {format_version(version)}"
    name = _MACOS_NAMES.get(version[0]) if version else None
    return f"{text} ({name})" if name else text


# ---- the facts ---------------------------------------------------------

@dataclass(frozen=True)
class PlatformInfo:
    """What was found out about this computer. None means "unknown"."""

    system: str = ""                        # platform.system(), "Darwin" on a Mac
    macos_version: Optional[Version] = None
    machine: Optional[str] = None           # "arm64" or "x86_64" (of Python)
    apple_silicon: Optional[bool] = None    # the Mac's chip, not Python's build
    rosetta: bool = False                   # Intel Python on an Apple Silicon Mac
    tk_version: Optional[Version] = None

    @property
    def is_macos(self) -> bool:
        return self.system == "Darwin"

    @property
    def architecture_label(self) -> str:
        if self.rosetta:
            return "Apple Silicon (Intel Python under Rosetta)"
        if self.apple_silicon is True:
            return "Apple Silicon"
        if self.apple_silicon is False:
            return "Intel"
        return self.machine or "unknown CPU"


def classify_architecture(
    machine: Optional[str], translated: bool, arm_capable: bool
) -> Tuple[Optional[bool], bool]:
    """Work out (apple_silicon, rosetta) from the raw readings.

    `machine` is what Python was built for (platform.machine()). `translated`
    is sysctl proc_translated (this process runs through Rosetta) and
    `arm_capable` is sysctl hw.optional.arm64 (the chip is Apple Silicon,
    even when Python itself is an Intel build). On an Intel Mac both sysctl
    names do not exist, which reads as False.
    """
    name = (machine or "").strip().lower()
    if name == "arm64":
        return True, False
    if name in ("x86_64", "amd64", "i386"):
        if translated or arm_capable:
            return True, True
        return False, False
    return None, False


def _run(command, env=None) -> Optional[str]:
    """Run a small system command; its output, or None on any failure."""
    try:
        done = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=_COMMAND_TIMEOUT,
            env=env,
        )
        if done.returncode != 0:
            return None
        return done.stdout.strip()
    except Exception:
        return None


def _sysctl_flag(name: str) -> bool:
    return _run(["/usr/sbin/sysctl", "-n", name]) == "1"


def _sw_vers_version() -> Optional[Version]:
    # Without this, sw_vers also reports 10.16 for Big Sur and newer when the
    # calling program is old enough to trigger macOS's compatibility mode.
    env = dict(os.environ, SYSTEM_VERSION_COMPAT="0")
    return parse_version(_run(["/usr/bin/sw_vers", "-productVersion"], env=env))


def _detect_macos_version() -> Optional[Version]:
    try:
        version = parse_version(platform.mac_ver()[0])
    except Exception:
        version = None
    # A Python built for an old SDK is told "10.16" on every macOS 11+.
    if version is None or version[:2] == (10, 16):
        real = _sw_vers_version()
        if real is not None and real[:2] != (10, 16):
            return real
        if version is not None and version[:2] == (10, 16):
            return None  # the real version cannot be told; treat as unknown
    return version


def _detect_tk_version() -> Optional[Version]:
    try:
        import tkinter

        return parse_version(str(tkinter.TkVersion))
    except Exception:
        return None


def detect_platform() -> PlatformInfo:
    """Read the facts about this computer. Never raises."""
    try:
        system = platform.system()
    except Exception:
        system = ""

    try:
        machine = platform.machine() or None
    except Exception:
        machine = None

    macos_version = None
    apple_silicon = None
    rosetta = False
    if system == "Darwin":
        macos_version = _detect_macos_version()
        apple_silicon, rosetta = classify_architecture(
            machine,
            translated=_sysctl_flag("sysctl.proc_translated"),
            arm_capable=_sysctl_flag("hw.optional.arm64"),
        )

    return PlatformInfo(
        system=system,
        macos_version=macos_version,
        machine=machine,
        apple_silicon=apple_silicon,
        rosetta=rosetta,
        tk_version=_detect_tk_version(),
    )


# ---- the verdict -------------------------------------------------------

@dataclass(frozen=True)
class CompatIssue:
    """One problem: what is wrong, why it matters, and how to fix it."""

    code: str
    title: str
    detail: str
    fix: str
    blocking: bool = False

    def text(self) -> str:
        return f"{self.title}\n{self.detail}\n\nHow to fix it:\n{self.fix}"


@dataclass(frozen=True)
class CompatibilityResult:
    info: PlatformInfo
    issues: Tuple[CompatIssue, ...] = ()

    @property
    def blocking_issues(self) -> Tuple[CompatIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    @property
    def warnings(self) -> Tuple[CompatIssue, ...]:
        return tuple(issue for issue in self.issues if not issue.blocking)

    @property
    def supported(self) -> bool:
        """False only when something definitely rules this setup out."""
        return not self.blocking_issues

    @property
    def macos_supported(self) -> bool:
        return self.issue(MACOS_TOO_OLD) is None

    @property
    def tk_supported(self) -> bool:
        return self.issue(TK_TOO_OLD) is None

    def issue(self, code: str) -> Optional[CompatIssue]:
        for issue in self.issues:
            if issue.code == code:
                return issue
        return None

    def macos_message(self) -> Optional[str]:
        found = self.issue(MACOS_TOO_OLD)
        return found.text() if found else None

    def tk_message(self) -> Optional[str]:
        found = self.issue(TK_TOO_OLD)
        return found.text() if found else None

    def blocking_message(self) -> Optional[str]:
        """All blocking problems as one message, or None when there are none."""
        if not self.blocking_issues:
            return None
        return "\n\n".join(issue.text() for issue in self.blocking_issues)

    def message(self, include_warnings: bool = True) -> str:
        """Every problem (blocking first) as one message; "" when none."""
        issues = list(self.blocking_issues)
        if include_warnings:
            issues.extend(self.warnings)
        return "\n\n".join(issue.text() for issue in issues)

    def summary(self) -> str:
        """One line, for example: macOS 14.5 (Sonoma), Apple Silicon, Tk 8.6."""
        info = self.info
        if info.is_macos:
            system = (
                describe_macos(info.macos_version)
                if info.macos_version
                else "macOS (version unknown)"
            )
        else:
            system = info.system or "unknown system"
        tk = (
            f"Tk {format_version(info.tk_version)}"
            if info.tk_version
            else "Tk not available"
        )
        return f"{system}, {info.architecture_label}, {tk}"


def _homebrew_hint(info: PlatformInfo) -> str:
    if info.apple_silicon:
        return "Homebrew lives in /opt/homebrew on Apple Silicon Macs."
    return "Homebrew lives in /usr/local on Intel Macs."


def _macos_too_old_issue(version: Version) -> CompatIssue:
    return CompatIssue(
        code=MACOS_TOO_OLD,
        title=f"{describe_macos(version)} is too old.",
        detail=(
            f"Soul Screen Recorder needs {MIN_MACOS_NAME} or newer. Older "
            "versions are not tested, and screen and system audio capture "
            "may not work on them."
        ),
        fix=(
            "1. Open System Settings > General > Software Update and install "
            "the newest macOS offered for your Mac (on macOS 12 and older: "
            "Apple menu > System Preferences > Software Update).\n"
            f"2. If no update to {MIN_MACOS_NAME} or newer is offered, this "
            "Mac is too old to record with this app."
        ),
        blocking=True,
    )


def _tk_too_old_issue(info: PlatformInfo) -> CompatIssue:
    found = format_version(info.tk_version) if info.tk_version else "unknown"
    return CompatIssue(
        code=TK_TOO_OLD,
        title=f"Tk {found} is too old for the app window.",
        detail=(
            f"The window needs Tk {format_version(MIN_TK)} or newer. The "
            "Python that comes with macOS (/usr/bin/python3) uses Tk 8.5, "
            "which draws blank or broken windows on current macOS."
        ),
        fix=(
            "1. Install a Python with a current Tk: brew install python "
            "python-tk (or use the installer from python.org, which includes "
            f"Tk 8.6). {_homebrew_hint(info)}\n"
            "2. Open a new Terminal window so python3 is the new one.\n"
            "3. Delete the old venv folder (rm -rf venv) and start the app "
            "again with ./run.sh."
        ),
        blocking=True,
    )


def _rosetta_issue(info: PlatformInfo) -> CompatIssue:
    return CompatIssue(
        code=RUNNING_UNDER_ROSETTA,
        title="Python is running under Rosetta.",
        detail=(
            "This Mac has an Apple Silicon chip, but the Python running the "
            "app is an Intel build, so everything goes through Rosetta "
            "translation. Recording still works, but it uses more CPU than a "
            "native build."
        ),
        fix=(
            "1. Install a native Python: brew install python python-tk "
            "(Homebrew lives in /opt/homebrew on Apple Silicon Macs).\n"
            "2. If Terminal itself runs under Rosetta, select it in Finder, "
            "choose File > Get Info and untick \"Open using Rosetta\".\n"
            "3. Delete the old venv folder (rm -rf venv) and start the app "
            "again with ./run.sh."
        ),
        blocking=False,
    )


def _untested_issue(version: Version) -> CompatIssue:
    return CompatIssue(
        code=MACOS_UNTESTED,
        title=f"{describe_macos(version)} is newer than the tested versions.",
        detail=(
            f"The app has been tested up to macOS {LATEST_TESTED_MACOS_MAJOR}. "
            "Newer versions are expected to work."
        ),
        fix=(
            "Nothing to do unless something goes wrong. If recording fails, "
            "check the Permissions note in the window and the Troubleshooting "
            "section of the README."
        ),
        blocking=False,
    )


def evaluate(info: PlatformInfo) -> CompatibilityResult:
    """Turn the facts into a verdict. Pure: it touches nothing on the system."""
    issues = []

    version = info.macos_version
    if info.is_macos and version is not None:
        if not version_at_least(version, MIN_MACOS):
            issues.append(_macos_too_old_issue(version))
        elif version[0] > LATEST_TESTED_MACOS_MAJOR:
            issues.append(_untested_issue(version))

    if info.tk_version is not None and not version_at_least(info.tk_version, MIN_TK):
        issues.append(_tk_too_old_issue(info))

    if info.is_macos and info.rosetta:
        issues.append(_rosetta_issue(info))

    # Blocking problems first, each group in the order found.
    issues.sort(key=lambda issue: not issue.blocking)
    return CompatibilityResult(info=info, issues=tuple(issues))


def check_compatibility() -> CompatibilityResult:
    """Check this computer. Never raises; unknown facts never block."""
    try:
        return evaluate(detect_platform())
    except Exception:
        return CompatibilityResult(info=PlatformInfo())


def main() -> int:
    """Print the report for this computer. Exit code 1 if it is unsupported."""
    result = check_compatibility()
    print(result.summary())
    if result.info.is_macos and result.info.macos_version is None:
        print("The macOS version could not be determined; continuing anyway.")
    message = result.message()
    if message:
        print()
        print(message)
    elif result.supported:
        print("This computer meets the requirements.")
    return 0 if result.supported else 1


if __name__ == "__main__":
    sys.exit(main())