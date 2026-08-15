"""
Sampling profiler using sys._current_frames().

sys._current_frames() returns a dict mapping thread_id → top frame for every
active Python thread.  By walking the frame chain (f_back links) we reconstruct
the full call stack without modifying the target code in any way.

The sampler runs in a dedicated daemon thread and records one Sample per
interval.  It stops automatically when:
    - the target thread finishes
    - the configured duration elapses
    - max_samples is reached
    - stop() is called explicitly

No cProfile, no sys.setprofile, no sys.settrace.  This approach has lower
overhead than trace-based profilers and works on any CPython code including
C extensions (the C frames appear as gaps in the stack).
"""

from __future__ import annotations

import sys
import threading
import time
from types import FrameType

from config import FrameInfo, ProfilerConfig, ProfileData, Sample


class Sampler:
    """
    Collects periodic stack samples from a set of target threads.

    Usage:

        sampler = Sampler(config)
        sampler.start(target_thread_ids={threading.main_thread().ident})
        # ... let target run ...
        sampler.stop()
        profile = sampler.profile_data()
    """

    def __init__(self, config: ProfilerConfig):
        self._cfg          = config
        self._samples:  list[Sample] = []
        self._lock         = threading.Lock()
        self._stop_event   = threading.Event()
        self._thread:  threading.Thread | None = None
        self._start_time:  float = 0.0
        self._end_time:    float = 0.0
        self._target_tids: set[int] = set()

    # ── Public API ────────────────────────────────────────────────────────

    def start(self, target_thread_ids: set[int] | None = None):
        """
        Begin sampling.

        If target_thread_ids is None, all threads are sampled.
        """
        self._target_tids  = target_thread_ids or set()
        self._start_time   = time.monotonic()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sample_loop,
            name="pyflame-sampler",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """Signal the sampler to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self._cfg.interval * 10)
        self._end_time = time.monotonic()

    def profile_data(self, target_cmd: str = "", pid: int = 0) -> ProfileData:
        with self._lock:
            return ProfileData(
                samples=list(self._samples),
                start_time=self._start_time,
                end_time=self._end_time or time.monotonic(),
                target_cmd=target_cmd,
                pid=pid,
            )

    # ── Sampling loop ─────────────────────────────────────────────────────

    def _sample_loop(self):
        cfg       = self._cfg
        deadline  = (
            self._start_time + cfg.duration
            if cfg.duration is not None else None
        )

        while not self._stop_event.is_set():
            now = time.monotonic()
            if deadline and now >= deadline:
                break

            self._capture_snapshot(now)

            with self._lock:
                if len(self._samples) >= cfg.max_samples:
                    break

            time.sleep(cfg.interval)

        self._end_time = time.monotonic()

    def _capture_snapshot(self, timestamp: float):
        all_frames = sys._current_frames()
        cfg        = self._cfg

        for tid, top_frame in all_frames.items():
            # Filter by target thread IDs if specified
            if self._target_tids and tid not in self._target_tids:
                continue
            # Skip the sampler thread itself
            if tid == threading.current_thread().ident:
                continue

            stack = self._walk_stack(top_frame)
            if not stack:
                continue

            sample = Sample(
                timestamp=timestamp,
                thread_id=tid,
                stack=tuple(stack),
            )
            with self._lock:
                self._samples.append(sample)

    def _walk_stack(self, top_frame: FrameType) -> list[FrameInfo]:
        """
        Walk the frame chain starting from the topmost (most recent) frame.

        Returns frames in caller-first order (outermost → innermost), matching
        the convention used by most flame graph tools where the root is at the
        bottom and the hot path is at the top.
        """
        frames: list[FrameInfo] = []
        frame: FrameType | None = top_frame

        while frame is not None:
            filename = frame.f_code.co_filename
            lineno   = frame.f_lineno
            funcname = frame.f_code.co_name

            # Skip C extension frames unless configured to include them
            if not self._cfg.include_c_frames and filename.startswith("<"):
                frame = frame.f_back
                continue

            frames.append(FrameInfo(filename=filename, lineno=lineno, funcname=funcname))
            frame = frame.f_back

        frames.reverse()   # make it caller-first (outermost at index 0)
        return frames


# ---------------------------------------------------------------------------
# Context manager convenience wrapper
# ---------------------------------------------------------------------------

class ProfileSession:
    """
    Context manager that profiles the block and returns a ProfileData.

        with ProfileSession(config) as p:
            ... code to profile ...
        p.profile  # ProfileData
    """

    def __init__(self, config: ProfilerConfig | None = None):
        self._config  = config or ProfilerConfig()
        self._sampler = Sampler(self._config)
        self.profile: ProfileData | None = None

    def __enter__(self) -> "ProfileSession":
        self._sampler.start({threading.current_thread().ident})
        return self

    def __exit__(self, *_):
        self._sampler.stop()
        self.profile = self._sampler.profile_data()
        return False
