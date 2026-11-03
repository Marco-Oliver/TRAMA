"""Regressões da base 2.2.0: restauração real, longa e não destrutiva.

Usa somente fixtures artificiais, sem acessar o cofre real do usuário,
GitHub, credenciais ou serviços de IA.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
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
        with closing(sqlite3.connect(db)) as conn:
            conn.execute("CREATE TABLE evidencias (id TEXT PRIMARY KEY, descricao TEXT)")
            conn.execute("INSERT INTO evidencias VALUES (?,?)", ("aula-001", "fonte artificial"))
            conn.commit()
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
        with closing(sqlite3.connect(target / ".base-conhecimento" / "estado.sqlite3")) as conn:
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
        with patch.object(bridge, "_save", side_effect=OSError("disk full")):
            self.assertFalse(bridge.set_ai_processing_consent(True)["ok"])
        self.assertFalse(bridge.settings["ai_processing_consent"])


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



class VerifiedCodeNavigationTests(unittest.TestCase):
    def test_only_provenance_checked_github_line_is_opened(self):
        from unittest.mock import patch
        from knowledge_bridge.bridge import Bridge
        from knowledge_bridge.store import Store

        with tempfile.TemporaryDirectory(prefix="trama-v220-code-links-") as folder:
            vault = Path(folder) / "Obsidian"
            catalog = Store(vault)
            sha = "a" * 40
            repo_url = "https://github.com/unit/example"
            catalog.save_repo(
                repo_url, "example", sha,
                {"evidence": [{"path": "src/sample.cs", "line": 17}],
                 "files": [{"path": "src/sample.cs", "size": 99}]},
                "INDEXED",
            )
            catalog.close()
            bridge = Bridge()
            bridge.settings = {"vault": str(vault)}
            valid = f"{repo_url}/blob/{sha}/src/sample.cs#L17"
            invalid = [
                "javascript:alert(1)",
                f"https://github.com/other/example/blob/{sha}/src/sample.cs#L17",
                f"{repo_url}/blob/{'b' * 40}/src/sample.cs#L17",
                f"{repo_url}/blob/{sha}/src/sample.cs#L18",
                f"{repo_url}/blob/{sha}/src/../secret.cs#L17",
                f"{repo_url}/blob/{sha}/src/%2e%2e/secret.cs#L17",
                f"{repo_url}/blob/{sha}/src/sample.cs?token=secret#L17",
                f"https://github.com@evil.test/unit/example/blob/{sha}/src/sample.cs#L17",
            ]
            with patch("knowledge_bridge.bridge.webbrowser.open",
                       return_value=True) as opener:
                for address in invalid:
                    self.assertFalse(bridge.open_code_link(address)["ok"], address)
                opener.assert_not_called()
                self.assertTrue(bridge.open_code_link(valid)["ok"])
                opener.assert_called_once_with(valid)

    def test_desktop_renders_code_citations_as_safe_controls(self):
        from knowledge_bridge.bridge import load_local_ui
        html = load_local_ui()
        self.assertIn('data-lib-code', html)
        self.assertIn("call('open_code_link'", html)
        self.assertNotIn('window.open(', html)


class TargetedFollowUpKnowledgeTests(unittest.TestCase):
    def test_later_evidence_enriches_only_the_question_from_aula_031(self):
        from knowledge_bridge.pipeline import Application

        with tempfile.TemporaryDirectory(prefix="trama-v220-follow-up-") as folder:
            base = Path(folder)
            app = Application(base / "Obsidian", base / "unused.env", log=lambda _: None)
            try:
                def record(lesson, raw, doubt=""):
                    file = base / f"Aula-{lesson}-V01.txt"
                    file.write_text(raw, encoding="utf-8")
                    self.assertTrue(app.add_file(file))
                    src = next(s for s in app.store.sources("transcript")
                               if s["label"] == file.name)
                    app.store.save_analysis(src["id"], src["digest"], "test", "offline", {
                        "resumo": "Conteúdo fictício de teste.",
                        "tipo_aula": "tecnica",
                        "conceitos": [],
                        "exemplos": [],
                        "duvidas": [doubt] if doubt else [],
                    })
                    return src

                src31 = record("031", "[0:01] Não entendi este assunto ainda.",
                               "Como funciona o HttpClient?")
                app.publisher.rebuild()
                note31 = app.store.vault / "02-Minhas-Aulas" / "Aula-031"
                entry31 = next(n for n in note31.glob("*.md")
                               if n.name != "00-Visao-geral.md")
                first = entry31.read_text(encoding="utf-8")
                self.assertIn("Nenhuma explicação posterior", first)

                record("049", "[0:01] Aula sobre organização do curso.")
                app.publisher.rebuild()
                self.assertEqual(entry31.read_text(encoding="utf-8"), first)

                src50 = record("050", "[0:01] O HttpClient realiza requisições HTTP.")
                app.publisher.rebuild()
                enriched = entry31.read_text(encoding="utf-8")
                self.assertIn("Aula-050", enriched)
                self.assertIn("HttpClient realiza requisições", enriched)
                self.assertIn("não comprovam que a dúvida foi resolvida", enriched)
                self.assertIn("NOVA_EVIDENCIA_PARA_REVISAR", enriched)
                self.assertNotEqual(first, enriched)
                # Never rewrite the original transcript when evidence is found.
                self.assertIn("Não entendi", (
                    app.store.vault / src31["stored_path"]
                ).read_text(encoding="utf-8"))
                self.assertIn("HttpClient", (
                    app.store.vault / src50["stored_path"]
                ).read_text(encoding="utf-8"))
            finally:
                app.close()


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



class ObsidianFullTextSearchTests(unittest.TestCase):
    def test_search_finds_text_inside_notes_and_shows_short_excerpts(self):
        from unittest.mock import patch
        from knowledge_bridge.bridge import Bridge
        with tempfile.TemporaryDirectory(prefix="trama-v220-search-") as folder:
            vault=Path(folder)/"Vault"
            section=vault/"02-Minhas-Aulas"
            section.mkdir(parents=True)
            (section/"Aula-031.md").write_text(
                "# Aula 031\n\nExemplo de Angular com HttpClient usado nas requisições.",
                encoding="utf-8"
            )
            (section/"Aula-050.md").write_text(
                "# Aula 050\n\nNenhuma relação com o conceito pesquisado.",
                encoding="utf-8"
            )
            bridge=Bridge()
            bridge.settings={"vault":str(vault)}
            with patch("knowledge_bridge.bridge.webbrowser.open",
                       side_effect=AssertionError("Search must not open URLs")):
                matches=bridge.search_notes("HttpClient")
            self.assertTrue(matches["ok"])
            self.assertEqual(matches["total"],1)
            self.assertEqual(len(matches["matches"]),1)
            self.assertEqual(matches["matches"][0]["id"],
                             "02-Minhas-Aulas/Aula-031.md")
            self.assertIn("HttpClient",matches["matches"][0]["snippet"])
            self.assertNotIn("Aula 050",str(matches))
            self.assertTrue(matches["matches"][0]["in_content"])
            self.assertFalse(bridge.search_notes("../bad\nname")["ok"])
            self.assertFalse(bridge.search_notes("x"*121)["ok"])
            self.assertFalse(bridge.search_notes("HttpClient",101)["ok"])

    def test_search_never_follows_symlinks_outside_vault(self):
        from knowledge_bridge.bridge import Bridge
        with tempfile.TemporaryDirectory(prefix="trama-v220-search-symlink-") as folder:
            base=Path(folder)
            vault=base/"Obsidian"
            vault.mkdir()
            outside=base/"PRIVATE.md"
            outside.write_text("SENHA_SUPER_SECRETA_PARA_TESTE",encoding="utf-8")
            try:
                (vault/"link.md").symlink_to(outside)
            except (OSError,NotImplementedError):
                self.skipTest("Symlinks not available for this account")
            bridge=Bridge()
            bridge.settings={"vault":str(vault)}
            found=bridge.search_notes("SENHA_SUPER_SECRETA_PARA_TESTE")
            self.assertEqual(found["total"],0)


class LargeLocalLibraryTests(unittest.TestCase):
    def test_150_lessons_enter_six_at_a_time_without_losing_structure(self):
        """Simulate the user's gradual import rhythm without an external API."""
        from knowledge_bridge.pipeline import Application

        with tempfile.TemporaryDirectory(prefix="trama-v220-150-lessons-") as folder:
            base = Path(folder)
            app = Application(base / "cofre", base / "no-key.env", log=lambda _: None)
            try:
                for number in range(1, 151):
                    name = f"Aula-{number:03d}-V01.txt"
                    source = base / name
                    source.write_text(
                        f"[0:01] Material fictício referente à aula {number}.",
                        encoding="utf-8",
                    )
                    self.assertTrue(app.add_file(source))
                    if number % 6 == 0:
                        app.publisher.rebuild()
                sources = app.store.sources("transcript")
                self.assertEqual(len(sources), 150)
                lessons = app.store.vault / "02-Minhas-Aulas"
                self.assertTrue((lessons / "Aula-001" / "00-Visao-geral.md").is_file())
                self.assertTrue((lessons / "Aula-150" / "00-Visao-geral.md").is_file())
                self.assertEqual(
                    sum(p.is_dir() and p.name.startswith("Aula-") for p in lessons.iterdir()),
                    150,
                )
                self.assertEqual(
                    len(list(app.store.vault.rglob("*.PROPOSTA*.md"))), 0
                )
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
