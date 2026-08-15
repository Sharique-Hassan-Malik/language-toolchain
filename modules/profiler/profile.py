#!/usr/bin/env python3
"""
PyFlame — sampling profiler with interactive flame graph UI.

Usage — profile a script:
    python profile.py myscript.py [args...]
    python profile.py -m mymodule [args...]
    python profile.py --interval 0.5 --duration 10 myscript.py

Usage — load an existing profile:
    python profile.py --load profile.json
    python profile.py --load profile.json --no-browser

Usage — view flame graph from a saved JSON:
    python profile.py --load profile.json --port 8090
"""

import argparse
import runpy
import sys
import threading
import time
from pathlib import Path

from config import ProfilerConfig, ProfileData
from profiler.sampler import Sampler
from profiler.aggregator import Aggregator
from profiler.serializer import ProfileSerializer
from ui.flamegraph import FlamegraphRenderer
from ui.server import FlameServer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sampling profiler with interactive flame graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("script", nargs="?",
                   help="Script to profile (use -- before script args)")
    p.add_argument("-m", "--module", default=None,
                   help="Profile a module as if run with python -m")
    p.add_argument("--interval",  type=float, default=0.001,
                   help="Sampling interval in seconds (default: 0.001)")
    p.add_argument("--duration",  type=float, default=None,
                   help="Maximum profiling duration in seconds")
    p.add_argument("--max-samples", type=int, default=100_000,
                   dest="max_samples")
    p.add_argument("--include-c",  action="store_true", dest="include_c",
                   help="Include C extension frames")
    p.add_argument("--output-json", default="profile.json", dest="output_json")
    p.add_argument("--output-html", default="flamegraph.html", dest="output_html")
    p.add_argument("--load",  default=None,
                   help="Load an existing profile.json instead of running a script")
    p.add_argument("--port",  type=int, default=8080)
    p.add_argument("--no-browser", action="store_true", dest="no_browser")
    p.add_argument("--no-serve",   action="store_true", dest="no_serve",
                   help="Generate files only, do not start the HTTP server")
    p.add_argument("--width", type=int, default=1200,
                   help="Flame graph width in pixels")
    # Remaining args passed through to the profiled script
    p.add_argument("script_args", nargs=argparse.REMAINDER)
    return p.parse_args()


def run_and_profile(
    config: ProfilerConfig,
    script: str | None,
    module: str | None,
    script_args: list[str],
) -> ProfileData:
    sampler    = Sampler(config)
    main_tid   = threading.current_thread().ident

    # Patch sys.argv so the profiled script sees the right arguments
    orig_argv  = sys.argv[:]
    if script:
        sys.argv = [script] + script_args
    elif module:
        sys.argv = [module] + script_args

    sampler.start({main_tid})
    try:
        if script:
            with open(script) as f:
                code = compile(f.read(), script, "exec")
            exec(code, {"__name__": "__main__", "__file__": script})
        elif module:
            runpy.run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit:
        pass
    finally:
        sampler.stop()
        sys.argv = orig_argv

    cmd = f"python -m {module}" if module else script or ""
    return sampler.profile_data(target_cmd=cmd)


def generate_outputs(
    data: ProfileData,
    output_json: str,
    output_html: str,
    width: int,
    interval_ms: float,
) -> tuple[str, str]:
    serializer = ProfileSerializer()
    aggregator = Aggregator()
    renderer   = FlamegraphRenderer(width=width)

    serializer.save(data, output_json)

    root  = aggregator.aggregate(data)
    html  = renderer.render(root, title=f"Flame Graph — {data.target_cmd}",
                            sample_interval_ms=interval_ms)
    Path(output_html).write_text(html)

    print(f"Profile saved  : {output_json}  ({data.sample_count} samples)")
    print(f"Flame graph    : {output_html}")
    return output_json, output_html


def print_top_functions(data: ProfileData, n: int = 10):
    from profiler.aggregator import Aggregator
    root  = Aggregator().aggregate(data)
    top   = Aggregator.hottest_functions(root, n=n)
    total = max(data.sample_count, 1)

    print(f"\n{'─'*60}")
    print(f"{'Function':<35} {'File':<20} {'Self %':>7}")
    print("─" * 60)
    for node in top:
        pct   = node.self_samples / total * 100
        fname = node.frame.funcname[:34]
        ffile = node.frame.filename.split("/")[-1][:19]
        print(f"{fname:<35} {ffile:<20} {pct:>6.1f}%")
    print("─" * 60)


def main():
    args   = parse_args()
    config = ProfilerConfig(
        interval=args.interval,
        duration=args.duration,
        max_samples=args.max_samples,
        include_c_frames=args.include_c,
        output_json=args.output_json,
        output_html=args.output_html,
    )

    if args.load:
        print(f"Loading profile from {args.load}")
        data = ProfileSerializer().load(args.load)
    elif args.script or args.module:
        target = args.script or args.module
        print(f"Profiling: {target}  (interval={config.interval*1000:.1f} ms)")
        data = run_and_profile(config, args.script, args.module, args.script_args)
        print(f"Profiling complete. {data.sample_count} samples in {data.duration:.2f}s")
        print_top_functions(data)
    else:
        print("Error: specify a script, --module or --load.", file=sys.stderr)
        sys.exit(1)

    output_json, output_html = generate_outputs(
        data,
        args.output_json,
        args.output_html,
        args.width,
        config.interval * 1000,
    )

    if not args.no_serve:
        server = FlameServer(
            html_path=output_html,
            json_path=output_json,
            port=args.port,
        )
        server.serve(open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
