"""Local app storage namespaces; safe to import without the optional Tk GUI."""
from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
ASSETS = APP_ROOT / "assets"


def _storage_namespace(root: Path) -> str:
    """Preview must never share stable installation settings or API keys."""
    return "TRAMA-Preview" if (root / "assets" / "trama-preview.marker").is_file() else "TRAMA"


PREVIEW_BUNDLE = _storage_namespace(APP_ROOT) == "TRAMA-Preview"
DATA_HOME = (
    Path(os.environ["LOCALAPPDATA"]) / _storage_namespace(APP_ROOT)
    if os.environ.get("LOCALAPPDATA") else
    Path.home() / (".trama-preview" if PREVIEW_BUNDLE else ".trama")
)
OLD_DATA_HOME = (
    Path(os.environ["LOCALAPPDATA"]) / "NEXO"
    if os.environ.get("LOCALAPPDATA") else Path.home() / ".nexo"
)
SETTINGS_FILE = DATA_HOME / "settings.json"
CONFIG_FILE = DATA_HOME / "config.env"
