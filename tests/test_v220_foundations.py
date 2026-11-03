"""Regressões da base 2.2.0: restauração real, longa e não destrutiva.

Usa somente fixtures artificiais, sem acessar o cofre real do usuário,
GitHub, credenciais ou serviços de IA.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from knowledge_bridge.recovery import (
    MANIFEST, _filesystem_path, create_backup, restore_backup,
)


class RestoreBackupFoundationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trama-220-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "original"
        db = self.vault / ".base-conhecimento" / "estado.sqlite3"
        db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE evidencias (id TEXT PRIMARY KEY, descricao TEXT)")
            conn.execute("INSERT INTO evidencias VALUES (?,?)", ("aula-001", "fonte artificial"))
        # Several valid path components, together longer than classic MAX_PATH.
        self.relative = (
            ".base-conhecimento/repos/" +
            "projeto-" + "a" * 80 + "/" +
            "subpasta-" + "b" * 80 + "/" +
            "arquivos-" + "c" * 80 + ".txt"
        )
        self.original_file = _filesystem_path(self.vault / self.relative)
        self.original_file.parent.mkdir(parents=True, exist_ok=True)
        self.original_file.write_text("Apenas texto fictício da Aula 001.", encoding="utf-8")
        self.backup = self.root / "copia.zip"

    def test_restores_long_github_paths_without_touching_original(self):
        report = create_backup(self.vault, self.backup)
        self.assertTrue(report["ok"])
        self.assertGreater(len(str(self.root / "restored" / self.relative)), 260)
        self.assertGreaterEqual(report["files"], 2)
        target = self.root / "restored"
        restored = restore_backup(self.backup, target)
        self.assertTrue(restored["ok"])
        self.assertEqual(
            _filesystem_path(target / self.relative).read_text(encoding="utf-8"),
            "Apenas texto fictício da Aula 001.",
        )
        self.assertEqual(
            self.original_file.read_text(encoding="utf-8"),
            "Apenas texto fictício da Aula 001.",
        )
        with sqlite3.connect(target / ".base-conhecimento" / "estado.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM evidencias").fetchone()[0], 1)

    def test_restore_never_overwrites_an_existing_vault(self):
        create_backup(self.vault, self.backup)
        with self.assertRaises(ValueError):
            restore_backup(self.backup, self.vault)
        self.assertTrue(self.original_file.is_file())

    def test_rejects_path_traversal_before_publishing(self):
        malicious = self.root / "malicioso.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../escape.txt", "bad")
            archive.writestr(MANIFEST, json.dumps({
                "format": 1,
                "files": {
                    "../escape.txt": {"sha256": "0" * 64, "size": 3},
                    ".base-conhecimento/estado.sqlite3": {"sha256": "0" * 64, "size": 0},
                },
            }))
            archive.writestr(".base-conhecimento/estado.sqlite3", "")
        target = self.root / "malicious-restore"
        with self.assertRaises(ValueError):
            restore_backup(malicious, target)
        self.assertFalse(target.exists())
        self.assertFalse((self.root / "escape.txt").exists())

class DesktopExperienceFoundationsTests(unittest.TestCase):
    def test_github_import_and_confirmations_are_embedded_in_trama(self):
        from knowledge_bridge.bridge import load_local_ui
        html = load_local_ui()
        self.assertIn('id="repo-dialog"', html)
        self.assertIn('id="trama-confirm-dialog"', html)
        self.assertIn('function askTramaConfirm', html)
        self.assertNotIn("const url=prompt(", html)
        self.assertNotIn("if(!confirm(", html)
        self.assertIn("Cole uma captura de tela ou imagem diretamente aqui.", html)
        self.assertNotIn("Não precisa abrir o Paint.", html)

    def test_consent_is_persistent_in_settings_and_can_be_revoked(self):
        from unittest.mock import patch
        from knowledge_bridge.bridge import Bridge
        bridge = Bridge()
        bridge.settings = {"vault": "", "ai_processing_consent": False}
        with patch.object(bridge, "_save") as save:
            self.assertTrue(bridge.set_ai_processing_consent(True)["ok"])
            self.assertTrue(bridge.ai_status()["processing_consent"])
            self.assertTrue(bridge.set_ai_processing_consent(False)["ok"])
            self.assertFalse(bridge.ai_status()["processing_consent"])
            self.assertEqual(save.call_count, 2)
        self.assertFalse(bridge.set_ai_processing_consent("true")["ok"])

    def test_git_process_does_not_spawn_console_on_windows(self):
        import subprocess
        from unittest.mock import patch
        from knowledge_bridge.pipeline import Application
        with patch("knowledge_bridge.pipeline.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "git version test"
            self.assertIn("git version test", Application._git(["--version"]))
            self.assertEqual(
                run.call_args.kwargs.get("creationflags"),
                getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )



class IncrementalAutomationFoundationsTests(unittest.TestCase):
    def test_new_lessons_reuse_old_analyses_and_single_part_summary_has_no_prefix(self):
        from knowledge_bridge.ai import AIResult
        from knowledge_bridge.pipeline import Application

        class FakeFreeAI:
            def __init__(self):
                self.calls = 0

            def analyze(self, text, context):
                self.calls += 1
                return AIResult({
                    "resumo": "O professor demonstrou um exemplo de programação.",
                    "tipo_aula": "tecnica",
                    "conceitos": [{
                        "nome": "Console.WriteLine",
                        "explicacao": "Escreve texto no console segundo o exemplo.",
                        "tempo": "0:01",
                    }],
                    "pessoas": [],
                    "atividades": [],
                    "ferramentas": [],
                    "marcos": [],
                    "exemplos": [],
                    "duvidas": [],
                    "nomes_a_conferir": [],
                }, "gemini", "offline-test")

        with tempfile.TemporaryDirectory(prefix="trama-v220-incremental-") as folder:
            root = Path(folder)
            app = Application(root / "obsidian", root / "no-key.env", log=lambda _: None)
            try:
                ai = FakeFreeAI()
                app.ai = ai
                original = root / "Aula-001-V01.txt"
                original.write_text(
                    "[0:01] O professor demonstrou Console.WriteLine em C#.",
                    encoding="utf-8",
                )
                self.assertTrue(app.add_file(original))
                app.process()
                self.assertEqual(ai.calls, 1)
                notes = list((app.store.vault / "02-Minhas-Aulas" / "Aula-001").glob("*.md"))
                transcript_notes = [p for p in notes if p.name != "00-Visao-geral.md"]
                self.assertTrue(transcript_notes)
                self.assertIn("O professor demonstrou", transcript_notes[0].read_text(encoding="utf-8"))
                self.assertNotIn("**Parte 1:**", transcript_notes[0].read_text(encoding="utf-8"))

                # A second run has nothing new and must spend no AI calls.
                app.process()
                self.assertEqual(ai.calls, 1)

                newer = root / "Aula-002-V01.txt"
                newer.write_text("[0:01] Um novo exemplo foi ensinado.", encoding="utf-8")
                self.assertTrue(app.add_file(newer))
                app.process()
                self.assertEqual(ai.calls, 2)
                self.assertTrue((app.store.vault / "02-Minhas-Aulas" / "Aula-001").is_dir())
                self.assertTrue((app.store.vault / "02-Minhas-Aulas" / "Aula-002").is_dir())
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
