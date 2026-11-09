"""HosMonitor server package."""

from pathlib import Path

from .config import application_dir


def current_version() -> str:
    path = application_dir() / "VERSION"
    try:
        value = path.read_text(encoding="utf-8").strip()
        parts = value.split(".")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            return value
    except OSError:
        pass
    return "0.1.0"


__version__ = current_version()
