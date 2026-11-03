"""Prepare an isolated, unsigned TRAMA Preview Windows build.

Run ONLY on a clean checkout on a CI runner before PyInstaller/Inno Setup.
The stable installer, application data, release metadata and production branch
are never modified. Changes are made to CI working files and a new .iss.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIEW_LABEL = "TRAMA Preview 2.1 (teste)"
PREVIEW_DATA_FOLDER = "TRAMA-Preview-PR4"


def replace_exact(path: Path, old: str, new: str, *, count: int = 1):
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"Expected {count} matches in {path.name}; found {found}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def prepare():
    gui = ROOT / "knowledge_bridge" / "gui_legacy.py"
    replace_exact(
        gui,
        'DATA_HOME = (Path(os.environ["LOCALAPPDATA"]) / "TRAMA" '
        'if os.environ.get("LOCALAPPDATA") else Path.home() / ".trama")',
        'DATA_HOME = (Path(os.environ["LOCALAPPDATA"]) / "TRAMA-Preview-PR4" '
        'if os.environ.get("LOCALAPPDATA") else Path.home() / ".trama-preview-pr4")',
    )
    replace_exact(
        gui,
        'OLD_DATA_HOME = (Path(os.environ["LOCALAPPDATA"]) / "NEXO" '
        'if os.environ.get("LOCALAPPDATA") else Path.home() / ".nexo")',
        'OLD_DATA_HOME = DATA_HOME  # Preview never migrates/reads stable settings.',
    )
    # The button remains in the UI, but an empty release channel disallows
    # official update downloads from this preview build.
    release_channel = ROOT / "release_channel.json"
    release_channel.write_text(
        json.dumps({"github_repo": ""}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    replace_exact(
        ROOT / "knowledge_bridge" / "ui" / "app.js",
        "TRAMA v2.0.1  │  ",
        PREVIEW_LABEL + "  │  ",
    )
    replace_exact(
        ROOT / "knowledge_bridge" / "ui" / "app.js",
        "Versão instalada: 2.0.1.",
        "Versão experimental: TRAMA Preview 2.1.",
    )
    iss = (ROOT / "TRAMA_Instalador.iss").read_text(encoding="utf-8")
    changes = [
        ('#define MyAppName "TRAMA"', '#define MyAppName "TRAMA Preview"'),
        ('#define MyAppVersion "2.0.1"', '#define MyAppVersion "2.1.0-preview"'),
        ("AppId={{9819EDB4-FC18-4D9E-99F6-8CB6D9914407}",
         "AppId={{7BFC6C0A-8574-48E2-A496-A0B0E030FCAF}"),
        (r"DefaultDirName={localappdata}\Programs\TRAMA",
         r"DefaultDirName={localappdata}\Programs\TRAMA Preview"),
        ("DefaultGroupName=TRAMA", "DefaultGroupName=TRAMA Preview"),
        ("OutputBaseFilename=TRAMA_Setup", "OutputBaseFilename=TRAMA_Preview_Setup"),
        (r'Name: "{autoprograms}\TRAMA";', r'Name: "{autoprograms}\TRAMA Preview";'),
        (r'Name: "{autodesktop}\TRAMA";', r'Name: "{autodesktop}\TRAMA Preview";'),
    ]
    for old, new in changes:
        if iss.count(old) != 1:
            raise RuntimeError(f"Preview installer replacement missing or ambiguous: {old}")
        iss = iss.replace(old, new)
    if "TRAMA_Instalador.iss" in iss:
        raise RuntimeError("Preview script accidentally references stable setup")
    (ROOT / "TRAMA_Preview_Instalador.iss").write_text(iss, encoding="utf-8")
    assert "TRAMA-Preview-PR4" in gui.read_text(encoding="utf-8")
    assert "TRAMA Preview" in iss and "7BFC6C0A" in iss
    assert json.loads(release_channel.read_text(encoding="utf-8")) == {"github_repo": ""}
    print("PASS: isolated app data, app ID, folder, shortcuts, release channel and preview label")


if __name__ == "__main__":
    prepare()
