"""Aula 02 local fidelity regressions. Fake data, no external AI or network."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from knowledge_bridge.academy_material import AcademyDocs, DOCS_REPO, extract_material
from knowledge_bridge.auto_ingest import AutoOrganizer
from knowledge_bridge.classroom_paste import parse_import_paste
from knowledge_bridge.pipeline import Application


DOC_URL = "https://academiadoprogramador-fullstack.github.io/docs/conteudo/exemplo-aula-dois/"
DOC_PATH = "docs/02 - Conteúdo/02 - Exemplos da Aula 02.md"
SHA = "a" * 40
DOC_MD = (
    "---\nslug: /conteudo/exemplo-aula-dois\n"
    "tags:\n  - conceito-dotnet\n---\n"
    "# Comandos para a aula\n"
    "Explicação do dotnet --version em prosa, sem evidência executável.\n"
    "\x60\x60\x60shell\n"
    "dotnet --info\n"
    "\x60\x60\x60\n"
    "\x60\x60\x60csharp\n"
    'Console.WriteLine("Oi");\n'
    "\x60\x60\x60\n"
)


class NoAI:
    attempts = 0
    def active(self): return []
    def analyze(self, *_args, **_kwargs):
        raise AssertionError("No AI request is allowed in local rebuild")


class FakeReader:
    def __init__(self):
        self._privacy = {}
        self.reads = []
    def read_file(self, repo, sha, path):
        assert (repo, sha, path) == (DOCS_REPO, SHA, DOC_PATH)
        self.reads.append((sha, path))
        return {"content": DOC_MD, "size": len(DOC_MD.encode("utf-8"))}


class Aula02FidelityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = Application(self.root / "vault",
                               config=self.root / "missing-free-keys.env",
                               log=lambda _:None)
        self.addCleanup(self.app.close)
        self.app.ai = NoAI()

    def add_lesson(self, number: int, raw: str, *, people=None,
                   names=None, concepts=None, examples=None):
        path = self.root / f"A{number:02d} - V01 - Instalação.txt"
        path.write_text(raw, encoding="utf-8")
        self.app.add_file(path)
        source = next(s for s in self.app.store.sources("transcript")
                      if s["lesson"] == f"Aula-{number:03d}")
        self.app.store.save_analysis(
            source["id"], source["digest"], "offline", "reused-model-output", {
                "resumo": "Síntese previamente armazenada.",
                "tipo_aula": "tecnica",
                "pessoas": people or [],
                "nomes_a_conferir": names or [],
                "conceitos": concepts or [],
                "exemplos_reconstruidos_a_conferir": examples or [],
                "duvidas": [], "atividades": [], "ferramentas": [], "marcos": [],
            })
        return source

    def post(self, *, author="Tiago Santini de Athayde",
             description="Conteúdo:\nInstalação do .NET SDK"):
        return {"aula": "Aula-002", "titulo": "Instalação do ambiente",
                "autor": author, "data": "03/03/2026",
                "pessoas": (author+" — autor do post do Classroom (não prova apresentação)" if author else ""),
                "descricao": description, "atividades": "",
                "gravacoes": [], "_pasted_classroom": True}

    def note02(self) -> str:
        folder = self.app.store.vault / "02-Minhas-Aulas" / "Aula-002"
        notes = [p for p in folder.glob("*.md")
                 if not p.name.startswith("00-")]
        self.assertTrue(notes)
        return notes[0].read_text(encoding="utf-8")

    def test_post_author_particles_and_same_post_parser_upgrade_archived(self):
        pasted = ("Aula 02 - Instalação do ambiente\n"
                  "Tiago Santini de Athayde\n"
                  "Agenda: 03/03/2026\nConteúdo:\nInstalação do .NET SDK\n")
        parsed = parse_import_paste(pasted)
        self.assertEqual(parsed["posts"][0]["autor"], "Tiago Santini de Athayde")
        organizer = AutoOrganizer(self.app, log=lambda _:None)
        source = {"id": "reused-post-id", "stored_path": "(post do Classroom colado)"}
        old = self.post(author="")
        new = self.post()
        self.assertTrue(organizer._save_extracted(
            source, "Aula-002", old, reason="Post copiado do Classroom"))
        self.assertTrue(organizer._save_extracted(
            source, "Aula-002", new, reason="Post copiado do Classroom"))
        saved = self.app.store.get_source("autoctx-reused-post-id")
        payload = json.loads((self.app.store.vault / saved["stored_path"]).read_text(
            encoding="utf-8"))
        self.assertEqual(payload["autor"], "Tiago Santini de Athayde")
        folder = self.app.store.vault / "99-Anexos" / "Contexto-Classroom" / "Historico"
        versions = list(folder.glob("Aula-002-auto-reused-post-id-*.json"))
        self.assertEqual(len(versions), 1)
        self.assertEqual(json.loads(versions[0].read_text(encoding="utf-8"))["autor"], "")
        self.assertFalse(organizer._save_extracted(
            source, "Aula-002", self.post(description="Conteúdo alterado"),
            reason="Post copiado do Classroom"))
        self.assertEqual(self.app.ai.attempts, 0)

    def test_canonical_teacher_aliases_and_person_pages_threshold(self):
        organizer=AutoOrganizer(self.app,log=lambda _:None)
        source={"id":"teacher-post","stored_path":"(post do Classroom colado)"}
        self.assertTrue(organizer._save_extracted(
            source,"Aula-002",self.post(),reason="Post copiado do Classroom"))
        people=[{"nome":"Thiago Santini", "papel":"professor"},
                {"nome":"João Silva","papel":"participante"},
                {"nome":"Dulu","papel":"aluno"}]
        self.add_lesson(2,
            "00:01 Thiago Santini e João Silva falaram.\n"
            "00:02 Ô Thagão. O Rash e o Hash. Dulu e Dudu participam.\n",
            people=people, names=["Thagão","Rash","Hash","Dulu","Dudu"])
        self.add_lesson(3, "00:01 João Silva participa.\n",
                        people=[{"nome":"João Silva"}])
        self.add_lesson(4, "00:01 João Silva volta.\n",
                        people=[{"nome":"João Silva"}])
        # An existing full-name note may act as an identity *hint*, not proof.
        people_dir=self.app.store.vault/"01-Meu-Conhecimento"/"Pessoas"
        people_dir.mkdir(parents=True,exist_ok=True)
        (people_dir/"alexandre-rech.md").write_text(
            "# Alexandre Rech\n\nNota humana preservada.\n",encoding="utf-8")
        self.app.publisher.rebuild()
        note=self.note02()
        self.assertIn("Thagão (possivelmente Tiago Santini de Athayde)",note)
        self.assertIn("Rash (possivelmente Alexandre Rech)",note)
        self.assertIn("Hash (possivelmente Alexandre Rech)",note)
        self.assertIn("Dulu (possivelmente Dudu)",note)
        self.assertTrue((people_dir/"tiago-santini-de-athayde.md").exists())
        self.assertTrue((people_dir/"joao-silva.md").exists())
        self.assertFalse((people_dir/"dulu.md").exists())
        self.assertFalse((people_dir/"dudu.md").exists())
        self.assertFalse((people_dir/"thagao.md").exists())
        self.assertIn("Nota humana preservada",
                      (people_dir/"alexandre-rech.md").read_text(encoding="utf-8"))
        self.assertEqual(self.app.ai.attempts,0)

    def test_same_lesson_concepts_grouped_without_losing_aliases(self):
        src=self.add_lesson(2,
            "00:01 Extensão C# Dev Kit, C# Dev Kit, Extensão .cs e Arquivo .cs.\n",
            concepts=[{"nome":"Extensão C# Dev Kit","explicacao":"Extensão para C#."},
                      {"nome":"C# Dev Kit","explicacao":"Kit de desenvolvimento."},
                      {"nome":"Extensão .cs","explicacao":"Extensão do arquivo."},
                      {"nome":"Arquivo .cs","explicacao":"Arquivo de C#."}])
        before=self.app.store.analysis(src["id"],src["digest"])
        digest=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
        self.app.publisher.rebuild()
        note=self.note02()
        self.assertEqual(note.count("- **C# Dev Kit**"),1)
        self.assertEqual(note.count("- **.cs**"),1)
        self.assertIn("Extensão C# Dev Kit",note)
        self.assertIn("Arquivo .cs",note)
        self.assertNotIn("- **Extensão C# Dev Kit**",note)
        after=self.app.store.analysis(src["id"],src["digest"])
        self.assertEqual(hashlib.sha256(
            json.dumps(after,sort_keys=True).encode()).hexdigest(),digest)
        self.assertEqual(self.app.ai.attempts,0)

    def test_legacy_frozen_doc_fences_reclassify_only_literal_examples(self):
        src=self.add_lesson(2,
            "00:01 O professor explicou instalação, mas sem digitar comandos.\n",
            examples=["dotnet --info", 'Console.WriteLine("Oi");',
                      "dotnet --version"])
        parsed=extract_material(DOC_MD,DOC_PATH)
        self.assertTrue(any(x["origin"]=="bloco_codigo" for x in parsed["terms"]))
        self.app.store.freeze_academy_docs("Aula-002",SHA)
        old_terms=[x for x in parsed["terms"] if x["origin"] not in (
            "bloco_codigo","codigo_fence_auditado")]
        self.app.store.register_academy_doc(
            "Aula-002",DOC_URL,SHA,DOC_PATH,parsed["title"],parsed["tags"],
            old_terms,parsed["concepts"])
        reader=FakeReader()
        with patch("knowledge_bridge.academy_material.AcademyDocs",
                   side_effect=lambda store: AcademyDocs(store,reader=reader)):
            self.app.publisher.rebuild()
        note=self.note02()
        self.assertIn("## Exemplos do material oficial",note)
        self.assertIn("dotnet --info",note)
        self.assertIn('Console.WriteLine("Oi");',note)
        self.assertIn("## Exemplos reconstruídos pela IA, conferir",note)
        self.assertIn("dotnet --version",note)
        self.assertIn("/blob/"+SHA+"/",note)
        self.assertEqual(self.app.store.academy_docs_sha("Aula-002"),SHA)
        self.assertEqual(len(reader.reads),1)
        self.app.publisher.rebuild()
        self.assertEqual(len(reader.reads),1)
        self.assertEqual(self.app.ai.attempts,0)

    def test_legacy_automatic_people_archived_but_manual_edit_kept(self):
        src=self.add_lesson(2,"00:01 Dudu e João Silva participam.\n",
            people=[{"nome":"Dudu"},{"nome":"João Silva"}])
        folder=self.app.store.vault/"01-Meu-Conhecimento"/"Pessoas"
        folder.mkdir(parents=True,exist_ok=True)
        relative="01-Meu-Conhecimento/Pessoas/dudu.md"
        old_content="---\ntipo: 'pessoa'\n---\n# Dudu\n"
        self.app.publisher.write(relative,old_content)
        manual=folder/"joao-silva.md"
        self.app.publisher.write("01-Meu-Conhecimento/Pessoas/joao-silva.md",
                                 "---\ntipo: 'pessoa'\n---\n# João Silva\n")
        manual.write_text(manual.read_text(encoding="utf-8")+
                          "\nMinha anotação humana.\n",encoding="utf-8")
        self.app.publisher.rebuild()
        self.assertFalse((folder/"dudu.md").exists())
        self.assertEqual(len(list(
            (self.app.store.vault/"90-Sistema"/"Pessoas-Arquivadas").glob(
                "dudu-*.md"))),1)
        self.assertIn("Minha anotação humana.",manual.read_text(encoding="utf-8"))
        self.assertEqual(self.app.ai.attempts,0)


if __name__=="__main__":
    unittest.main()
