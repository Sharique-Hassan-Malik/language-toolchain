from __future__ import annotations

import json
from pathlib import Path

from config import FrameInfo, ProfileData, Sample
from profiler.aggregator import FlameRoot


class ProfileSerializer:
    """
    Serialises ProfileData to JSON and deserialises it back.

    Format:

        {
          "version": 1,
          "start_time": 0.0,
          "end_time": 1.234,
          "target_cmd": "python myscript.py",
          "pid": 12345,
          "samples": [
            {
              "ts": 0.001,
              "tid": 140234,
              "stack": [
                ["filename", lineno, "funcname"],
                ...
              ]
            },
            ...
          ]
        }
    """

    VERSION = 1

    def save(self, data: ProfileData, path: str):
        Path(path).write_text(json.dumps(self._to_dict(data), indent=2))

    def load(self, path: str) -> ProfileData:
        raw = json.loads(Path(path).read_text())
        return self._from_dict(raw)

    def save_flame_tree(self, root: FlameRoot, path: str):
        Path(path).write_text(json.dumps(root.to_dict(), indent=2))

    # ── Serialisation helpers ─────────────────────────────────────────────

    def _to_dict(self, data: ProfileData) -> dict:
        return {
            "version":    self.VERSION,
            "start_time": data.start_time,
            "end_time":   data.end_time,
            "target_cmd": data.target_cmd,
            "pid":        data.pid,
            "samples": [
                {
                    "ts":    s.timestamp,
                    "tid":   s.thread_id,
                    "stack": [
                        [f.filename, f.lineno, f.funcname]
                        for f in s.stack
                    ],
                }
                for s in data.samples
            ],
        }

    def _from_dict(self, raw: dict) -> ProfileData:
        samples = []
        for s in raw.get("samples", []):
            stack = tuple(
                FrameInfo(filename=f[0], lineno=f[1], funcname=f[2])
                for f in s["stack"]
            )
            samples.append(Sample(
                timestamp=s["ts"],
                thread_id=s["tid"],
                stack=stack,
            ))
        return ProfileData(
            samples=samples,
            start_time=raw.get("start_time", 0.0),
            end_time=raw.get("end_time", 0.0),
            target_cmd=raw.get("target_cmd", ""),
            pid=raw.get("pid", 0),
        )
