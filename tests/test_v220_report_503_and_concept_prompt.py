"""Regression: Gemini compatibility is proven by ANY successful HTTP 200 attempt.

All provider/network data here is synthetic; no real free quota or vault is touched.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge import ai
from knowledge_bridge.ai import ProviderError, SYSTEM_INSTRUCTIONS
from tools.teste_gemini import report_markdown, run


def simulated_result():
    return {"resumo": "Aula fictícia de validação do cadastro.",
            "tipo_aula": "tecnica", "pessoas": [], "atividades": [],
            "ferramentas": [], "marcos": [], "conceitos": [],
            "exemplos": [], "duvidas": [], "nomes_a_conferir": []}


def http_503():
    url = "https://generativelanguage.googleapis.com/v1beta/models/mock:generateContent"
    upstream = urllib.error.HTTPError(
        url, 503, "Service Unavailable", {}, io.BytesIO(
            b'{"error":{"code":503,"message":"server overloaded"}}'))
    try:
        raise ProviderError("gemini", "falha HTTP 503", retryable=True) from upstream
    except ProviderError as error:
        return error


class GeminiReportAndConceptConsistencyTests(unittest.TestCase):
    def test_first_503_then_200_confirms_api_compatibility_and_counts_503(self):
        calls = [
            {"http_status": 503, "response": None, "api_error": {"error": "busy"}},
            {"http_status": 200, "response": {"candidates": []}, "usageMetadata": {}},
        ]
        row = {"aula": "A131-V01", "trecho": 1, "ok": True, "motivo": "SUCESSO",
               "chamadas": calls, "novas_tentativas": 1, "tentativas": 2,
               "resumo": "Aula de teste", "nomes_conceitos": [], "nomes_a_conferir": []}
        report = report_markdown({"gerado_em": "fixture", "limite": 12,
                                  "trechos": [row]})
        self.assertIn("Compatibilidade da API: confirmada", report)
        self.assertIn("Tentativas HTTP 503: 1", report)
        self.assertNotIn("compatibilidade NÃO confirmada", report)
        self.assertIn("Chamadas usadas: 2 / 12", report)

    def test_no_http_200_keeps_compatibility_unconfirmed(self):
        rows = [{"aula": "A131-V01", "trecho": 1, "ok": False,
                 "motivo": "HTTP_503", "chamadas": [
                     {"http_status": 503, "response": None},
                     {"http_status": 503, "response": None},
                 ], "erro": "service temporarily busy"}]
        report = report_markdown({"gerado_em": "fixture", "limite": 12,
                                  "trechos": rows})
        self.assertIn("Compatibilidade da API: NÃO confirmada", report)
        self.assertIn("Tentativas HTTP 503: 2", report)

    def test_report_counts_failures_across_all_chunks_not_only_first_chunk(self):
        rows = [
            {"aula": "A-1", "trecho": 1, "ok": False, "motivo": "HTTP_503",
             "chamadas": [{"http_status": 503, "response": None}]},
            {"aula": "A-2", "trecho": 1, "ok": True, "motivo": "SUCESSO",
             "chamadas": [
                 {"http_status": 503, "response": None},
                 {"http_status": 200, "response": {"candidates": []}}],
             "resumo": "Análise aprovada", "nomes_conceitos": [],
             "nomes_a_conferir": []},
        ]
        report = report_markdown({"gerado_em": "fixture", "limite": 12,
                                  "trechos": rows})
        self.assertIn("Compatibilidade da API: confirmada", report)
        self.assertIn("Tentativas HTTP 503: 2", report)

    def test_http_200_with_max_tokens_is_classified_as_content_failure(self):
        from tools.teste_gemini import failure_kind
        calls = [{"http_status": 200, "response": {"candidates": []},
                  "finishReason": "MAX_TOKENS", "erro": "MAX_TOKENS"}]
        error = ProviderError("gemini", "MAX_TOKENS")
        self.assertEqual(failure_kind(error, calls), "MAX_TOKENS")

    def test_real_diagnostic_flow_with_mocked_upstream_503_then_200(self):
        with tempfile.TemporaryDirectory(prefix="trama-gemini-503-report-") as folder:
            root = Path(folder)
            inputs = root / "aulas"
            inputs.mkdir()
            (inputs / "A131-V01.txt").write_text(
                "[0:01] O professor demonstrou validação e relacionamentos.",
                encoding="utf-8")
            responses = {
                "candidates": [{"finishReason": "STOP",
                                "content": {"parts": [
                                    {"text": json.dumps(simulated_result())}]}}],
                "usageMetadata": {"promptTokenCount": 30,
                                  "candidatesTokenCount": 20,
                                  "thoughtsTokenCount": 0},
            }
            with patch.dict("os.environ", {
                "GEMINI_API_KEY": "fixture-secret-not-to-persist-987",
                "FREE_TIER_CONFIRMED": "YES"}), patch.object(
                    ai, "_send", side_effect=[http_503(), responses]
                ) as outgoing, patch.object(ai.time, "sleep") as waiting:
                results = run(inputs, root / "output", limite=12, pausa=0)
            self.assertEqual(outgoing.call_count, 2)
            waiting.assert_called_once_with(2)
            self.assertEqual(len(results["trechos"]), 1)
            self.assertTrue(results["trechos"][0]["ok"])
            self.assertEqual(results["trechos"][0]["tentativas"], 2)
            report = (root / "output" / "relatorio_teste.md").read_text(
                encoding="utf-8")
            self.assertIn("Compatibilidade da API: confirmada", report)
            self.assertIn("Tentativas HTTP 503: 1", report)
            trace = list((root / "output" / "respostas").glob("*.json"))
            self.assertEqual(len(trace), 1)
            calls = json.loads(trace[0].read_text(encoding="utf-8"))["chamadas"]
            self.assertEqual([r.get("http_status") for r in calls], [503, 200])
            self.assertNotIn("fixture-secret-not-to-persist-987", report)
            self.assertNotIn("fixture-secret-not-to-persist-987",
                             trace[0].read_text(encoding="utf-8"))

    def test_system_prompt_matches_summarized_technical_topics_to_concepts(self):
        for required in ("Confronte o resumo", "TODO assunto", '"conceitos"',
                         "nome curto", "evidência literal", "Validação",
                         "Relacionamento um para um", '"evidencia" vazia'):
            with self.subTest(requirement=required):
                self.assertIn(required, SYSTEM_INSTRUCTIONS)
        self.assertIn("Respeite o teto de 20 conceitos", SYSTEM_INSTRUCTIONS)
        self.assertIn("nunca invente citação", SYSTEM_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
