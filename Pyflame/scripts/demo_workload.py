#!/usr/bin/env python3
"""
Workload demo used to test the profiler.

Runs three functions with known relative costs so the flame graph
can be visually verified.  fast_work appears briefly, slow_work
dominates, and medium_work sits in between.

Usage:
    python profile.py scripts/demo_workload.py
"""

import math
import time


def fast_work(n: int = 500) -> float:
    return sum(math.sqrt(i) for i in range(n))


def slow_work(n: int = 200_000) -> float:
    total = 0.0
    for i in range(n):
        total += math.sin(i) * math.cos(i)
    return total


def medium_work(n: int = 50_000) -> float:
    return sum(i ** 2 for i in range(n))


def io_simulation(delay: float = 0.05) -> None:
    time.sleep(delay)


def main():
    results = []
    for _ in range(3):
        results.append(fast_work())
        results.append(slow_work())
        results.append(medium_work())
        io_simulation(0.01)
    print(f"Done. checksum={sum(results):.2f}")


if __name__ == "__main__":
    main()
