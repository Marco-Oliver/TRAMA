"""Offline adversarial fidelity checks across transcription, Obsidian and code.

All dialogues, summaries, tokens and paths below are FICTIONAL. No real user
lesson, private Obsidian vault, API key, paid provider or release publication.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.ai import AIResult
from knowledge_bridge.content import chunks, timed_lines
from knowledge_bridge.pipeline import Application


def long_synthetic_lesson() -> str:
    """Two blocks; HttpClient is spoken ONLY in the final block."""
    opening = [
        "[0:00] Introdução fictícia ao recebimento de pedidos.",
        "[0:01] O pedido pode ser enfileirado para processamento futuro.",
    ]
    middle = [
        f"[{i//60}:{i%60:02d}] A aplicação recebe um novo pedido, "
        "faz validações e apresenta a fila de eventos em um desenho "
        "conceitual fictício, sem implementar integrações."
        for i in range(2, 157)
    ]
    ending = [
        "[20:05] Agora mostramos a referência literal HttpClient, "
        "somente nesta parte final da gravação.",
        "[20:11] O exemplo termina sem afirmar que a API ficou pronta.",
    ]
    return "\n".join(opening + middle + ending) + "\n"


class AdversarialModel:
    def __init__(self):
        self.calls = []

    def analyze(self, piece: str, context: str):
        self.calls.append(piece)
        # Deliberate cross-chunk hallucination, repeated in the first block.
        if "HttpClient" not in piece:
            return AIResult({
                "resumo": "A aula implementou GraphQL, segundo esta resposta FALSA da IA.",
                "tipo_aula": "tecnica",
                "conceitos": [{"nome": "HttpClient",
                               "explicacao": "Citação incorreta de outro bloco",
                               "tempo": "20:05"}],
                "exemplos": [], "duvidas": [],
            }, "fixture", "offline")
        return AIResult({
            "resumo": "O trecho final cita HttpClient literalmente; "
                      "a conclusão técnica ainda precisa de revisão humana.",
            "tipo_aula": "tecnica",
            "conceitos": [{"nome": "HttpClient",
                           "explicacao": "Termo mencionado no trecho final",
                           "tempo": "20:05"}],
            "exemplos": [], "duvidas": [],
        }, "fixture", "offline")


class ChunkFidelityTests(unittest.TestCase):
    def test_independent_chunk_cannot_borrow_a_later_timestamp_or_term(self):
        text = long_synthetic_lesson()
        sections = chunks(text)
        self.assertEqual(len(sections), 2, "Fixture must cross one real 11500-byte boundary")
        self.assertEqual(timed_lines("\n".join(sections)), timed_lines(text))
        self.assertNotIn("HttpClient", sections[0])
        self.assertIn("HttpClient", sections[1])

        deceptive = {
            "resumo": "Incluímos GraphQL e JWT.",
            "tipo_aula": "tecnica",
            "conceitos": [{"nome": "HttpClient", "tempo": "20:05",
                           "explicacao": "Inventado para o primeiro bloco."}],
            "ferramentas": [{"nome": "Kafka", "tempo": "20:05"}],
        }
        # Historic behavior accepted a concept and timestamp from another
        # chunk because the original WHOLE lesson contained that word/time.
        local = Application._clean_result(deceptive, sections[0])
        self.assertEqual(local["conceitos"], [])
        self.assertEqual(local["ferramentas"][0]["tempo"], "")
        self.assertEqual([c["nome"] for c in local["conceitos_a_conferir"]],
                         ["HttpClient"])
        warning = " ".join(local["qualidade_pendente"])
        self.assertIn("GraphQL", warning)
        self.assertIn("JWT", warning)
        self.assertNotIn("GraphQL", sections[0])
        actual = Application._clean_result({
            "resumo": "A parte dois contém HttpClient.",
            "conceitos": [{"nome": "HttpClient", "tempo": "20:05",
                           "explicacao": "Citação literal."}],
        }, sections[1])
        self.assertEqual(actual["conceitos"][0]["tempo"], "20:05")
        self.assertNotIn("Nomes técnicos", " ".join(actual["qualidade_pendente"]))

    def test_cached_old_chunk_is_revalidated_offline_without_rebilling(self):
        text = long_synthetic_lesson()
        with tempfile.TemporaryDirectory(prefix="trama-faithful-chunks-") as temp:
            root = Path(temp)
            transcript = root / "Aula-137-V01.txt"
            transcript.write_text(text, encoding="utf-8")
            vault = root / "cofre-de-teste"
            app = Application(vault, root / "nao-e-uma-chave.env",
                              log=lambda *_: None)
            model = AdversarialModel()
            app.ai = model
            try:
                self.assertTrue(app.add_file(transcript))
                src = app.store.sources("transcript")[0]
                context_digest = hashlib.sha256(
                    json.dumps([], ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                cache_digest = hashlib.sha256(
                    (src["digest"] + context_digest).encode()
                ).hexdigest()
                # Replicate old cached result: concept was incorrectly grounded
                # against the entire recording, not its original chunk.
                old = Application._clean_result({
                    "resumo": "Foi implementado GraphQL.",
                    "tipo_aula": "tecnica",
                    "conceitos": [{"nome": "HttpClient", "tempo": "20:05",
                                   "explicacao": "Modelo cruzou outro trecho."}],
                }, text)
                self.assertEqual(len(old["conceitos"]), 1)
                app.store.save_chunk(src["id"], cache_digest, 0,
                                     "fixture", "old-policy", old)

                app.process()
                self.assertEqual(len(model.calls), 1,
                                 "Revalidated cache must not spend more calls")
                data = app.store.analysis(src["id"], src["digest"])
                self.assertEqual(
                    [(c["nome"], c["tempo"]) for c in data["conceitos"]],
                    [("HttpClient", "20:05")])
                self.assertEqual(data["conceitos"][0]["explicacao"],
                                 "Termo mencionado no trecho final")
                self.assertIn("GraphQL", " ".join(data["qualidade_pendente"]))
                self.assertTrue(data["conceitos_a_conferir"])

                lesson = vault / "02-Minhas-Aulas" / "Aula-137"
                overview = (lesson / "00-Visao-geral.md").read_text(
                    encoding="utf-8")
                note = next(x for x in lesson.glob("*.md")
                            if x.name != "00-Visao-geral.md").read_text(
                                encoding="utf-8")
                self.assertIn("Fidelidade a conferir", overview)
                self.assertIn("Síntese assistida por IA", note)
                self.assertIn("GraphQL", note)
                self.assertIn("20:05", note)
                self.assertIn("Citação incorreta de outro bloco", " ".join(
                    c.get("explicacao", "") for c in old["conceitos"]))
                self.assertNotIn(
                    "Citação incorreta de outro bloco", note)
                self.assertEqual(transcript.read_text(encoding="utf-8"), text)
                self.assertEqual(len(app.store.sources("transcript")), 1)

                # Repeating the workflow must not change notes or charge a
                # model request for the same digest and context.
                note_path = next(x for x in lesson.glob("*.md")
                                 if x.name != "00-Visao-geral.md")
                stable_bytes = note_path.read_bytes()
                app.process()
                self.assertEqual(len(model.calls), 1)
                self.assertEqual(note_path.read_bytes(), stable_bytes)
            finally:
                app.close()


class EvidenceLinkTests(unittest.TestCase):
    def setUp(self):
        self.repo = {
            "evidence": [
                {"concept": "exhaustMap", "path": "src/status.ts",
                 "line": 15, "snippet": "15: exhaustMap(() => refresh())"},
                {"concept": "interval", "path": "src/status.ts",
                 "line": 20, "snippet": "20: interval(2000)"},
            ],
            "symbols": [{"name": "StatusService", "concept": "StatusService",
                         "path": "src/status.ts", "line": 4,
                         "snippet": "4: class StatusService"}]
        }
        self.raw = ("[0:01] O nome ouvido foi exustrix, para evitar "
                    "requisições simultâneas.\n"
                    "[0:10] O StatusService foi citado na aula.\n")

    def test_rejects_fabricated_code_relation_even_with_real_path_line(self):
        analysis = Application._check_comparison({
            "resumo": "Comparação a revisar",
            "relacoes": [
                {"conceito": "Kafka", "tempo": "0:01", "path": "src/status.ts",
                 "line": 15, "explicacao": "Alega Kafka em uma linha com exhaustMap"},
                {"conceito": "exhaustMap", "tempo": "0:01", "path": "src/status.ts",
                 "line": 15, "explicacao": "Operador citado com grafia suspeita"},
                {"conceito": "StatusService", "tempo": "0:10", "path": "src/status.ts",
                 "line": 4, "explicacao": "Classe mencionada literalmente"},
                {"conceito": "interval", "tempo": "0:01", "path": "src/status.ts",
                 "line": 20, "explicacao": "Operador só aparece no código"},
                {"conceito": "exhaustMap", "tempo": "0:01", "path": "src/status.ts",
                 "line": 20, "explicacao": "Linha real, termo ERRADO"}
            ],
            "correcoes": [
                {"ouvido": "exustrix", "sugestao": "Kafka",
                 "tempo": "0:01", "path": "src/status.ts", "line": 15},
                {"ouvido": "exustrix", "sugestao": "exhaustMap",
                 "tempo": "0:01", "path": "src/status.ts", "line": 15}
            ],
            "novidades": [
                {"conceito": "FiltragemDeMagia", "tempo": "0:01"},
                {"conceito": "interval", "tempo": "0:01"}
            ]
        }, self.raw, self.repo)
        self.assertEqual(
            [(x["conceito"], x["line"]) for x in analysis["relacoes"]],
            [("exhaustMap", 15), ("StatusService", 4)])
        self.assertEqual(
            [x["sugestao"] for x in analysis["correcoes"]], ["exhaustMap"])
        self.assertEqual(
            [x["conceito"] for x in analysis["novidades"]], ["interval"])
        self.assertTrue(all(x["status"].startswith("SUGESTÃO")
                            for x in analysis["relacoes"]))

    def test_unrelated_source_cannot_be_linked_as_teacher_code(self):
        raw = ("[0:01] Falamos de SQL e banco de dados.\n"
               "[0:02] A aula termina com exercícios.")
        result = Application._check_comparison({
            "relacoes": [
                {"conceito": "exhaustMap", "tempo": "0:01",
                 "path": "src/status.ts", "line": 15}
            ],
            "correcoes": [],
            "novidades": [{"conceito": "React sem código", "tempo": "0:01"}],
        }, raw, self.repo)
        self.assertEqual(result["relacoes"], [])
        self.assertEqual(result["novidades"], [])


if __name__ == "__main__":
    unittest.main()
