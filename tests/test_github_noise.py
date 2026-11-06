"""Do not advertise language keywords as code relations or ASR suspicions."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.code_intel import (
    concept_from_text, is_generic_code_term,
    match_lesson_to_repository, potential_transcript_corrections,
)
from knowledge_bridge.pipeline import Application


WORDS = [
    "class", "interface", "public", "static", "namespace", "using",
    "string", "void", "classe", "método", "controller",
]


def entry(name, path="src/DeliveryController.cs"):
    return {
        "concept": name, "name": name, "path": path, "line": 7,
        "snippet": f"7: {name}", "line_text": name,
    }


def index():
    return {
        "files": [{"path": "src/DeliveryController.cs", "size": 100}],
        "total_files": 1,
        "technologies": ["C#"],
        "evidence": [
            *(entry(term) for term in WORDS),
            entry("HttpClient"),
        ],
        "symbols": [
            *(entry(term) for term in WORDS),
            entry("DeliveryController"), entry("HttpClient"),
        ],
        "documentation": [],
        "history": [],
        "collaboration": False,
    }


class GithubNoiseFilteringTests(unittest.TestCase):
    def test_all_generic_terms_are_ignored_as_code_relations(self):
        text = "00:10 " + " ".join(WORDS) + " HttpClient DeliveryController"
        for term in WORDS:
            with self.subTest(term=term):
                self.assertTrue(is_generic_code_term(term))
        self.assertTrue(is_generic_code_term("MÉTODO"))
        self.assertFalse(is_generic_code_term("DeliveryController"))
        self.assertFalse(is_generic_code_term("HttpClient"))
        self.assertNotIn("class", concept_from_text(text))
        self.assertNotIn("interface", concept_from_text(text))
        self.assertNotIn("Controller", concept_from_text(text))
        matches = match_lesson_to_repository(text, None, index())
        labels = [row["concept"] for row in matches]
        self.assertIn("HttpClient", labels)
        self.assertIn("DeliveryController", labels)
        self.assertFalse(set(WORDS).intersection(labels))
        self.assertEqual(potential_transcript_corrections(
            "class classe interface controller", index()), [])

    def test_obsidian_code_and_suspicious_terms_exclude_generic_words(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = Application(root / "vault", root / "no-keys.env",
                              log=lambda message: None)
            try:
                source = root / "A131 - V01 - Codigo.txt"
                source.write_text("00:10 " + " ".join(WORDS) +
                                  " HttpClient DeliveryController\n", encoding="utf-8")
                app.add_file(source)
                row = next(s for s in app.store.sources("transcript")
                           if s["label"] == source.name)
                app.store.save_repo(
                    "https://github.com/example/course", "course", "a"*40,
                    index(), "INDEXED",
                )
                app.store.save_analysis(
                    row["id"], row["digest"], "test", "mock",
                    {
                        "resumo": "Conferindo código específico do projeto.",
                        "tipo_aula": "tecnica",
                        "conceitos": [],
                        "conceitos_a_conferir": [
                            {"nome": term} for term in WORDS + ["HttpClient"]
                        ],
                    },
                )
                app.publisher.rebuild()
                notes = list((app.store.vault / "02-Minhas-Aulas" /
                              "Aula-131").glob("*.md"))
                notes = [p for p in notes if p.name != "00-Visao-geral.md"]
                self.assertEqual(len(notes), 1)
                md = notes[0].read_text(encoding="utf-8")
                section = md.split("## Relações com códigos e projetos", 1)[1]
                section = section.split("## Termos suspeitos da transcrição", 1)[0]
                self.assertIn("HttpClient", section)
                self.assertIn("DeliveryController", section)
                for term in WORDS:
                    self.assertNotIn("- " + chr(96) + term + chr(96) + " —", md)
                    self.assertNotIn(f"### {term}\n", section)
                self.assertIn(chr(96) + "HttpClient" + chr(96), md)
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
