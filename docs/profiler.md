# Architecture — Python Profiler with Flame Graph UI

## Overview

A sampling profiler that captures periodic call stack snapshots from a
running Python process, aggregates them into a call tree and renders an
interactive flame graph in the browser — built entirely on CPython internals,
no cProfile and no sys.settrace.

---

## How the Sampler Works

The profiler uses `sys._current_frames()`, a CPython internal that returns a
dict mapping each active thread's ID to its topmost frame object.

```python
all_frames = sys._current_frames()   # {thread_id: frame}
```

From the top frame, the sampler walks the frame chain backwards through
`frame.f_back` links, reading `co_filename`, `f_lineno` and `co_name` from
each frame's code object.  This reconstructs the full call stack at that
instant.

The sampler runs in a dedicated daemon thread that wakes every
`config.interval` seconds, calls `sys._current_frames()` and stores the
snapshot.  It never pauses the target thread.

**Why not sys.settrace / sys.setprofile?**

Trace-based profilers fire a callback on every function call, return and
exception — which can slow the target by 10–50×.  `sys._current_frames()`
has near-zero overhead: it reads existing data structures from the CPython
interpreter without modifying execution.  The tradeoff is that infrequent
calls (e.g. functions that return faster than the sampling interval) may be
underrepresented.

---

## Pipeline

```
sys._current_frames()     ← called every `interval` seconds by daemon thread
    │
    ▼
Sampler._walk_stack()     frame chain → list[FrameInfo]
    │                     (reversed to caller-first order)
    ▼
Sample(timestamp, thread_id, stack)
    │
    ▼ list[Sample] in ProfileData
    │
    ▼
Aggregator.aggregate()    replay samples into FlameRoot call tree
    │                     each stack increments total_samples on every node,
    │                     self_samples on the leaf node only
    ▼
FlameRoot (tree of FlameNode)
    │
    ├──► ProfileSerializer.save()    → profile.json
    │
    └──► FlamegraphRenderer.render() → flamegraph.html
              │
              ▼
         FlameServer.serve()  → http://localhost:8080
```

---

## Aggregation

Each sample is a call stack in caller-first order:

```
[outer_caller, ..., innermost_callee]
```

The aggregator replays every stack into a shared tree:

```
root → stack[0] → stack[1] → ... → stack[-1]
```

At each node:
- `total_samples` is incremented (this function was on the call stack)
- `self_samples` is incremented only at the leaf (this function was executing)

`self_samples / total_samples` gives the "self time fraction" — time spent
in the function body, not in callees.

---

## Flame Graph Rendering

The renderer uses a recursive layout algorithm:

1. Total width budget = `config.width` pixels.
2. For each node, `width = (node.total_samples / root.total_samples) × total_width`.
3. Nodes narrower than 2 px are skipped.
4. Children are laid out left-to-right, sorted by `total_samples` descending.
5. Y position = `depth × frame_height`.

Each rectangle is one `<rect>` element in an inline SVG.  Labels are clipped
to the rectangle's width using `<clipPath>`.

Colour is a deterministic HSL value derived from `md5(filename) % 360`, so
frames from the same source file share the same hue, making module boundaries
visible at a glance.

---

## Interactive Features (JavaScript)

All interactivity is inline JavaScript with no external libraries:

| Feature | Implementation |
|---------|----------------|
| Hover tooltip | `mousemove` on `<svg>`, reads `data-*` attributes from `.frame` |
| Search | `input` event filters `.frame` elements, adds `dimmed` class to non-matches |
| Breadcrumbs | Click records the function name, displays navigation trail |
| Reset | Clears search, breadcrumbs |

---

## Data Format

Profile JSON:

```json
{
  "version": 1,
  "start_time": 1234567890.123,
  "end_time":   1234567891.456,
  "target_cmd": "python myscript.py",
  "pid": 12345,
  "samples": [
    {
      "ts":  0.001,
      "tid": 140234567,
      "stack": [
        ["path/to/file.py", 42, "outer_func"],
        ["path/to/file.py", 17, "inner_func"]
      ]
    }
  ]
}
```

---

## Files

```
pyflame/
├── profile.py                  — CLI entry point
├── config.py                   — FrameInfo, Sample, ProfileData, ProfilerConfig
├── profiler/
│   ├── sampler.py              — sys._current_frames() sampling loop
│   ├── aggregator.py           — FlameRoot/FlameNode call tree builder
│   └── serializer.py           — JSON save and load
├── ui/
│   ├── flamegraph.py           — SVG/HTML flame graph renderer
│   └── server.py               — stdlib HTTP server
├── tests/
│   └── test_profiler.py        — 35+ tests, all offline
└── scripts/
    └── demo_workload.py        — known-cost workload for visual validation
```
