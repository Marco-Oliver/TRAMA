"""Obsidian quality: complete reviews, traceable evidence and human-safe output.

All scenarios are synthetic, offline, and leave user vaults untouched.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.ai import AIResult
from knowledge_bridge.pipeline import Application
from knowledge_bridge.publishing import _code_ref
from knowledge_bridge.vault_index import VaultIndex


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vault = self.root / "cofre"
        self.config = self.root / "config.env"
        self.config.write_text("FREE_TIER_CONFIRMED=NO\n", encoding="utf-8")
        self.app = Application(self.vault, self.config, log=lambda _msg: None)

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def source(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        self.app.add_file(path)
        return next(s for s in self.app.store.sources("transcript") if s["label"] == name)

    def analysis(self, source, summary, concepts=None, examples=None, doubts=None):
        data = {
            "resumo": summary,
            "tipo_aula": "tecnica",
            "conceitos": concepts or [],
            "exemplos": examples or [],
            "duvidas": doubts or [],
        }
        self.app.store.save_analysis(source["id"], source["digest"], "teste", "mock", data)

    def lesson_note(self, lesson="Aula-001"):
        return next(
            p for p in (self.vault / "02-Minhas-Aulas" / lesson).glob("*.md")
            if p.name != "00-Visao-geral.md"
        )

    def test_module_study_guide_keeps_full_explanations_and_examples(self):
        s1 = self.source(
            "Aula-001-V01.txt",
            "[0:04] O console escreve texto.\n[0:10] Também usamos console para saída.",
        )
        s2 = self.source(
            "Aula-002-V01.txt",
            "[0:01] O console recebeu dados.\n[0:20] O console retornou resultado.",
        )
        long_summary = "O professor demonstrou a saída de dados. " + ("Exemplo detalhado. " * 31)
        self.analysis(s1, long_summary,
            [{"nome": "Console", "explicacao": "Exibe resultados no terminal.", "tempo": "0:04"}],
            ["Console.WriteLine no primeiro programa"])
        self.analysis(s2, "A segunda aula retomou o console.",
            [{"nome": "Console", "explicacao": "Revisão e aplicação no terminal.", "tempo": "0:01"}])
        self.app.publisher.rebuild()
        page = (self.vault / "01-Meu-Conhecimento/Modulos/Logica-de-Programacao.md").read_text(encoding="utf-8")
        self.assertIn(long_summary.strip(), page)
        self.assertIn("A segunda aula retomou", page)
        self.assertIn("Console.WriteLine no primeiro programa", page)
        self.assertIn("## Conceitos e explicações encontrados nas fontes", page)
        self.assertIn("02-Minhas-Aulas/Aula-001/00-Visao-geral", page)
        self.assertIn("## Como revisar", page)

    def test_inferred_concept_is_not_certified_taught(self):
        source = self.source(
            "Aula-001-V01.txt",
            "[0:04] O console recebe entrada.\n[0:06] O console mostra saída.",
        )
        self.analysis(source, "Falou de console.",
            [{"nome": "AlienMethod", "explicacao": "Suposto recurso.", "tempo": "0:04"}])
        self.app.publisher.rebuild()
        page = (self.vault / "01-Meu-Conhecimento/Conceitos/alienmethod.md").read_text(encoding="utf-8")
        self.assertIn("estado: 'interpretacao_ia_sem_termo_literal'", page)
        self.assertIn("interpretação da IA; termo não encontrado literalmente", page)
        self.assertNotIn("Ensinado: encontrado nas aulas", page)
        ctx = (self.vault / "00-Inicio/MEU_CONTEXTO.md").read_text(encoding="utf-8")
        self.assertIn("identificado pela IA; confirmar na fonte", ctx)
        module = (self.vault / "01-Meu-Conhecimento/Modulos/Logica-de-Programacao.md").read_text(encoding="utf-8")
        self.assertIn("termo inferido pela IA", module)

    def test_concept_page_preserves_multiple_explanations_and_time_anchors(self):
        source = self.source(
            "Aula-001-V01.txt",
            "[0:04] Uma classe agrupa dados.\n[0:07] Uma classe pode ter construtor.",
        )
        self.analysis(source, "Introdução a classes.", [
            {"nome": "Classe", "explicacao": "Primeiro: reúne dados.", "tempo": "0:04"},
            {"nome": "Classe", "explicacao": "Depois: pode ter construtores.", "tempo": "0:07"},
        ])
        self.app.publisher.rebuild()
        note = self.lesson_note().read_text(encoding="utf-8")
        page = (self.vault / "01-Meu-Conhecimento/Conceitos/classe.md").read_text(encoding="utf-8")
        self.assertIn("^min-0-04", note)
        self.assertIn("^min-0-07", note)
        self.assertIn("#^min-0-04", page)
        self.assertIn("#^min-0-07", page)
        self.assertIn("Primeiro: reúne dados.", page)
        self.assertIn("Depois: pode ter construtores.", page)

    def test_distinct_explanations_survive_pipeline_chunk_merge(self):
        source = self.source(
            "Aula-001-V01.txt",
            "[0:04] Uma classe agrupa os dados.\n" + ("Texto de introdução. " * 550)
            + "\n[10:04] Uma classe pode incluir comportamentos.\n",
        )
        counter = [0]
        def analyze(_piece, _context):
            counter[0] += 1
            stamp = "0:04" if counter[0] == 1 else "10:04"
            return AIResult({
                "resumo": f"Parte {counter[0]} sobre classe.",
                "tipo_aula": "tecnica",
                "conceitos": [{"nome": "classe",
                              "explicacao": f"Explicação distinta {counter[0]}",
                              "tempo": stamp}],
                "exemplos": [], "duvidas": [],
            }, "mock", "fake")
        self.app.ai.analyze = analyze
        self.app.process()
        result = self.app.store.analysis(source["id"], source["digest"])
        self.assertGreaterEqual(counter[0], 2)
        self.assertEqual(len(result["conceitos"]), counter[0])
        concepts = (self.vault / "01-Meu-Conhecimento/Conceitos/classe.md").read_text(encoding="utf-8")
        self.assertIn("Explicação distinta 1", concepts)
        self.assertIn("Explicação distinta 2", concepts)

    def test_code_reference_points_at_immutable_github_line(self):
        repo = {"name": "Aula", "url": "https://github.com/academia/projeto.git",
                "sha": "a" * 40}
        link = _code_ref(repo, "src/hello world.cs", 41)
        self.assertIn("/blob/" + "a"*40 + "/src/hello%20world.cs#L41", link)
        self.assertIn("`src/hello world.cs:41`", link)
        repo["url"] = str(self.root / "projeto")
        self.assertNotIn("http", _code_ref(repo, "Program.cs", 7))

    def test_github_code_link_is_published_on_lecture_and_project(self):
        source = self.source("Aula-001-V01.txt",
                             "[0:04] O subscribe atualiza dados e o subscribe observa eventos.")
        self.analysis(source, "O professor abordou subscribe.",
                      [{"nome":"subscribe", "explicacao": "Observa eventos", "tempo": "0:04"}])
        self.app.store.save_repo(
            "https://github.com/academia/projeto", "exemplo", "a"*40,
            {"files": [], "technologies": ["TypeScript"],
             "evidence": [{"concept":"subscribe", "path":"src/app.ts",
                           "line":19, "snippet":"19: obs.subscribe()", "line_text":"obs.subscribe()"}],
             "documentation": [], "history": []},
            "PUBLISHED")
        self.app.publisher.rebuild()
        lecture = self.lesson_note().read_text(encoding="utf-8")
        project = next((self.vault / "03-Meus-Projetos").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("/blob/" + "a"*40 + "/src/app.ts#L19", lecture)
        self.assertIn("obs.subscribe()", lecture)
        self.assertIn("```typescript", lecture)
        self.assertIn("/blob/" + "a"*40 + "/src/app.ts#L19", project)

    def test_duplicate_proposal_is_not_recreated_if_earlier_one_was_edited(self):
        self.source("Aula-001-V01.txt",
                    "[0:04] O console escreve.\n[0:07] O console mostra dados.")
        self.app.publisher.rebuild()
        note = self.lesson_note()
        note.write_text("# Anotação pessoal", encoding="utf-8")
        self.app.publisher.rebuild()
        proposals = sorted(note.parent.glob(note.stem + ".PROPOSTA*.md"))
        self.assertEqual(len(proposals), 1)
        proposals[0].write_text("# Proposta comentada por mim", encoding="utf-8")
        self.app.publisher.rebuild()
        self.assertEqual(len(list(note.parent.glob(note.stem + ".PROPOSTA*.md"))), 2)
        self.app.publisher.rebuild()
        self.assertEqual(len(list(note.parent.glob(note.stem + ".PROPOSTA*.md"))), 2)
        self.assertEqual(note.read_text(encoding="utf-8"), "# Anotação pessoal")


class NavigationTests(unittest.TestCase):
    def test_ambiguous_stems_do_not_point_to_unrelated_lecture(self):
        with tempfile.TemporaryDirectory() as folder:
            vault = Path(folder)
            for lesson in ("Aula-001", "Aula-002"):
                path = vault / "02-Minhas-Aulas" / lesson / "00-Visao-geral.md"
                path.parent.mkdir(parents=True)
                path.write_text("# " + lesson, encoding="utf-8")
            idx = VaultIndex(vault)
            self.assertIsNone(idx.resolve("00-Visao-geral"))
            self.assertEqual(
                idx.resolve("02-Minhas-Aulas/Aula-002/00-Visao-geral").title,
                "Aula-002",
            )
            first = next(n for n in idx.notes if "Aula-001" in n.relative)
            self.assertEqual(idx.resolve("00-Visao-geral", first), first)

    def test_search_looks_beyond_first_800_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "aula.md"
            file.write_text("# Aula\n" + ("x"*1100) +
                            "\nUma migração especial com EF Core.", encoding="utf-8")
            index = VaultIndex(Path(folder))
            self.assertEqual(len(index.filter("biblioteca", "migração especial")), 1)


if __name__ == "__main__":
    unittest.main()
