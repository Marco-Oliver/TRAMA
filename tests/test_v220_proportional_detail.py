"""Proportional long-lecture detail and output budget regression (offline).

The concept grounding rules and 40k input chunks are intentionally unchanged.
"""
from __future__ import annotations

import unittest

from knowledge_bridge.ai import SYSTEM_INSTRUCTIONS, _SUMMARY_SCHEMA
from knowledge_bridge.content import CHUNK_MAX_CHARS, chunks
from knowledge_bridge.pipeline import Application


def accepted_names(number=21):
    names = [f"Tecnologia{index:02d}" for index in range(1, number + 1)]
    speech = "[0:01] O professor explicou " + " ".join(names) + " durante a demonstração."
    payload = [{"nome": name, "explicacao": f"Referência verificada: {name}",
                "tempo": "0:01"} for name in names]
    return speech, payload, names


class ProportionalLessonDetailTests(unittest.TestCase):
    def test_schema_exposes_twenty_concepts_ten_examples_and_ten_questions(self):
        fields = _SUMMARY_SCHEMA["properties"]
        self.assertEqual(fields["conceitos"]["maxItems"], 20)
        self.assertEqual(fields["exemplos"]["maxItems"], 10)
        self.assertEqual(fields["duvidas"]["maxItems"], 10)
        self.assertEqual(fields["pessoas"]["maxItems"], 8)
        self.assertEqual(fields["nomes_a_conferir"]["maxItems"], 5)

    def test_prompt_requests_proportional_depth_and_every_real_technical_topic(self):
        self.assertIn("até 2000 caracteres", SYSTEM_INSTRUCTIONS)
        self.assertIn("até 4000 caracteres", SYSTEM_INSTRUCTIONS)
        self.assertIn("20.000 caracteres", SYSTEM_INSTRUCTIONS)
        self.assertIn("CADA assunto técnico", SYSTEM_INSTRUCTIONS)
        self.assertIn("TODAS as etapas", SYSTEM_INSTRUCTIONS)
        self.assertIn("20 conceitos", SYSTEM_INSTRUCTIONS)
        self.assertIn("10 exemplos", SYSTEM_INSTRUCTIONS)
        self.assertIn("10 dúvidas técnicas", SYSTEM_INSTRUCTIONS)
        self.assertIn('"Delivery App"', SYSTEM_INSTRUCTIONS)
        self.assertIn("Não invente", SYSTEM_INSTRUCTIONS)

    def test_summary_cut_is_2000_for_short_input_and_exact_20000_boundary(self):
        payload = {"resumo": "R" * 4500}
        for length in (19999, 20000):
            with self.subTest(characters=length):
                clean = Application._clean_result(payload, "F" * length)
                self.assertEqual(len(clean["resumo"]), 2000)

    def test_summary_cut_is_4000_above_20000_input(self):
        clean = Application._clean_result({"resumo": "R" * 4500},
                                          "F" * 20001)
        self.assertEqual(len(clean["resumo"]), 4000)

    def test_twenty_distinct_literal_names_survive_local_filter(self):
        text, concepts, names = accepted_names()
        result = Application._clean_result({
            "resumo": "O professor apresentou diferentes tecnologias.",
            "conceitos": concepts,
        }, text)
        self.assertEqual([c["nome"] for c in result["conceitos"]], names[:20])
        self.assertTrue(all(c["confianca"] == "nome_literal" for c in result["conceitos"]))
        self.assertEqual(result["conceitos_a_conferir"], [])

    def test_ten_examples_and_questions_are_retained_without_excess(self):
        example_items = [f"Exemplo numero {i}" for i in range(12)]
        question_items = [f"Pergunta numero {i}" for i in range(12)]
        result = Application._clean_result({
            "exemplos": example_items, "duvidas": question_items
        }, "[0:01] " + ". ".join(example_items) + ".")
        self.assertEqual(result["exemplos"], example_items[:10])
        self.assertEqual(result["duvidas"], question_items[:10])

    def test_concept_evidence_validation_is_unchanged(self):
        speech = ("[0:01] A classe filha herda os atributos da classe mãe.\n"
                  "[0:02] Foi apresentada a tecnologia Docker.")
        clean = Application._clean_result({
            "conceitos": [
                {"nome": "Herança", "evidencia":
                    "A classe filha herda os atributos da classe mãe."},
                {"nome": "Docker", "evidencia": ""},
                {"nome": "PostgreSQL", "evidencia": "Uma citação inventada."},
            ],
        }, speech)
        self.assertEqual([(c["nome"], c["confianca"]) for c in clean["conceitos"]],
                         [("Herança", "citacao_literal"), ("Docker", "nome_literal")])
        self.assertEqual([c["nome"] for c in clean["conceitos_a_conferir"]],
                         ["PostgreSQL"])

    def test_large_input_chunk_limit_remains_40000(self):
        self.assertEqual(CHUNK_MAX_CHARS, 40_000)
        source = "[0:01] " + ("Texto fictício sobre programação. " * 1200)
        self.assertEqual(len(chunks(source)), 2)
        self.assertTrue(all(len(piece) <= 40_000 for piece in chunks(source)))


if __name__ == "__main__":
    unittest.main()
