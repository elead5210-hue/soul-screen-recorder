"""Soak test: record unattended for a long time and report how it went.

Usage (on the Mac, with the camera, microphone and screen permissions
already granted and the sound output set to the Multi-Output Device):

    python3 -m recorder.soak --minutes 30

The test drives the real app logic: it presses Record on the controller,
leaves the recording running, then presses Stop, waits for final.mp4 and
checks the finished session folder. While recording it samples, every few
seconds:

  - the CPU use and memory of every ffmpeg process the app started,
  - the size of camera.mp4 and screen.mp4 (they must keep growing),
  - whether the app's own threads stay responsive (a heartbeat thread that
    must wake up on time, how long a controller call takes, and that the
    capture monitor thread is still alive).

Afterwards the session is verified with recorder.verify, including the audio
levels, the audio-versus-video lengths (dropped audio) and a minimum length,
and a PASS / FAIL report with the measurements is printed. Exit status:
0 = every check passed, 1 = a check failed, 2 = the test could not be run
(or was given bad options), 130 = interrupted with Ctrl-C (the recording is
stopped cleanly and kept).

CPU is read with `ps`, which reports a decayed average rather than an
instant value on macOS; it is good enough to tell low CPU (hardware
encoding) from an encoder that is using whole cores. Standard library only.
"""

import argparse
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from recorder.controller import RecorderController
from recorder.stability import format_elapsed
from recorder.state import RecorderState
from recorder.verify import SessionCheck, VerifyError, format_report, verify_session

DEFAULT_MINUTES = 30.0
DEFAULT_SAMPLE_SECONDS = 5.0

# Pass / fail limits (all can be changed on the command line).
DEFAULT_MAX_CPU_PERCENT = 150.0       # all ffmpeg processes together, average
DEFAULT_MAX_MEMORY_MB = 1500.0        # all ffmpeg processes together, peak
DEFAULT_MAX_MEMORY_GROWTH_MB = 300.0  # growth from the start to the end
DEFAULT_MAX_UI_LAG_SECONDS = 2.0      # latest a heartbeat may wake up
DEFAULT_MAX_STALL_SECONDS = 30.0      # longest a raw file may stop growing

# How long to wait for the recording to start, and the extra time (beyond
# twice the recording length) allowed for stopping and creating final.mp4.
START_TIMEOUT_SECONDS = 120.0
STOP_TIMEOUT_MIN_SECONDS = 600.0

# A session may be this much shorter than asked for (start-up and stop).
LENGTH_TOLERANCE_SECONDS = 10.0

MONITOR_THREAD_NAME = "capture-monitor"


# ---- measurements ----------------------------------------------------------

@dataclass(frozen=True)
class Sample:
    """One round of measurements."""

    at: float                      # seconds since recording started
    cpu_percent: float             # all ffmpeg processes together
    memory_mb: float               # resident memory, all ffmpeg processes
    ffmpeg_count: int
    sizes: Dict[str, int]          # file name -> bytes
    controller_call_seconds: float
    monitor_alive: bool


@dataclass(frozen=True)
class CheckResult:
    """One line of the final report."""

    name: str
    ok: bool
    detail: str


@dataclass
class SoakData:
    """Everything the test measured."""

    samples: List[Sample] = field(default_factory=list)
    states: List[Tuple[float, RecorderState, Optional[str]]] = field(
        default_factory=list
    )
    max_ui_lag: float = 0.0
    recorded_seconds: float = 0.0
    start_error: Optional[str] = None
    final_state: Optional[RecorderState] = None
    final_message: Optional[str] = None
    interrupted: bool = False
    session_folder: Optional[Path] = None
    verification: Optional[SessionCheck] = None
    verify_error: Optional[str] = None


def read_ffmpeg_processes(parent_pid: Optional[int] = None) -> List[Tuple[int, float, float]]:
    """(pid, cpu percent, resident MB) of the ffmpeg children of `parent_pid`.

    Defaults to this process. Returns an empty list if `ps` cannot be run.
    """
    parent = os.getpid() if parent_pid is None else parent_pid
    try:
        result = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,pcpu=,rss=,comm="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    found: List[Tuple[int, float, float]] = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
            cpu, rss_kb = float(parts[2]), float(parts[3])
        except ValueError:
            continue
        if ppid == parent and "ffmpeg" in os.path.basename(parts[4]).lower():
            found.append((pid, cpu, rss_kb / 1024.0))
    return found


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


