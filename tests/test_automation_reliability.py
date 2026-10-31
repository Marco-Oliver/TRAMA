"""Realistic, offline integration and adversarial scenarios for TRAMA reliability."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from knowledge_bridge.pipeline import Application
from knowledge_bridge.recovery import create_backup, restore_backup
from knowledge_bridge.ai import AIResult, BudgetStopped


class ReliableAutomation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.vault = self.base / "Obsidian"
        self.config = self.base / "config.env"
        self.config.write_text("FREE_TIER_CONFIRMED=NO\n", encoding="utf-8")
        self.app = Application(self.vault, self.config, log=lambda *_: None)

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def add_lesson(self, lesson, content):
        filename = self.base / f"Aula-{lesson:03d}-V01.txt"
        filename.write_text(content, encoding="utf-8")
        self.app.add_file(filename)
        return next(s for s in self.app.store.sources("transcript")
                    if s["label"] == filename.name)

    def analyze(self, source, *, questions=(), concepts=()):
        self.app.store.save_analysis(source["id"], source["digest"], "fake", "offline",
                                     {"resumo": "Revisão da aula com fontes.",
                                      "tipo_aula": "tecnica", "duvidas": list(questions),
                                      "conceitos": list(concepts), "exemplos": []})

    def test_doubt_is_revisited_by_later_source_and_history_is_idempotent(self):
        old = self.add_lesson(35, "[0:03] Hoje ouvimos exustrix no RXJS.")
        self.analyze(old, questions=["Será que exustrix é o nome correto?"])
        self.app.publisher.rebuild()
        rows = self.app.store.uncertainties()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "HIPOTESE_SEM_CONFIRMACAO")
        self.assertEqual(rows[0]["candidate"], "exhaustMap")
        self.assertEqual(len(self.app.store.uncertainty_events(rows[0]["id"])), 1)
        later = self.add_lesson(37, "[0:21] O operador exhaustMap ignora novas solicitações concorrentes.")
        self.analyze(later, concepts=[{"nome": "exhaustMap", "explicacao": "Explicação literal", "tempo": "0:21"}])
        self.app.publisher.rebuild()
        updated = self.app.store.uncertainties()[0]
        self.assertEqual(updated["status"], "NOVA_EVIDENCIA_PARA_REVISAR")
        evidence = json.loads(updated["evidence_json"])
        self.assertEqual(evidence[0]["lesson"], "Aula-037")
        self.assertEqual(evidence[0]["timestamp"], "0:21")
        page = (self.vault / "01-Meu-Conhecimento/Duvidas" / (updated["id"] + ".md")).read_text(encoding="utf-8")
        self.assertIn("Aula-037", page)
        self.assertIn("não são confirmação", page)
        self.assertIn("Dúvidas", (self.vault / "00-Inicio/Dashboard.md").read_text(encoding="utf-8"))
        history_len = len(self.app.store.uncertainty_events(updated["id"]))
        self.app.publisher.rebuild()
        self.assertEqual(len(self.app.store.uncertainty_events(updated["id"])), history_len)

    def test_wrong_newer_spelling_does_not_fake_correction(self):
        old = self.add_lesson(35, "[0:01] O nome parece ser exustrix.")
        self.analyze(old, questions=["exustrix está correto?"])
        later = self.add_lesson(40, "[0:10] O exustrix apareceu de novo.")
        self.analyze(later)
        self.app.publisher.rebuild()
        self.assertEqual(self.app.store.uncertainties()[0]["status"], "HIPOTESE_SEM_CONFIRMACAO")

    def test_outdated_doubt_is_archived_not_deleted(self):
        old = self.add_lesson(35, "[0:03] exustrix")
        self.analyze(old, questions=["exustrix está correto?"])
        self.app.publisher.rebuild()
        uid = self.app.store.uncertainties()[0]["id"]
        self.analyze(old, questions=[])
        self.app.publisher.rebuild()
        self.assertEqual(self.app.store.uncertainties()[0]["status"], "ARQUIVADA_FONTE_ALTERADA")
        self.assertEqual(len(self.app.store.uncertainty_events(uid)), 2)

    def test_corrupted_transcript_is_never_sent_to_ai(self):
        source = self.add_lesson(35, "[0:03] Conteúdo íntegro sobre RXJS.")
        file = self.vault / source["stored_path"]
        file.write_text("[0:03] CONTEÚDO CORROMPIDO", encoding="utf-8")
        self.app.ai.analyze = lambda *args: self.fail("Corrupted content sent to AI!")
        with self.assertRaisesRegex(ValueError, "corrompida"):
            self.app.process()
        self.assertEqual(self.app.store.get_source(source["id"])["status"], "NEEDS_REVIEW")
        self.assertEqual(file.read_text(encoding="utf-8"), "[0:03] CONTEÚDO CORROMPIDO")

    def test_batch_interruption_resumes_cached_chunks(self):
        lesson = ("[0:01] O professor falou de console.\n" +
                  "[0:02] Exemplos de console.\n" + "Texto adicional sobre console. " * 550 +
                  "\n[1:20] Mais exemplos de console e explicações.")
        source = self.add_lesson(1, lesson)
        calls = []
        def first(part, ctx):
            calls.append(part)
            if len(calls) > 1:
                raise BudgetStopped("cota encerrada")
            return AIResult({"resumo": "Parte um", "tipo_aula": "tecnica",
                             "conceitos": [], "exemplos": [], "duvidas": []}, "fake", "offline")
        self.app.ai.analyze = first
        self.app.process()
        self.assertEqual(self.app.store.get_source(source["id"])["status"], "WAITING_FOR_PROVIDER")
        again = []
        def second(part, ctx):
            again.append(part)
            return AIResult({"resumo": "Continuou", "tipo_aula": "tecnica",
                             "conceitos": [], "exemplos": [], "duvidas": []}, "fake", "offline")
        self.app.ai.analyze = second
        self.app.process()
        self.assertEqual(self.app.store.get_source(source["id"])["status"], "PUBLISHED")
        self.assertEqual(len(again), len(calls) - 1 if False else
                         self.app.store.conn.execute(
                             "SELECT COUNT(*) FROM chunks WHERE source_id=?",
                             (source["id"],)).fetchone()[0] - 1)
        self.assertIn("Parte um", self.app.store.analysis(source["id"], source["digest"])["resumo"])

    def test_verified_backup_restores_manual_notes_and_sqlite(self):
        src = self.add_lesson(1, "[0:04] Console.WriteLine demonstra saída.")
        self.analyze(src, concepts=[{"nome": "Console", "explicacao": "Imprime texto", "tempo": "0:04"}])
        self.app.publisher.rebuild()
        manual = self.vault / "05-Anotacoes-Pessoais" / "minha-nota.md"
        manual.write_text("# Minha anotação", encoding="utf-8")
        obs = self.vault / ".obsidian" / "app.json"
        obs.parent.mkdir(exist_ok=True)
        obs.write_text('{"vimMode":false}', encoding="utf-8")
        archive = self.base / "backup-do-curso.zip"
        report = create_backup(self.vault, archive)
        self.assertGreater(report["files"], 3)
        with self.assertRaises(FileExistsError):
            create_backup(self.vault, archive)
        restored = self.base / "restored-vault"
        restore_backup(archive, restored)
        self.assertEqual((restored / manual.relative_to(self.vault)).read_bytes(), manual.read_bytes())
        self.assertEqual((restored / obs.relative_to(self.vault)).read_bytes(), obs.read_bytes())
        with self.assertRaises(ValueError):
            restore_backup(archive, restored)
        old = self.app.store.sources("transcript")
        self.app.close()
        self.app = Application(restored, self.config, log=lambda *_: None)
        self.assertEqual(len(self.app.store.sources("transcript")), len(old))
        self.assertEqual(self.app.store.analysis(old[0]["id"], old[0]["digest"])["resumo"],
                         "Revisão da aula com fontes.")

    def test_tampered_zip_is_rejected_without_destination_files(self):
        self.add_lesson(1, "[0:01] Conteúdo.")
        archive = self.base / "original.zip"
        create_backup(self.vault, archive)
        fake = self.base / "invalid.zip"
        with zipfile.ZipFile(archive) as z, zipfile.ZipFile(fake, "w") as w:
            for info in z.infolist():
                value = z.read(info.filename)
                if info.filename.endswith(".txt"):
                    value += b"ALGUEM MUDOU A TRANSCRICAO"
                w.writestr(info.filename, value)
        restored = self.base / "invalid-target"
        with self.assertRaises(ValueError):
            restore_backup(fake, restored)
        self.assertFalse(restored.exists())
        with zipfile.ZipFile(self.base / "zip-slip.zip", "w") as w:
            w.writestr("../outside.txt", "attack")
            w.writestr("TRAMA-BACKUP-MANIFEST.json",
                       '{"format":1,"files":{"../outside.txt":{"sha256":"","size":6}}}')
        with self.assertRaises(ValueError):
            restore_backup(self.base / "zip-slip.zip", self.base / "sneaky")

    def test_large_offline_150_lecture_vault(self):
        # Test real indexing/Markdown publication without faking an AI summary.
        for i in range(1, 151):
            self.add_lesson(i, f"[0:04] Aula {i} explica console e variações.\n"
                               "[0:19] O professor demonstrou console no programa.")
        start = time.monotonic()
        result = self.app.publisher.rebuild()
        took = time.monotonic() - start
        self.assertEqual(result["aulas"], 150)
        dashboard = (self.vault / "00-Inicio/Dashboard.md").read_text(encoding="utf-8")
        self.assertIn("Aula-150", dashboard)
        self.assertEqual(len(list((self.vault / "02-Minhas-Aulas").glob("Aula-*/00-Visao-geral.md"))),150)
        # Track a regression with a generous cross-platform bound, not a benchmark claim.
        self.assertLess(took, 180)


if __name__ == "__main__":
    unittest.main()
