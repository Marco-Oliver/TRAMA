"""Prepare an isolated, unsigned TRAMA Preview Windows build.

Run ONLY on a clean checkout on a CI runner before PyInstaller/Inno Setup.
The stable installer, application data, release metadata and production branch
are never modified. Changes are made to CI working files and a new .iss.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIEW_BUILD = int(os.environ.get("TRAMA_PREVIEW_BUILD", "1"))
if not 1 <= PREVIEW_BUILD <= 99_999_999:
    raise ValueError("Número de build Preview inválido.")
PREVIEW_VERSION = f"2.2.0-preview.{PREVIEW_BUILD}"
PREVIEW_LABEL = f"TRAMA v{PREVIEW_VERSION} — Preview de teste"
PREVIEW_DATA_FOLDER = "TRAMA-Preview"


def replace_exact(path: Path, old: str, new: str, *, count: int = 1):
    text = path.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"Expected {count} matches in {path.name}; found {found}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def prepare():
    gui = ROOT / "knowledge_bridge" / "gui_legacy.py"
    # Bundled marker selects LocalAppData/TRAMA-Preview. The normal checkout
    # and stable installer keep using LocalAppData/TRAMA unchanged.
    marker = ROOT / "assets" / "trama-preview.marker"
    marker.write_text("TRAMA_PREVIEW_ISOLATED_V1" + chr(10), encoding="utf-8")
    if "_storage_namespace(APP_ROOT)" not in gui.read_text(encoding="utf-8"):
        raise RuntimeError("QA source no longer supports isolated preview storage")
    replace_exact(
        gui,
        'OLD_DATA_HOME = (Path(os.environ["LOCALAPPDATA"]) / "NEXO" '
        'if os.environ.get("LOCALAPPDATA") else Path.home() / ".nexo")',
        'OLD_DATA_HOME = DATA_HOME  # Preview never migrates/reads stable settings.',
    )
    # Preview checks ONLY explicitly published GitHub prereleases. This
    # build step never publishes one and cannot touch the stable channel.
    release_channel = ROOT / "release_channel.json"
    release_channel.write_text(
        json.dumps({"github_repo": "Marco-Oliver/TRAMA",
                    "channel": "preview", "version": PREVIEW_VERSION},
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    replace_exact(
        ROOT / "knowledge_bridge" / "ui" / "app.js",
        "TRAMA v2.1.0  │  ",
        PREVIEW_LABEL + "  │  ",
    )
    replace_exact(
        ROOT / "knowledge_bridge" / "ui" / "app.js",
        "Versão instalada: 2.1.0.",
        f"Versão experimental: TRAMA Preview v{PREVIEW_VERSION}. "
        "Verifique atualizações aqui sem baixar ZIP; a instalação exige sua confirmação.",
    )
    replace_exact(
        ROOT / "knowledge_bridge" / "ui" / "app.js",
        "Atualizações do TRAMA</h3>",
        "Atualizações do TRAMA Preview</h3>",
    )
    iss = (ROOT / "TRAMA_Instalador.iss").read_text(encoding="utf-8")
    changes = [
        ('#define MyAppName "TRAMA"', '#define MyAppName "TRAMA Preview"'),
        ('#define MyAppVersion "2.1.0"', f'#define MyAppVersion "{PREVIEW_VERSION}"'),
        ("AppId={{9819EDB4-FC18-4D9E-99F6-8CB6D9914407}",
         "AppId={{ACF2B65E-BC0C-4FF9-9A47-05323162EB96}"),
        (r"DefaultDirName={localappdata}\Programs\TRAMA",
         r"DefaultDirName={localappdata}\Programs\TRAMA Preview"),
        ("DefaultGroupName=TRAMA", "DefaultGroupName=TRAMA Preview"),
        ("UsePreviousAppDir=yes", "UsePreviousAppDir=no"),
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
    assert marker.is_file() and "_storage_namespace" in gui.read_text(encoding="utf-8")
    assert "TRAMA Preview" in iss and "ACF2B65E" in iss and "UsePreviousAppDir=no" in iss
    assert json.loads(release_channel.read_text(encoding="utf-8")) == {
        "github_repo": "Marco-Oliver/TRAMA",
        "channel": "preview", "version": PREVIEW_VERSION}
    print(f"PASS: isolated {PREVIEW_VERSION} data, AppId, install folder, preview updates and label")


if __name__ == "__main__":
    prepare()
