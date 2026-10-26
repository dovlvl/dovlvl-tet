"""Offline CI gates; never launch the GUI or native input diagnostics."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def check_lint():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src", "tests", "tools", "--output-format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    diagnostics = json.loads(result.stdout)
    baseline = json.loads((ROOT / "tools/ruff_baseline.json").read_text(encoding="utf-8"))
    print(f"Ruff diagnostics: {len(diagnostics)} / {baseline['count']}", flush=True)
    if len(diagnostics) > baseline["count"]:
        raise RuntimeError("Ruff diagnostic count increased")


def run_tests():
    tests = ROOT / "tests"
    sys.path.insert(0, str(tests))
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(tests)))
    count = result.testsRun
    failed = [getattr(test, "test_case", test).id() for test, _ in result.failures + result.errors]
    for attempt in range(1, 3):
        if not failed:
            break
        print(f"Retry {attempt}: {', '.join(failed)}", flush=True)
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(failed))
        failed = [getattr(test, "test_case", test).id() for test, _ in result.failures + result.errors]
    print(f"Tests: {count}, remaining failures: {len(failed)}", flush=True)
    return not failed


if __name__ == "__main__":
    check_lint()
    raise SystemExit(0 if run_tests() else 1)
