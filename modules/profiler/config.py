from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProfilerConfig:
    # Sampling interval in seconds
    interval:        float = 0.001    # 1 ms
    # Maximum wall-clock duration to profile (None = unlimited)
    duration:        float | None = None
    # Maximum number of samples to collect
    max_samples:     int = 100_000
    # Include C extension frames (those with no Python source file)
    include_c_frames: bool = False
    # Minimum number of samples a frame must appear in to be shown
    min_samples:     int = 1
    # Output paths
    output_json:     str = "profile.json"
    output_html:     str = "flamegraph.html"


@dataclass(frozen=True)
class FrameInfo:
    """One frame in a call stack."""
    filename:   str
    lineno:     int
    funcname:   str

    def __str__(self) -> str:
        short = self.filename.split("/")[-1] if "/" in self.filename else self.filename
        return f"{self.funcname} ({short}:{self.lineno})"


@dataclass
class Sample:
    """One stack snapshot captured at a point in time."""
    timestamp:  float            # monotonic seconds
    thread_id:  int
    stack:      tuple[FrameInfo, ...]  # outermost (caller) first


@dataclass
class ProfileData:
    """Accumulated profile data from a completed profiling session."""
    samples:     list[Sample]  = field(default_factory=list)
    start_time:  float         = 0.0
    end_time:    float         = 0.0
    target_cmd:  str           = ""
    pid:         int           = 0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def threads(self) -> set[int]:
        return {s.thread_id for s in self.samples}
