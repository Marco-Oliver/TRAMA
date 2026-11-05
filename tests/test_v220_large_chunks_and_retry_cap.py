"""C6: larger chunks, free-tier retry cap and one-call batch measurement.

Uses synthetic lessons and mocked provider responses only. No Obsidian data or real API.
"""
from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge import ai
from knowledge_bridge.ai import (AIResult, AllProvidersFailed, FreeAIRouter, ProviderError,
                                 SYSTEM_INSTRUCTIONS)
from knowledge_bridge.content import chunks
from knowledge_bridge.pipeline import Application
from tools.teste_gemini import run


def fake_router():
    return FreeAIRouter({
        "FREE_TIER_CONFIRMED": "YES",
        "FREE_PROVIDER_ORDER": "gemini",
        "GEMINI_API_KEY": "fake-for-test",
    })


def sample_payload():
    return {
        "resumo": "Resumo de uma aula fictícia sobre ferramentas.",
        "tipo_aula": "tecnica",
        "conceitos": [],
        "pessoas": [],
        "atividades": [],
        "ferramentas": [],
        "marcos": [],
        "exemplos": [],
        "duvidas": [],
        "nomes_a_conferir": [],
    }


def lesson_text():
    # About 30k characters: at least three old chunks, one new chunk.
    return "\n".join(
        f"[0:{minute:02d}] "
        + "O professor mostra Docker e explica a mensageria no terminal. " * 30
        for minute in range(18)
    )


class RetryAfterBoundTests(unittest.TestCase):
    def test_gemini_retry_after_above_30s_is_logged_and_not_slept(self):
        router = fake_router()
        with self.assertLogs("knowledge_bridge.ai", level="WARNING") as warnings, \
             patch.object(ai.time, "sleep") as sleep, \
             patch.object(ai, "_completion",
                          side_effect=ProviderError("gemini", "falha HTTP 503",
                                                    retryable=True, retry_after=75)) as send:
            with self.assertRaises(AllProvidersFailed) as failure:
                router.analyze("[0:01] Mensageria.", "teste sem rede")
        self.assertIn("Retry-After de 75s", str(failure.exception))
        self.assertIn("75", " ".join(warnings.output))
        self.assertIn("30", " ".join(warnings.output))
        sleep.assert_not_called()
        self.assertEqual(send.call_count, 1)
        self.assertEqual(router.attempts, 1)
        self.assertEqual(router.blocked, set())

    def test_retry_after_exactly_30_waits_and_retries_once(self):
        router = fake_router()
        with patch.object(ai.time, "sleep") as sleep, patch.object(
            ai, "_completion",
            side_effect=[ProviderError("gemini", "HTTP 503", retryable=True, retry_after=30),
                         sample_payload()],
        ) as send:
            router.analyze("[0:01] Docker.", "teste")
        sleep.assert_called_once_with(30)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(router.attempts, 2)

    def test_teacher_retry_after_above_cap_does_not_block_other_questions(self):
        router = fake_router()
        with patch.object(ai.time, "sleep") as sleep, patch.object(
            ai, "_teacher_completion",
            side_effect=[ProviderError("gemini", "HTTP 503", retryable=True,
                                       retry_after=90),
                         {"resposta": "resposta simulada"}],
        ) as send, self.assertLogs("knowledge_bridge.ai", level="WARNING"):
            with self.assertRaises(AllProvidersFailed):
                router.teach("Pergunta 1")
            result = router.teach("Pergunta 2")
        self.assertEqual(result.payload["resposta"], "resposta simulada")
        self.assertEqual(send.call_count, 2)
        self.assertEqual(router.attempts, 2)
        sleep.assert_not_called()

    def test_pipeline_continues_after_long_retry_after(self):
        with tempfile.TemporaryDirectory(prefix="trama-retry-after-long-") as folder:
            root = Path(folder)
            app = Application(root / "cofre-simulado", root / "sem-chave.env",
                              log=lambda *_: None)
            app.ai = fake_router()
            try:
                for number in (1, 2):
                    transcript = root / f"Aula-{number:03d}-V01.txt"
                    transcript.write_text("[0:01] A aula usa Docker.", encoding="utf-8")
                    self.assertTrue(app.add_file(transcript))
                with patch.object(ai.time, "sleep") as sleep, \
                     patch.object(ai, "_completion", side_effect=[
                         ProviderError("gemini", "HTTP 503", retryable=True,
                                       retry_after=100),
                         sample_payload(),
                     ]), self.assertLogs("knowledge_bridge.ai", level="WARNING"):
                    app.process()
                states = {s["lesson"]: s["status"]
                          for s in app.store.sources("transcript")}
                self.assertEqual(states["Aula-001"], "NEEDS_REVIEW")
                self.assertEqual(states["Aula-002"], "PUBLISHED")
                sleep.assert_not_called()
            finally:
                app.close()