class _Heartbeat:
    """A thread that should wake up once a second; records how late it ever was.

    If the app's threads were starved or blocked (a frozen interpreter, a
    lock held for too long), the heartbeat would wake up late.
    """

    def __init__(self, period: float = 1.0) -> None:
        self._period = period
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="soak-heartbeat", daemon=True)
        self.max_lag = 0.0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        expected = time.monotonic() + self._period
        while not self._stop.wait(max(0.0, expected - time.monotonic())):
            now = time.monotonic()
            self.max_lag = max(self.max_lag, now - expected)
            expected = now + self._period


def _monitor_alive() -> bool:
    return any(t.name == MONITOR_THREAD_NAME and t.is_alive() for t in threading.enumerate())


def _wait_for_state(
    controller: RecorderController,
    wanted: Tuple[RecorderState, ...],
    timeout: float,
) -> RecorderState:
    """Wait until the controller reaches one of `wanted`; returns the state seen."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = controller.state
        if state in wanted:
            return state
        time.sleep(0.2)
    return controller.state


# ---- the soak run ----------------------------------------------------------

def run_soak(
    minutes: float,
    sample_seconds: float = DEFAULT_SAMPLE_SECONDS,
    controller: Optional[RecorderController] = None,
    log=print,
) -> SoakData:
    """Record for `minutes` through the controller and collect measurements.

    Never raises for a recording problem: it ends up in the returned data.
    """
    data = SoakData()
    controller = controller or RecorderController()
    clock_start = time.monotonic()

    def on_state(state: RecorderState, message: Optional[str]) -> None:
        data.states.append((time.monotonic() - clock_start, state, message))

    controller.add_listener(on_state)
    heartbeat = _Heartbeat()
    heartbeat.start()

    try:
        log("Pressing Record...")
        controller.toggle()
        seen = _wait_for_state(
            controller,
            (RecorderState.RECORDING, RecorderState.ERROR),
            START_TIMEOUT_SECONDS,
        )
        if seen != RecorderState.RECORDING:
            data.start_error = controller.message or "The recording did not start in time."
            data.final_state = controller.state
            data.final_message = controller.message
            return data

        session = controller.session
        names: Dict[str, Path] = {}
        if session is not None:
            data.session_folder = session.folder
            names = {
                session.camera_path.name: session.camera_path,
                session.screen_path.name: session.screen_path,
            }
        log(f"Recording for {minutes:g} minutes into {data.session_folder} ...")

        target = minutes * 60
        started = time.monotonic()
        while True:
            elapsed = time.monotonic() - started
            if elapsed >= target or controller.state != RecorderState.RECORDING:
                break
            time.sleep(min(sample_seconds, max(0.1, target - elapsed)))

            call_start = time.monotonic()
            state = controller.state
            controller.elapsed_seconds()
            call_seconds = time.monotonic() - call_start

            procs = read_ffmpeg_processes()
            sample = Sample(
                at=time.monotonic() - started,
                cpu_percent=sum(p[1] for p in procs),
                memory_mb=sum(p[2] for p in procs),
                ffmpeg_count=len(procs),
                sizes={name: _file_size(path) for name, path in names.items()},
                controller_call_seconds=call_seconds,
                monitor_alive=_monitor_alive(),
            )
            data.samples.append(sample)
            sizes = ", ".join(f"{n} {s / 1e6:.0f} MB" for n, s in sample.sizes.items())
            log(
                f"  {format_elapsed(sample.at)}  ffmpeg x{sample.ffmpeg_count}  "
                f"CPU {sample.cpu_percent:.0f}%  mem {sample.memory_mb:.0f} MB  {sizes}"
            )
            if state != RecorderState.RECORDING:
                break

        data.recorded_seconds = time.monotonic() - started

        if controller.state == RecorderState.RECORDING:
            log("Pressing Stop...")
            controller.toggle()
        timeout = max(STOP_TIMEOUT_MIN_SECONDS, 2 * target)
        _wait_for_state(
            controller, (RecorderState.DONE, RecorderState.ERROR), timeout
        )
        data.final_state = controller.state
        data.final_message = controller.message
        return data
    except KeyboardInterrupt:
        data.interrupted = True
        log("Interrupted: stopping the recording cleanly...")
        controller.shutdown()
        data.final_state = controller.state
        data.final_message = controller.message
        return data
    finally:
        heartbeat.stop()
        data.max_ui_lag = heartbeat.max_lag


# ---- judging the measurements ---------------------------------------------

def _longest_stall(samples: List[Sample], name: str) -> float:
    """Longest time (seconds) the named file went without growing."""
    longest = 0.0
    last_size: Optional[int] = None
    last_growth = 0.0
    for sample in samples:
        size = sample.sizes.get(name, 0)
        if last_size is None or size > last_size:
            last_size = size
            last_growth = sample.at
        else:
            longest = max(longest, sample.at - last_growth)
    return longest


def evaluate(
    data: SoakData,
    minutes: float,
    max_cpu: float = DEFAULT_MAX_CPU_PERCENT,
    max_memory_mb: float = DEFAULT_MAX_MEMORY_MB,
    max_memory_growth_mb: float = DEFAULT_MAX_MEMORY_GROWTH_MB,
    max_ui_lag: float = DEFAULT_MAX_UI_LAG_SECONDS,
    max_stall: float = DEFAULT_MAX_STALL_SECONDS,
) -> List[CheckResult]:
    """Turn the measurements into PASS / FAIL results."""
    results: List[CheckResult] = []

    if data.start_error is not None:
        results.append(CheckResult("Recording started", False, data.start_error))
        return results
    results.append(CheckResult("Recording started", True, "Record reached the Recording state"))

    # 1. The recording ran for the whole time without an error.
    errors = [m for _, s, m in data.states if s == RecorderState.ERROR]
    needed = minutes * 60 - LENGTH_TOLERANCE_SECONDS
    if errors:
        results.append(CheckResult("Ran without errors", False, (errors[0] or "").splitlines()[0] if errors[0] else "an error was reported"))
    elif data.recorded_seconds < needed:
        results.append(CheckResult(
            "Ran without errors", False,
            f"stopped after {format_elapsed(data.recorded_seconds)} of {minutes:g} minutes",
        ))
    else:
        results.append(CheckResult(
            "Ran without errors", True,
            f"recorded {format_elapsed(data.recorded_seconds)} with no error",
        ))

    # 2. The recording finished: Done, with all three files.
    done = data.final_state == RecorderState.DONE
    results.append(CheckResult(
        "Finished with three files", done,
        (data.final_message or "Done") if done
        else f"ended in the {data.final_state.name if data.final_state else 'unknown'} state"
        + (f": {(data.final_message or '').splitlines()[0]}" if data.final_message else ""),
    ))

    samples = data.samples
    if samples:
        # 3. CPU stays low (hardware encoding).
        avg_cpu = sum(s.cpu_percent for s in samples) / len(samples)
        peak_cpu = max(s.cpu_percent for s in samples)
        results.append(CheckResult(
            "Low CPU", avg_cpu <= max_cpu,
            f"ffmpeg average {avg_cpu:.0f}%, peak {peak_cpu:.0f}% (limit {max_cpu:.0f}% average)",
        ))

        # 4. Memory does not grow without bound.
        peak_mem = max(s.memory_mb for s in samples)
        quarter = max(1, len(samples) // 4)
        early = sum(s.memory_mb for s in samples[:quarter]) / quarter
        late = sum(s.memory_mb for s in samples[-quarter:]) / quarter
        growth = late - early
        results.append(CheckResult(
            "Stable memory", peak_mem <= max_memory_mb and growth <= max_memory_growth_mb,
            f"peak {peak_mem:.0f} MB, growth {growth:+.0f} MB from start to end "
            f"(limits {max_memory_mb:.0f} MB and {max_memory_growth_mb:.0f} MB)",
        ))

        # 5. Both ffmpeg processes stayed alive the whole time.
        fewest = min(s.ffmpeg_count for s in samples)
        results.append(CheckResult(
            "Both captures kept running", fewest >= 2,
            f"at least {fewest} ffmpeg process(es) in every sample (expected 2)",
        ))

        # 6. The raw files kept growing.
        stalls = {
            name: _longest_stall(samples, name) for name in samples[0].sizes
        }
        worst = max(stalls.values()) if stalls else 0.0
        detail = ", ".join(f"{n} longest quiet {v:.0f}s" for n, v in stalls.items())
        results.append(CheckResult(
            "Files kept growing", worst <= max_stall,
            f"{detail} (limit {max_stall:.0f}s)" if detail else "no files were sampled",
        ))

        # 7. The app's threads stayed responsive.
        slowest_call = max(s.controller_call_seconds for s in samples)
        monitor_missing = sum(1 for s in samples if not s.monitor_alive)
        responsive = (
            data.max_ui_lag <= max_ui_lag
            and slowest_call <= max_ui_lag
            and monitor_missing == 0
        )
        results.append(CheckResult(
            "App stayed responsive", responsive,
            f"heartbeat at most {data.max_ui_lag:.2f}s late, slowest controller call "
            f"{slowest_call * 1000:.0f} ms, monitor thread missing in {monitor_missing} "
            f"of {len(samples)} samples (limit {max_ui_lag:.1f}s)",
        ))
    else:
        results.append(CheckResult("Measurements taken", False, "no samples were collected"))

    # 8. The finished files pass the verify checks.
    if data.verify_error is not None:
        results.append(CheckResult("Files verified", False, data.verify_error))
    elif data.verification is not None:
        check = data.verification
        failed = [f"{f.name} {f.detail}" for f in check.failed]
        warned = [f"{f.name} {f.detail}" for f in check.files if f.ok and f.warning]
        detail = "all checks passed (playable, audio audible, lengths match)"
        if failed:
            detail = "; ".join(failed)
        elif warned:
            detail += "; warnings: " + "; ".join(warned)
        results.append(CheckResult("Files verified", check.ok, detail))
    else:
        results.append(CheckResult("Files verified", False, "the session folder was not checked"))

    return results


def verify_result(data: SoakData, minutes: float) -> None:
    """Run the verify checks (video, audio levels, lengths, minimum length)."""
    if data.session_folder is None:
        return
    min_minutes = max(0.0, minutes * 60 - LENGTH_TOLERANCE_SECONDS) / 60
    try:
        data.verification = verify_session(
            data.session_folder,
            with_audio=True,
            with_lengths=True,
            min_minutes=min_minutes,
        )
    except VerifyError as exc:
        data.verify_error = str(exc)


def format_soak_report(data: SoakData, results: List[CheckResult], minutes: float) -> str:
    lines = [
        "",
        f"Soak test: {minutes:g} minute recording",
        f"Session: {data.session_folder or 'none'}",
    ]
    for item in results:
        lines.append(f"  [{'PASS' if item.ok else 'FAIL'}] {item.name}: {item.detail}")
    if data.verification is not None:
        lines.append("")
        lines.append(format_report(data.verification))
    failed = [r for r in results if not r.ok]
    lines.append("")
    if failed:
        lines.append(f"FAILED: {len(failed)} of {len(results)} checks did not pass.")
    else:
        lines.append(f"PASSED: all {len(results)} checks passed.")
    return "\n".join(lines)


# ---- command line ----------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m recorder.soak",
        description=(
            "Record unattended through the app's controller, measure CPU, memory, "
            "file growth and responsiveness, then verify the finished files."
        ),
    )
    parser.add_argument("--minutes", type=float, default=DEFAULT_MINUTES,
                        help=f"how long to record (default {DEFAULT_MINUTES:g})")
    parser.add_argument("--interval", type=float, default=DEFAULT_SAMPLE_SECONDS,
                        help=f"seconds between measurements (default {DEFAULT_SAMPLE_SECONDS:g})")
    parser.add_argument("--max-cpu", type=float, default=DEFAULT_MAX_CPU_PERCENT,
                        help="highest average CPU %% of all ffmpeg processes together")
    parser.add_argument("--max-memory-mb", type=float, default=DEFAULT_MAX_MEMORY_MB,
                        help="highest memory (MB) of all ffmpeg processes together")
    parser.add_argument("--max-memory-growth-mb", type=float, default=DEFAULT_MAX_MEMORY_GROWTH_MB,
                        help="largest memory growth (MB) from start to end")
    parser.add_argument("--max-ui-lag", type=float, default=DEFAULT_MAX_UI_LAG_SECONDS,
                        help="longest (seconds) a thread may be unresponsive")
    parser.add_argument("--max-stall", type=float, default=DEFAULT_MAX_STALL_SECONDS,
                        help="longest (seconds) a raw file may stop growing")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.minutes <= 0 or args.interval <= 0:
        print("Error: --minutes and --interval must be greater than 0.", file=sys.stderr)
        return 2

    try:
        data = run_soak(args.minutes, args.interval)
    except Exception as exc:  # the test itself could not run
        print(f"Error: the soak test could not run: {exc}", file=sys.stderr)
        return 2

    if data.interrupted:
        print("Interrupted. The raw files were finalized and kept.")
        return 130

    if data.final_state == RecorderState.DONE or data.session_folder is not None:
        verify_result(data, args.minutes)

    results = evaluate(
        data,
        args.minutes,
        max_cpu=args.max_cpu,
        max_memory_mb=args.max_memory_mb,
        max_memory_growth_mb=args.max_memory_growth_mb,
        max_ui_lag=args.max_ui_lag,
        max_stall=args.max_stall,
    )
    print(format_soak_report(data, results, args.minutes))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())