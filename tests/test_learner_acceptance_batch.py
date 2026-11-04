"""Consolidated learner journey. NO real classes, secrets or provider requests.

One run checks what a person would otherwise test repeatedly:
12 lessons in two batches, recording links, AI budget/cache semantics,
reimport, protected hand edits, backup and independent restoration.
This mechanical acceptance gate does NOT rate actual Gemini summaries.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.ai import AIResult
from knowledge_bridge.auto_ingest import AutoOrganizer
from knowledge_bridge.pipeline import Application
from knowledge_bridge.recovery import create_backup, restore_backup


class DeterministicCourseProvider:
    def __init__(self):
        self.attempts = 0

    def active(self):
        return ["gemini"]  # fake capability flag; no network client exists

    def analyze(self, source: str, context: str):
        self.attempts += 1
        return AIResult({
            "resumo": (
                "Na transcrição fictícia, o instrutor introduz SDK como conjunto "
                "de ferramentas para desenvolvimento de software. A explicação "
                "é uma hipótese da análise e deve ser comparada com o texto."
            ),
            "tipo_aula": "tecnica",
            "conceitos": [{"nome": "SDK (Software Development Kit)",
                           "explicacao": "Kit de desenvolvimento mencionado.",
                           "tempo": "0:02"}],
            "pessoas": [], "atividades": [], "ferramentas": [],
            "marcos": [], "exemplos": [], "duvidas": [],
            "nomes_a_conferir": [],
        }, "fixture-offline", "sem-requisicao")

    def compare(self, *_args):
        self.attempts += 1
        return AIResult({"resumo":"Sem relação verificada.", "relacoes":[],
                         "correcoes":[], "novidades":[]},
                        "fixture-offline", "sem-requisicao")


class LearnerAcceptanceBatchTests(unittest.TestCase):
    def test_two_six_lesson_batches_repeat_backup_and_protected_notes(self):
        with tempfile.TemporaryDirectory(prefix="trama-journey-complete-") as tmp:
            base=Path(tmp)
            vault=base/"TRAMA-TESTE"
            originals=base/"materiais-originais"
            originals.mkdir()
            paths=[]
            for n in range(1,13):
                path=originals/f"A{n:02d} - V01 - Aula {n:02d}.txt"
                path.write_text(
                    f"[0:01] Aula {n:02d}: o professor apresenta o SDK.\n"
                    "[0:02] SDK significa Software Development Kit.\n"
                    "[0:05] Serve para criar projetos e reunir ferramentas.\n",
                    encoding="utf-8")
                paths.append(path)
            contents=[path.read_bytes() for path in paths]
            app=Application(vault,base/"sem-segredos.env",log=lambda *_:None)
            fake=DeterministicCourseProvider()
            app.ai=fake
            try:
                organizer=AutoOrganizer(app,log=lambda *_:None)
                links=(
                    "Aula 01 | V01 - Introdução | "
                    "https://drive.google.com/file/d/curso-ficticio-01/view\n"
                    "Aula 02 | V01 - Ferramentas | "
                    "https://drive.google.com/file/d/curso-ficticio-02/view"
                )
                first=organizer.run(paths[:6],links,authorized=True)
                self.assertEqual(first["files"],6,first)
                self.assertTrue(first["processed"])
                self.assertEqual(fake.attempts,6)
                self.assertEqual(len(first["lessons"]),6)
                self.assertEqual(first["errors"],[])
                self.assertEqual(len(app.store.sources("transcript")),6)
                classroom=[row for row in app.store.sources("classroom")
                           if row["lesson"]=="Aula-001"]
                self.assertTrue(classroom)
                record=json.loads((vault/classroom[0]["stored_path"]).read_text(encoding="utf-8"))
                self.assertEqual(len(record.get("videos",[])),1)
                self.assertIn("curso-ficticio-01",record["videos"][0]["url"])
                # Reimporting the same batch must not spend another request
                # or multiply recording notes and original attachments.
                repeat=organizer.run(paths[:6],links,authorized=True)
                self.assertEqual(repeat["files"],0,repeat)
                self.assertEqual(fake.attempts,6)
                self.assertEqual(len(app.store.sources("transcript")),6)

                second=organizer.run(paths[6:],"",authorized=True)
                self.assertEqual(second["files"],6,second)
                self.assertEqual(fake.attempts,12)
                self.assertEqual(len(app.store.sources("transcript")),12)
                self.assertEqual(
                    sum(s["status"]=="PUBLISHED" for s in app.store.sources("transcript")),12
                )
                for number in range(1,13):
                    folder=vault/"02-Minhas-Aulas"/f"Aula-{number:03d}"
                    self.assertTrue((folder/"00-Visao-geral.md").is_file())
                    self.assertEqual(len(list(folder.glob("*.md"))),2)
                for path,content in zip(paths,contents):
                    self.assertEqual(path.read_bytes(),content)

                # A person's changes have priority over republishing.
                first_source=next(s for s in app.store.sources("transcript")
                                  if s["lesson"]=="Aula-001")
                lesson_folder=vault/"02-Minhas-Aulas"/"Aula-001"
                note=next(p for p in lesson_folder.glob("*.md")
                          if p.name!="00-Visao-geral.md")
                personal="# Minhas observações\nTexto pessoal que não pode sumir.\n"
                note.write_text(personal,encoding="utf-8")
                analysis=app.store.analysis(first_source["id"],first_source["digest"])
                analysis["exemplos"]=["Exemplo adicional fictício extraído da fonte."]
                app.store.save_analysis(first_source["id"],first_source["digest"],
                                        "fixture-offline","sem-requisicao",analysis)
                app.publisher.rebuild()
                self.assertEqual(note.read_text(encoding="utf-8"),personal)
                proposals=list(lesson_folder.glob(note.stem+".PROPOSTA*.md"))
                self.assertEqual(len(proposals),1)
                app.publisher.rebuild()
                self.assertEqual(len(list(lesson_folder.glob(note.stem+".PROPOSTA*.md"))),1)
                self.assertEqual(fake.attempts,12)

                # A verified local ZIP can be restored into an isolated vault;
                # the original remains untouched and the catalog stays usable.
                backup=base/"backup-curso.zip"
                created=create_backup(vault,backup)
                self.assertTrue(created["ok"])
                restored=base/"TRAMA-RESTAURADO"
                report=restore_backup(backup,restored)
                self.assertTrue(report["ok"])
                relative=note.relative_to(vault)
                self.assertEqual((restored/relative).read_text(encoding="utf-8"),personal)
                self.assertEqual(note.read_text(encoding="utf-8"),personal)
                reopened=Application(restored,base/"sem-segredos.env",log=lambda *_:None)
                try:
                    self.assertEqual(len(reopened.store.sources("transcript")),12)
                    self.assertEqual(reopened.store.analysis(
                        first_source["id"],first_source["digest"])["exemplos"],
                        ["Exemplo adicional fictício extraído da fonte."])
                finally:
                    reopened.close()
            finally:
                app.close()