class ConceptPromptTests(unittest.TestCase):
    def test_prompt_explicitly_excludes_project_application_course_and_person_names(self):
        for example in ('"Delivery App"', "projetos", "aplicações", "cursos", "pessoas"):
            self.assertIn(example, SYSTEM_INSTRUCTIONS)
        response = {
            "candidates": [{"finishReason": "STOP", "content": {
                "parts": [{"text": json.dumps(sample_payload())}],
            }}],
        }
        with patch.object(ai, "_send", return_value=response) as send:
            fake_router().analyze("[0:01] Hoje vimos o projeto Delivery App.",
                                  "aula de teste")
        sent_body = send.call_args.args[1]
        rules = sent_body["systemInstruction"]["parts"][0]["text"]
        self.assertIn('"Delivery App"', rules)
        self.assertIn('não um conceito', rules)


class ChunkExpansionTests(unittest.TestCase):
    def test_new_default_uses_one_chunk_instead_of_three_or_more(self):
        transcript = lesson_text()
        self.assertGreater(len(transcript), 23_000)
        self.assertLess(len(transcript), 40_000)
        original_chunks = chunks(transcript, max_chars=11_500)
        new_chunks = chunks(transcript)
        self.assertGreaterEqual(len(original_chunks), 3)
        self.assertEqual(len(new_chunks), 1)
        self.assertLessEqual(len(new_chunks[0]), 40_000)

    def test_app_default_remains_twelve_calls(self):
        self.assertEqual(fake_router().max_requests, 12)

    def test_isolated_batch_reports_old_vs_new_with_one_real_code_path_call(self):
        with tempfile.TemporaryDirectory(prefix="trama-chunks-40000-") as folder:
            root = Path(folder)
            inputs = root / "testes" / "aulas"
            inputs.mkdir(parents=True)
            (inputs / "Aula-131-V01.txt").write_text(lesson_text(), encoding="utf-8")
            result = {"candidates": [{"finishReason": "STOP",
                                     "content": {"parts": [
                                         {"text": json.dumps(sample_payload())}]}}],
                      "usageMetadata": {"promptTokenCount": 100,
                                        "candidatesTokenCount": 90,
                                        "thoughtsTokenCount": 0}}
            out = root / "testes" / "resultado"
            with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-only",
                                          "FREE_TIER_CONFIRMED": "YES"}), \
                 patch.object(ai, "_send", return_value=result) as calls:
                report = run(inputs, out, limite=12, pausa=0)
            self.assertEqual(calls.call_count, 1)
            self.assertEqual(len(report["trechos"]), 1)
            self.assertTrue(report["trechos"][0]["ok"])
            comparison = report["comparacao_chunks"]["Aula-131-V01"]
            self.assertGreaterEqual(comparison["antes_11500"], 3)
            self.assertEqual(comparison["agora_40000"], 1)
            markdown = (out / "relatorio_teste.md").read_text(encoding="utf-8")
            self.assertIn("### Chamadas por aula", markdown)
            self.assertIn("Trechos antes (11.500)", markdown)
            self.assertIn("Trechos agora (40.000)", markdown)
            expected = (f"| Aula-131-V01 | {comparison['antes_11500']} | "
                        "1 | 1 | 0 |")
            self.assertIn(expected, markdown)
            self.assertEqual(len(list((out / "respostas").glob("*.json"))), 1)


    def test_old_11500_character_cache_is_not_reused_for_a_40000_chunk(self):
        with tempfile.TemporaryDirectory(prefix="trama-c6-cache-layout-") as folder:
            root = Path(folder)
            transcript = root / "Aula-131-V01.txt"
            transcript.write_text(lesson_text(), encoding="utf-8")
            app = Application(root / "cofre-ficticio", root / "missing.env",
                              log=lambda *_: None)
            try:
                self.assertTrue(app.add_file(transcript))
                source = app.store.sources("transcript")[0]
                context_digest = hashlib.sha256(
                    json.dumps([], ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                old_layout_key = hashlib.sha256(
                    (source["digest"] + context_digest).encode()
                ).hexdigest()
                old_chunk = sample_payload()
                old_chunk["resumo"] = "Este era apenas o trecho antigo de 11.500."
                app.store.save_chunk(source["id"], old_layout_key, 0,
                                     "fixture", "old-layout", old_chunk)

                fresh = sample_payload()
                fresh["resumo"] = "Reprocessamento seguro da aula inteira."
                with patch.object(app.ai, "analyze",
                                  return_value=AIResult(fresh, "fixture", "offline")) as ai_call:
                    app.process()
                    self.assertEqual(ai_call.call_count, 1)
                    self.assertEqual(
                        app.store.analysis(source["id"], source["digest"])["resumo"],
                        fresh["resumo"])
                    app.process()
                    self.assertEqual(ai_call.call_count, 1,
                                     "Finished notes must not be billed again")
                self.assertEqual(app.store.get_chunk(source["id"], old_layout_key, 0),
                                 old_chunk)
            finally:
                app.close()

if __name__ == "__main__":
    unittest.main()
