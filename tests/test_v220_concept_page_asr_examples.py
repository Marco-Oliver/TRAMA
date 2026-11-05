"""Aula 131: stable human concept filenames, ASR review hints and literal examples.

Offline synthetic sources only; no real vault or Gemini requests.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.content import (
    concept_file_slug, concept_slug, suspected_concept_name,
    suspected_technical_transcription,
)
from knowledge_bridge.pipeline import Application


def seed(app, root, spoken, concepts=(), examples=()):
    src = root / "Aula-131-V01.txt"
    src.write_text(spoken, encoding="utf-8")
    assert app.add_file(src)
    item = app.store.sources("transcript")[0]
    clean = Application._clean_result({
        "resumo": "Aula de teste.", "tipo_aula": "tecnica",
        "conceitos": list(concepts), "exemplos": list(examples),
    }, spoken)
    app.store.save_analysis(item["id"], item["digest"], "offline", "fixture", clean)
    return clean


def make_app(root):
    return Application(root / "vault-isolado", root / "sem-credenciais.env",
                       log=lambda *_: None)


def lesson_text(app):
    folder = app.store.vault / "02-Minhas-Aulas" / "Aula-131"
    return "\n".join(p.read_text(encoding="utf-8") for p in folder.glob("*.md"))


class ReadableFilenamesTests(unittest.TestCase):
    def test_display_slug_is_not_comparison_key(self):
        labels = {
            "Migrações": "migracoes",
            "Validação de dados": "validacao-de-dados",
            "Variável de ambiente": "variavel-de-ambiente",
            "C": "c", "C#": "c-sharp", "C++": "c-plus-plus",
        }
        for name, expected in labels.items():
            with self.subTest(name=name):
                self.assertEqual(concept_file_slug(name), expected)
        self.assertEqual(concept_slug("Relacionamento de um para um"),
                         concept_slug("Relacionamento um para um"))
        self.assertNotEqual(concept_slug("C#"), concept_slug("C++"))

    def test_fresh_vault_uses_first_readable_name_and_one_page(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            app = make_app(root)
            try:
                seed(app, root, (
                    "[2:20] Validação de dados foi demonstrada.\n"
                    "[2:21] Relacionamento de um para um foi apresentado.\n"
                    "[2:22] Relacionamento um para um foi retomado."),
                    concepts=[
                        {"nome": "Validação de dados", "tempo": "2:20"},
                        {"nome": "Relacionamento de um para um", "tempo": "2:21"},
                        {"nome": "Relacionamento um para um", "tempo": "2:22"},
                    ])
                app.publisher.rebuild()
                pages = app.store.vault / "01-Meu-Conhecimento" / "Conceitos"
                self.assertEqual({p.name for p in pages.glob("*.md")}, {
                    "validacao-de-dados.md", "relacionamento-de-um-para-um.md",
                })
                self.assertIn("[[validacao-de-dados|Validação de dados]]",
                              lesson_text(app))
                self.assertIn("[[relacionamento-de-um-para-um|Relacionamento um para um]]",
                              lesson_text(app))
                atlas = (app.store.vault / "01-Meu-Conhecimento" /
                         "Mapa-da-Evolucao.md").read_text(encoding="utf-8")
                self.assertIn("[[validacao-de-dados|", atlas)
                self.assertIn("[[relacionamento-de-um-para-um|", atlas)
                app.publisher.rebuild()
                self.assertEqual(len(list(pages.glob("*.md"))), 2)
            finally:
                app.close()

    def test_legacy_pages_are_reused_and_links_do_not_point_to_new_duplicate(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            app = make_app(root)
            try:
                seed(app, root, "[2:20] Migrações. Validação de dados.",
                     concepts=[{"nome": "Migrações"}, {"nome": "Validação de dados"}])
                folder = app.store.vault / "01-Meu-Conhecimento" / "Conceitos"
                app.publisher.write("01-Meu-Conhecimento/Conceitos/migracoe.md",
                                    "# Nome anterior\n")
                app.publisher.write("01-Meu-Conhecimento/Conceitos/validacao-dado.md",
                                    "# Nome anterior\n")
                app.publisher.rebuild()
                self.assertEqual({p.name for p in folder.glob("*.md")},
                                 {"migracoe.md", "validacao-dado.md"})
                self.assertIn("[[migracoe|Migrações]]", lesson_text(app))
                self.assertIn("[[validacao-dado|Validação de dados]]",
                              lesson_text(app))
                self.assertFalse((folder / "migracoes.md").exists())
                self.assertFalse((folder / "validacao-de-dados.md").exists())
            finally:
                app.close()


class ASRConceptReviewTests(unittest.TestCase):
    CASES = [
        ("DB Contact", "DbContext"), ("row manager", "RoleManager"),
        ("check password saind assim", "CheckPasswordSignInAsync"),
        ("Winch Framework", "Entity Framework"),
        ("posts", "PostgreSQL"), ("post will", "PostgreSQL"),
    ]

    def test_suspects_are_accepted_by_literal_name_but_flagged_not_renamed(self):
        for label, suggestion in self.CASES:
            with self.subTest(label=label):
                self.assertEqual(suspected_concept_name(label), suggestion)
                transcript = f"[2:20] O professor falou {label} durante a aula."
                self.assertTrue(any(candidate == suggestion for _, _, candidate
                                    in suspected_technical_transcription(transcript)))
                clean = Application._clean_result({
                    "conceitos": [{"nome": label, "tempo": "02:20"}],
                }, transcript)
                self.assertEqual([x["nome"] for x in clean["conceitos"]], [label])
                self.assertEqual(clean["conceitos"][0]["confianca"], "nome_literal")
                self.assertIn(suggestion, clean["conceitos"][0]["suspeita_transcricao"])
                self.assertNotEqual(clean["conceitos"][0]["nome"], suggestion)

    def test_suspicion_shown_on_lesson_and_concept_page(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            app = make_app(root)
            try:
                seed(app, root, "[2:20] DB Contact foi mostrado.",
                     concepts=[{"nome": "DB Contact", "tempo": "2:20"}])
                app.publisher.rebuild()
                self.assertIn("Nome possivelmente distorcido pela transcrição",
                              lesson_text(app))
                self.assertIn("DbContext", lesson_text(app))
                concept = (app.store.vault / "01-Meu-Conhecimento" / "Conceitos" /
                           "db-contact.md").read_text(encoding="utf-8")
                self.assertIn("DbContext", concept)
                self.assertFalse((app.store.vault / "01-Meu-Conhecimento" /
                                  "Conceitos" / "dbcontext.md").exists())
            finally:
                app.close()


class LiteralExampleTests(unittest.TestCase):
    def test_cross_line_literal_is_kept_and_completed_connection_string_is_reviewed(self):
        raw = ("[2:20] O professor falou username P\n"
               "[2:21] e senha PW para conectar.")
        literal = "username P e senha PW"
        invented = "Host=localhost;Username=postgres;Password=pw"
        clean = Application._clean_result({
            "exemplos": [literal, invented],
        }, raw)
        self.assertEqual(clean["exemplos"], [literal])
        self.assertEqual(clean["exemplos_reconstruidos_a_conferir"], [invented])

    def test_normalization_allows_accents_case_and_punctuation(self):
        raw = "[2:20] Exemplo prático: Validação de CPF, não é?"
        clean = Application._clean_result({
            "exemplos": ["EXEMPLO PRATICO: validacao de cpf, nao e?",
                         "Exemplo prático de normalização de números"],
        }, raw)
        self.assertEqual(len(clean["exemplos"]), 1)
        self.assertEqual(len(clean["exemplos_reconstruidos_a_conferir"]), 1)

    def test_review_section_keeps_reconstructed_example_out_of_literal_examples(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            app = make_app(root)
            try:
                literal = "username P e senha PW"
                invented = "Host=localhost;Username=postgres;Password=pw"
                clean = seed(app, root, "[2:20] O exemplo é username P e senha PW.",
                             examples=[literal, invented])
                self.assertEqual(clean["exemplos"], [literal])
                app.publisher.rebuild()
                note = lesson_text(app)
                self.assertIn("## Exemplos mencionados", note)
                self.assertIn("## Exemplos reconstruídos pela IA, conferir", note)
                self.assertIn(invented, note)
                literal_section = note.split("## Exemplos mencionados")[1].split(
                    "## Exemplos reconstruídos pela IA, conferir")[0]
                self.assertIn(literal, literal_section)
                self.assertNotIn(invented, literal_section)
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
