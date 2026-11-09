"""Canonical links and teacher-name regression: fake vault, no AI/network."""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from knowledge_bridge.auto_ingest import AutoOrganizer
from knowledge_bridge.pipeline import Application


class ForbiddenAI:
    attempts=0
    def active(self): return []
    def analyze(self,*_args,**_kwargs):
        raise AssertionError("A rebuild must never call AI")


class Aula02CanonicalReferencesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.vault=self.root/"vault"
        self.app=Application(self.vault,config=self.root/"no-api.env",log=lambda _:None)
        self.addCleanup(self.app.close)
        self.app.ai=ForbiddenAI()

    def add(self, filename, transcript, *, kind="tecnica", concepts=None,
            people=None, doubtful_names=None):
        file=self.root/filename
        file.write_text(transcript,encoding="utf-8")
        self.app.add_file(file)
        row=next(s for s in self.app.store.sources("transcript")
                 if s["label"]==filename)
        data={
            "tipo_aula":kind,
            "resumo":"Resumo previamente guardado, não reanalisar.",
            "conceitos":concepts or [],
            "pessoas":people or [],
            "nomes_a_conferir":doubtful_names or [],
            "duvidas":[],"ferramentas":[],"marcos":[],"atividades":[],
        }
        self.app.store.save_analysis(
            row["id"],row["digest"],"offline","cached",data)
        return row

    def author(self, author="Tiago Santini de Athayde"):
        post={
            "aula":"Aula-002","titulo":"Instalação e ferramentas",
            "data":"03/03/2026","autor":author,
            "pessoas":author+" — autor do post do Classroom (não prova apresentação)",
            "descricao":"Instalação do ambiente","atividades":"",
            "gravacoes":[],"_pasted_classroom":True
        }
        self.assertTrue(AutoOrganizer(self.app,log=lambda _:None)._save_extracted(
            {"id":"post-aula-02","stored_path":"(post copiado)"},
            "Aula-002",post,reason="Post copiado do Classroom"))

    def note(self, lesson, video):
        files=sorted((self.vault/"02-Minhas-Aulas"/lesson).glob("*.md"))
        chosen=[p for p in files if not p.name.startswith("00-")
                and video.lower() in p.name.lower()]
        self.assertEqual(len(chosen),1,[(p.name) for p in files])
        return chosen[0].read_text(encoding="utf-8")

    def test_concept_links_exist_in_all_generated_views_and_are_canonical(self):
        base=[
            {"nome":"Extensão C# Dev Kit","explicacao":"Extensão da ferramenta.","tempo":"0:01"},
            {"nome":"C# Dev Kit","explicacao":"Ferramenta para C#.","tempo":"0:02"},
            {"nome":"Extensão .cs","explicacao":"Extensão do código.","tempo":"0:03"},
            {"nome":"Arquivo .cs","explicacao":"Arquivo de C#.","tempo":"0:04"},
        ]
        first=self.add("A02 - V01 - Instalação.txt",
                       "[0:01] Extensão C# Dev Kit.\n"
                       "[0:02] C# Dev Kit.\n"
                       "[0:03] Extensão .cs.\n"
                       "[0:04] Arquivo .cs.\n"
                       "[0:05] Um algoritmo no console.\n",
                       concepts=base)
        self.add("A02 - V02 - Ferramentas.txt",
                 "[0:01] Arquivo .cs, Extensão C# Dev Kit.\n",
                 concepts=[{"nome":"Arquivo .cs","tempo":"0:01",
                            "explicacao":"Outra observação."}])
        # The same old spelling has a distinct (unmerged) mapping elsewhere.
        # v2.2.4 lost the global alias and emitted a dangling overview link.
        self.add("A03 - V01 - Exercício.txt",
                 "[0:01] Arquivo .cs numa variável do console.\n",
                 concepts=[{"nome":"Arquivo .cs","tempo":"0:01",
                            "explicacao":"Outro assunto."}])
        original=self.app.store.analysis(first["id"],first["digest"])
        old_digest=hashlib.sha256(json.dumps(original,sort_keys=True).encode()).hexdigest()
        self.app.publisher.rebuild()
        pages={p.stem for p in (self.vault/"01-Meu-Conhecimento"/"Conceitos").glob("*.md")}
        self.assertIn("c-sharp-dev-kit",pages)
        self.assertIn("cs",pages)

        overview=(self.vault/"02-Minhas-Aulas"/"Aula-002"/"00-Visao-geral.md"
                 ).read_text(encoding="utf-8")
        atlas=(self.vault/"01-Meu-Conhecimento"/"Mapa-da-Evolucao.md"
              ).read_text(encoding="utf-8")
        context=(self.vault/"00-Inicio"/"MEU_CONTEXTO.md").read_text(encoding="utf-8")
        modules=[p.read_text(encoding="utf-8")
                 for p in (self.vault/"01-Meu-Conhecimento"/"Modulos").glob("*.md")]
        self.assertTrue(modules)
        sections=[
            overview.split("## Conhecimentos técnicos citados",1)[1]
                    .split("\n## ",1)[0],
            atlas.split("## Trajetória por conceito",1)[1]
                    .split("\n## ",1)[0],
            context.split("## Conceitos encontrados",1)[1]
                   .split("\n## ",1)[0],
        ]
        sections.extend(m.split("## Conceitos e explicações encontrados nas fontes",1)[1]
                        .split("\n## ",1)[0]
                        for m in modules
                        if "## Conceitos e explicações encontrados nas fontes" in m)
        self.assertGreater(len(sections),3)
        for section in sections:
            names=re.findall(r"\[\[([^|#\]]+)\|([^\]]+)\]\]",section)
            self.assertTrue(names,section[:250])
            for target,label in names:
                self.assertIn(target,pages,
                    f"Broken concept target [[{target}|{label}]]")
                if target=="c-sharp-dev-kit":
                    self.assertEqual(label,"C# Dev Kit")
                if target=="cs" and "Aula-002" in section:
                    self.assertEqual(label,".cs")
            self.assertNotIn("[[extensao-c-sharp-dev-kit",section)
            self.assertNotIn("[[extensao-cs",section)
        topic=sections[0]
        self.assertEqual(topic.count("[[c-sharp-dev-kit|C# Dev Kit]]"),1)
        self.assertEqual(topic.count("[[cs|.cs]]"),1)
        self.assertIn("[[cs|.cs]]",atlas)
        self.assertIn("[[c-sharp-dev-kit|C# Dev Kit]]",atlas)
        self.assertIn("[[cs|.cs]]",context)
        self.assertEqual(self.app.ai.attempts,0)
        self.assertEqual(hashlib.sha256(json.dumps(
            self.app.store.analysis(first["id"],first["digest"]),
            sort_keys=True).encode()).hexdigest(),old_digest)
        self.app.publisher.rebuild()
        self.assertEqual((self.vault/"01-Meu-Conhecimento"/"Mapa-da-Evolucao.md"
                          ).read_text(encoding="utf-8"),atlas)

    def test_tiago_teacher_is_canonical_and_archives_generated_thiago(self):
        self.add("A01 - V01 - Apresentação Thiago Santini.txt",
                 "[0:01] Eu sou o Thiago Santini.\n",
                 kind="apresentacao",
                 people=[{"nome":"Thiago Santini","papel":"professor"}])
        self.author()
        self.add("A02 - V03 - Ferramentas.txt",
                 "[0:01] O Thago Rover explicou a extensão no console.\n",
                 doubtful_names=["Thago Rover"])
        self.add("A02 - V04 - Revisão.txt",
                 "[0:01] O Thiago Santini apresentou as ferramentas.\n",
                 people=[{"nome":"Thiago Santini","papel":"professor"}],
                 doubtful_names=["Thiago Santini"])
        people=self.vault/"01-Meu-Conhecimento"/"Pessoas"
        people.mkdir(parents=True,exist_ok=True)
        legacy="01-Meu-Conhecimento/Pessoas/thiago-santini.md"
        old_content="---\ntipo: 'pessoa'\n---\n# Thiago Santini\n\nRegistros antigos.\n"
        self.app.publisher.write(legacy,old_content)
        self.app.publisher.rebuild()
        canonical=people/"tiago-santini-de-athayde.md"
        self.assertTrue(canonical.is_file())
        content=canonical.read_text(encoding="utf-8")
        self.assertIn("# Tiago Santini de Athayde",content)
        self.assertIn("aliases:",content)
        self.assertIn("Thiago Santini",content)
        self.assertFalse((people/"thiago-santini.md").exists())
        archive=self.vault/"90-Sistema"/"Pessoas-Arquivadas"
        history=list(archive.glob("thiago-santini-*.md"))
        self.assertEqual(len(history),1)
        self.assertEqual(history[0].read_text(encoding="utf-8"),old_content)

        v03=self.note("Aula-002","v03")
        v04=self.note("Aula-002","v04")
        self.assertIn("Thago Rover (possivelmente Tiago Santini de Athayde)",v03)
        self.assertNotIn("Thago Rover (possivelmente Thiago Santini)",v03)
        self.assertIn("Tiago Santini de Athayde",v04)
        self.assertIn("Thiago Santini (alias de Tiago Santini de Athayde)",v04)
        first_overview=(self.vault/"02-Minhas-Aulas"/"Aula-001"/"00-Visao-geral.md"
                        ).read_text(encoding="utf-8")
        later_overview=(self.vault/"02-Minhas-Aulas"/"Aula-002"/"00-Visao-geral.md"
                        ).read_text(encoding="utf-8")
        context=(self.vault/"00-Inicio"/"MEU_CONTEXTO.md"
                 ).read_text(encoding="utf-8")
        for doc in (first_overview,later_overview,context):
            self.assertNotIn("[[thiago-santini|",doc)
            self.assertIn("[[tiago-santini-de-athayde|Tiago Santini de Athayde]]",doc)
        self.app.publisher.rebuild()
        self.assertEqual(len(list(archive.glob("thiago-santini-*.md"))),1)
        self.assertEqual(self.app.ai.attempts,0)

    def test_manually_edited_legacy_name_is_never_archived(self):
        self.add("A01 - V01 - Apresentação Thiago Santini.txt",
                 "[0:01] Sou Thiago Santini.\n",kind="apresentacao",
                 people=[{"nome":"Thiago Santini"}])
        self.author()
        rel="01-Meu-Conhecimento/Pessoas/thiago-santini.md"
        self.app.publisher.write(rel,
            "---\ntipo: 'pessoa'\n---\n# Thiago Santini\n")
        saved=self.vault/rel
        saved.write_text(saved.read_text(encoding="utf-8")+
                         "\nAnotação manual a preservar.\n",encoding="utf-8")
        self.app.publisher.rebuild()
        self.assertIn("Anotação manual a preservar.",
                      saved.read_text(encoding="utf-8"))
        self.assertTrue((self.vault/"01-Meu-Conhecimento"/"Pessoas"/
                         "tiago-santini-de-athayde.md").is_file())
        self.assertEqual(self.app.ai.attempts,0)


if __name__=="__main__":
    unittest.main()
