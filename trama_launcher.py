"""TRAMA desktop entry point for the packaged Windows app.

The bundled installer launches this file without a console. Startup failures
are reported as a small native dialog and a local error report, instead of
flooding the user's terminal with a traceback.
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path


def _report_error(error: BaseException) -> None:
    try:
        from knowledge_bridge.gui_legacy import DATA_HOME
        log_dir = DATA_HOME / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "inicializacao.log"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] "
                         f"{type(error).__name__}: {error}\n")
            stream.write("".join(traceback.format_exception(error))[-12000:])
            stream.write("\n")
    except Exception:
        path = Path.home() / "inicializacao-trama.log"
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "O TRAMA não conseguiu abrir. Nenhuma nota foi apagada.\n\n"
                f"Relatório de erro: {path}\n\n"
                f"Tipo de falha: {type(error).__name__}",
                "TRAMA — Falha na inicialização", 0x10,
            )
        except Exception:
            pass
    else:
        print(f"TRAMA: {type(error).__name__}: {error}", file=sys.stderr)


def smoke_test() -> None:
    """Offline packaging check; does not open GUI, read user vault or call AI."""
    from knowledge_bridge.bridge import Bridge, PublicApi, load_local_ui
    html = load_local_ui()
    assert "Biblioteca do Obsidian" in html
    api = PublicApi(Bridge())
    assert isinstance(api.snapshot(), dict)
    assert not hasattr(api, "window")
    from knowledge_bridge.gui_legacy import APP_ROOT, DATA_HOME, PREVIEW_BUNDLE
    preview_marker=(APP_ROOT / "assets" / "trama-preview.marker").is_file()
    assert PREVIEW_BUNDLE == preview_marker
    if preview_marker:
        assert DATA_HOME.name == "TRAMA-Preview", (
            "QA preview must not read stable TRAMA app data or keys")
    if sys.platform == "win32":
        import webview  # verifies the frozen Windows GUI dependency is present
        assert callable(webview.create_window)


def main() -> int:
    try:
        if "--self-test" in sys.argv:
            smoke_test()
            return 0
        from knowledge_bridge.bridge import start_webview
        start_webview()
        return 0
    except Exception as error:
        _report_error(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
