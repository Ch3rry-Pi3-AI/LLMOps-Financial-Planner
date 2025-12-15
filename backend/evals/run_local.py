#!/usr/bin/env python3
"""
Run local, deterministic evals against agent helper functions.

This runner executes eval scripts inside each agent directory so their local
imports (e.g. `from agent import ...`) and per-agent environments work.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


def _run(cmd: List[str], cwd: Path) -> Tuple[bool, str]:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    env.pop("VIRTUAL_ENV", None)
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
    return result.returncode == 0, output.strip()


def main() -> int:
    backend_dir = Path(__file__).resolve().parent.parent
    checks = [
        ("charter", backend_dir / "charter", ["uv", "run", "eval_local.py"]),
        ("retirement", backend_dir / "retirement", ["uv", "run", "eval_local.py"]),
        ("tagger", backend_dir / "tagger", ["uv", "run", "eval_local.py"]),
        ("planner", backend_dir / "planner", ["uv", "run", "eval_local.py"]),
    ]

    failures: list[str] = []
    for name, cwd, cmd in checks:
        ok, out = _run(cmd, cwd)
        print(f"== {name} ==")
        if out:
            print(out)
        if not ok:
            failures.append(name)
        print()

    if failures:
        print("FAILED:", ", ".join(failures))
        return 1

    print("PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
