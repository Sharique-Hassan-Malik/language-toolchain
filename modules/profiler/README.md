# PyFlame — Python Profiler with Flame Graph UI

> Part of the [Language Toolchain](../../README.md). Runs standalone from this
> folder; `lang` joins the compiler, runtime and profiler into one pipeline.

A sampling profiler that captures periodic call stack snapshots, aggregates
them into a call tree and renders an interactive flame graph in the browser.

Built on `sys._current_frames()` — no cProfile, no sys.settrace, no
external dependencies.

---

## Features

- Sampling via `sys._current_frames()` — near-zero overhead, no trace hooks
- Configurable sampling interval (default 1 ms)
- Profiles scripts, modules (`-m`) or loads saved profiles
- Recursive call tree aggregation with total and self sample counts
- Self-contained interactive HTML flame graph — hover tooltips, search, breadcrumbs
- Colour coding by source file — same hue for frames from the same module
- Top-N hottest functions table in the flame graph page
- Profile saved as JSON for later analysis or re-rendering
- Built-in HTTP server serves the flame graph on localhost
- 35+ offline pytest tests — no network, no subprocess required

---

## Requirements

Python 3.11+ — no runtime dependencies.

```bash
pip install pytest   # for running tests only
```

---

## Usage

### Profile a script

```bash
python profile.py myscript.py
```

Opens `http://localhost:8080` with the interactive flame graph.

### Profile a module

```bash
python profile.py -m json.tool < data.json
```

### Options

```
--interval SECS      Sampling interval (default: 0.001 = 1 ms)
--duration SECS      Stop after this many seconds
--max-samples N      Stop after this many samples (default: 100 000)
--include-c          Include C extension frames
--output-json PATH   Profile JSON output path (default: profile.json)
--output-html PATH   Flame graph HTML output (default: flamegraph.html)
--load PATH          Load an existing profile.json
--port N             HTTP server port (default: 8080)
--no-browser         Generate files but don't open the browser
--no-serve           Generate files only, skip the HTTP server
--width PX           Flame graph width in pixels (default: 1200)
```

### Generate files without serving

```bash
python profile.py myscript.py --no-serve
# Produces profile.json and flamegraph.html
```

### Load and re-render a saved profile

```bash
python profile.py --load profile.json --port 9090
```

---

## Demo Workload

A demo script with known relative costs validates the profiler output:

```bash
python profile.py scripts/demo_workload.py --no-browser
```

`slow_work` should dominate the flame graph, `medium_work` should appear
next, and `fast_work` should be a narrow sliver.

---

## Programmatic API

```python
from config import ProfilerConfig
from profiler.sampler import ProfileSession
from profiler.aggregator import Aggregator
from ui.flamegraph import FlamegraphRenderer

cfg = ProfilerConfig(interval=0.001, max_samples=10_000)

with ProfileSession(cfg) as p:
    # ... code to profile ...
    result = my_expensive_function()

root = Aggregator().aggregate(p.profile)
html = FlamegraphRenderer().render(root, title="My Profile")
open("flamegraph.html", "w").write(html)
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## Architecture Summary

```
sys._current_frames()          every `interval` seconds
    │
    ▼
Sampler._walk_stack()          frame.f_back chain → list[FrameInfo]
    │
    ▼
ProfileData (list[Sample])
    │
    ▼
Aggregator.aggregate()         call tree with total and self sample counts
    │
    ├──► profile.json           (ProfileSerializer)
    └──► flamegraph.html        (FlamegraphRenderer)
                │
                ▼
         FlameServer → http://localhost:8080
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed explanation of the
sampling mechanism, aggregation algorithm and flame graph layout.

---

## Project Structure

```
pyflame/
├── profile.py
├── config.py
├── profiler/
│   ├── sampler.py
│   ├── aggregator.py
│   └── serializer.py
├── ui/
│   ├── flamegraph.py
│   └── server.py
├── tests/
│   └── test_profiler.py
└── scripts/
    └── demo_workload.py
```
