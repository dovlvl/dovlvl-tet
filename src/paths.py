"""Application output and bundled resource locations."""

from pathlib import Path
import sys


def app_root(*, resolve_executable=False):
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        return (executable.resolve() if resolve_executable else executable).parent
    return Path(__file__).resolve().parents[1]


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
