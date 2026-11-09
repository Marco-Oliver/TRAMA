# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a self-contained Windows desktop TRAMA folder."""
from pathlib import Path

root = Path(SPECPATH)
assets = root / 'assets'
code = root / 'knowledge_bridge'

analysis = Analysis(
    [str(root / 'trama_launcher.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(assets), 'assets'),
        (str(root / 'release_channel.json'), '.'),
        (str(code / 'ui'), 'knowledge_bridge/ui'),
    ],
    hiddenimports=['clr', 'webview.platforms.edgechromium', 'knowledge_bridge.auto_ingest', 'knowledge_bridge.study_notes',
                   'knowledge_bridge.activities', 'knowledge_bridge.projects'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name='TRAMA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    icon=str(assets / 'trama.ico'),
    uac_admin=False,
)
coll = COLLECT(exe, analysis.binaries, analysis.datas,
               strip=False, upx=False, name='TRAMA')
