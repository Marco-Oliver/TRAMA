"""Aula 131 fidelity regressions: names, timestamps, concepts and ASR hints.

Synthetic materials only. No live model, credentials, user vault or release.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.ai import SYSTEM_INSTRUCTIONS
from knowledge_bridge.content import concept_slug, concept_file_slug, timestamp_seconds
from knowledge_bridge.pipeline import Application


class PromptFidelityTests(unittest.TestCase):
    def test_prompt_does_not_include_real_person_name_examples(self):
        for forbidden in ("Thagão", "Thag", "Rash"):
            self.assertNotIn(forbidden, SYSTEM_INSTRUCTIONS)
        self.assertIn("nomes que\nnão aparecem literalmente", SYSTEM_INSTRUCTIONS)

    def test_prompt_keeps_uncertain_asr_code_and_literal_examples(self):
        for phrase in ("Status 2011", "provavelmente HTTP 201 Created",
                       "duvidas", "conferir na gravação",
                       'itens de "exemplos"', "trechos literais",
                       "NÃO reconstrua", "o horário exatamente"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, SYSTEM_INSTRUCTIONS)
        self.assertNotIn('"tempo":"mm:ss ou vazio"', SYSTEM_INSTRUCTIONS)


class NamesMustBeInTranscriptTests(unittest.TestCase):
    def test_hallucinated_names_are_removed_from_both_lists(self):
        source = "[2:20] A professora Joana apresentou o módulo.\n"
        payload = {
            "pessoas": [
                {"nome": "Joana", "papel": "professora", "tempo": "2:20"},
                {"nome": "Thagão", "papel": "professor", "tempo": "2:20"},
                {"nome": "Rash", "papel": "colega", "tempo": "2:20"},
            ],
            "nomes_a_conferir": ["Thagão", "Rash", "Joana"],
        }
        actual = Application._clean_result(payload, source)
        self.assertEqual([p["nome"] for p in actual["pessoas"]], ["Joana"])
        self.assertEqual(actual["nomes_a_conferir"], ["Joana"])

    def test_genuine_names_preserved_despite_accent_case_and_punctuation(self):
        source = "[2:20] JOAO SILVA explica algo. Maria falou logo depois."
        actual = Application._clean_result({
            "pessoas": [{"nome": "João Silva", "tempo": "02:20"},
                        {"nome": "Rash", "tempo": "02:20"}],
            "nomes_a_conferir": ["João Silva", "MARÍA", "Marcela"],
        }, source)
        self.assertEqual([p["nome"] for p in actual["pessoas"]], ["João Silva"])
        self.assertEqual(actual["nomes_a_conferir"], ["João Silva", "MARÍA"])
        self.assertEqual(actual["pessoas"][0]["tempo"], "2:20")

    def test_name_match_requires_full_word_not_just_substring(self):
        result = Application._clean_result({
            "pessoas": [{"nome": "Ana"}, {"nome": "Mar"}],
            "nomes_a_conferir": ["Ana", "Mar"],
        }, "[0:02] A palavra banana apareceu em março.")
        self.assertEqual(result["pessoas"], [])
        self.assertEqual(result["nomes_a_conferir"], [])

    def test_absent_person_cannot_suppress_a_real_concept(self):
        source = "[0:01] A classe tem um construtor."
        result = Application._clean_result({
            "pessoas": [{"nome": "Pessoa Fantasma", "papel": "professor imaginado"}],
            "conceitos": [{"nome": "Classe", "tempo": "0:01"}],
        }, source)
        self.assertEqual(result["pessoas"], [])
        self.assertEqual([c["nome"] for c in result["conceitos"]], ["Classe"])


class EquivalentTimestampsTests(unittest.TestCase):
    def test_multiple_spellings_match_the_original_anchor(self):
        raw = "[2:20] Aula sobre Docker."
        for stamp in ("2:20", "02:20", "0:02:20", "00:02:20", "[00:02:20]"):
            with self.subTest(stamp=stamp):
                result = Application._clean_result({
                    "conceitos": [{"nome": "Docker", "tempo": stamp}],
                    "atividades": [{"descricao": "Explicou Docker", "tempo": stamp}],
                    "pessoas": [{"nome": "João", "tempo": stamp}],
                }, raw)
                self.assertEqual(result["conceitos"][0]["tempo"], "2:20")
                self.assertEqual(result["atividades"][0]["tempo"], "2:20")

    def test_original_hour_format_is_preserved(self):
        raw = "[01:02:20] Joana mostrou Docker."
        result = Application._clean_result({
            "pessoas": [{"nome": "Joana", "tempo": "1:02:20"}],
            "conceitos": [{"nome": "Docker", "tempo": "62:20"}],
        }, raw)
        self.assertEqual(result["pessoas"][0]["tempo"], "01:02:20")
        self.assertEqual(result["conceitos"][0]["tempo"], "01:02:20")

    def test_invalid_and_unseen_timestamp_never_accepted(self):
        raw = "[2:20] Docker"
        for invalid in ("2:21", "2:60", "0:62:20", "2:2", "12:99:20",
                        "sem horário", "3:20"):
            with self.subTest(invalid=invalid):
                r = Application._clean_result({
                    "conceitos": [{"nome": "Docker", "tempo": invalid}]
                }, raw)
                self.assertEqual(r["conceitos"][0]["tempo"], "")
        self.assertEqual(timestamp_seconds("00:02:20"), 140)
        self.assertEqual(timestamp_seconds("2:20"), 140)

    def test_check_comparison_normalizes_all_three_time_fields(self):
        raw = "[2:20] A professora disse exustrix e mostrou StatusService."
        repo = {
            "evidence": [
                {"concept": "exhaustMap", "path": "src/status.ts",
                 "line": 15, "snippet": "15: exhaustMap(() => refresh())"},
            ],
            "symbols": [
                {"name": "StatusService", "concept": "StatusService",
                 "path": "src/status.ts", "line": 4, "snippet": "4: class StatusService"},
            ],
        }
        result = Application._check_comparison({
            "relacoes": [{"conceito": "StatusService", "tempo": "02:20",
                          "path": "src/status.ts", "line": 4}],
            "correcoes": [{"ouvido": "exustrix", "sugestao": "exhaustMap",
                           "tempo": "0:02:20", "path": "src/status.ts", "line": 15}],
            "novidades": [{"conceito": "StatusService", "tempo": "00:02:20"}],
        }, raw, repo)
        self.assertEqual([x["tempo"] for x in result["relacoes"]], ["2:20"])
        self.assertEqual([x["tempo"] for x in result["correcoes"]], ["2:20"])
        self.assertEqual([x["tempo"] for x in result["novidades"]], ["2:20"])


class ConceptGroupingTests(unittest.TestCase):
    def test_connection_words_and_simple_plurals_merge(self):
        self.assertEqual(concept_slug("Relacionamento de um para um"),
                         concept_slug("Relacionamento um para um"))
        self.assertEqual(concept_slug("Relacionamentos de um para um"),
                         concept_slug("Relacionamento um para um"))
        self.assertEqual(concept_slug("Tabelas"), concept_slug("Tabela"))
        self.assertEqual(concept_slug("Banco de Dados"),
                         concept_slug("Banco dado"))

    def test_distinct_technical_identifiers_remain_distinct(self):
        different = [
            ("C", "C#"), ("C#", "C++"), ("C++", "C"),
            ("HTTP", "HTTPS"), ("Redis", "Redi"),
            ("Postgres", "PostgreSQL"),
            ("Entity Framework", "Entity Framework Core"),
            ("Docker", "Docker Compose"),
            ("Windows", "Window"),
        ]
        for left, right in different:
            with self.subTest(left=left, right=right):
                self.assertNotEqual(concept_slug(left), concept_slug(right))

    def test_publisher_creates_one_concept_page_for_two_wording_variants(self):
        with tempfile.TemporaryDirectory(prefix="trama-a131-alias-") as folder:
            root = Path(folder)
            app = Application(root / "cofre-ficticio", root / "no-key.env",
                              log=lambda *_: None)
            try:
                source = root / "A131-V01.txt"
                source.write_text(
                    "[2:20] Relacionamento de um para um é demonstrado.\n"
                    "[2:21] Relacionamento um para um é revisado.\n",
                    encoding="utf-8")
                self.assertTrue(app.add_file(source))
                record = app.store.sources("transcript")[0]
                data = Application._clean_result({
                    "tipo_aula": "tecnica",
                    "resumo": "Aula sobre relacionamentos.",
                    "conceitos": [
                        {"nome": "Relacionamento de um para um",
                         "explicacao": "Primeira explicação", "tempo": "02:20"},
                        {"nome": "Relacionamento um para um",
                         "explicacao": "Segunda explicação", "tempo": "00:02:21"},
                    ],
                }, source.read_text(encoding="utf-8"))
                app.store.save_analysis(record["id"], record["digest"],
                                        "fixture", "offline", data)
                app.publisher.rebuild()
                pages = list((app.store.vault /
                              "01-Meu-Conhecimento" / "Conceitos").glob("*.md"))
                self.assertEqual(len(pages), 1, [p.name for p in pages])
                self.assertEqual(pages[0].stem,
                                 concept_file_slug("Relacionamento de um para um"))
                note = pages[0].read_text(encoding="utf-8")
                self.assertIn("Primeira explicação", note)
                self.assertIn("Segunda explicação", note)
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
