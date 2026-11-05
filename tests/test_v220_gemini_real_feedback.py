"""Real Gemini regressions: 503 backoff, Retry-After and literal quote grounding.

No live provider, private course material, API keys or Obsidian vault.
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
from knowledge_bridge.ai import AllProvidersFailed, BudgetStopped, FreeAIRouter, ProviderError
from knowledge_bridge.pipeline import Application
from tools.teste_gemini import inspect_result, report_markdown, run


def router(limit="20"):
    return FreeAIRouter({
        "FREE_TIER_CONFIRMED": "YES", "FREE_PROVIDER_ORDER": "gemini",
        "GEMINI_API_KEY": "fixture-not-real", "MAX_REQUESTS_PER_RUN": limit,
    })


class Http503RetryTests(unittest.TestCase):
    def test_503_retries_three_times_2_5_10_and_all_count(self):
        agent = router()
        errors = [ProviderError("gemini", "falha HTTP 503", retryable=True)] * 3
        with patch.object(ai.time, "sleep") as sleep, patch.object(
            ai, "_completion", side_effect=errors + [{"resumo": "ok", "conceitos": []}]
        ) as completion:
            answer = agent.analyze("[0:01] Mensageria.", "teste")
        self.assertEqual(answer.provider, "gemini")
        self.assertEqual(agent.attempts, 4)
        self.assertEqual(completion.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5, 10])
        self.assertEqual(agent.active(), ["gemini"])

    def test_retry_after_header_is_respected(self):
        agent = router()
        responses = [
            ProviderError("gemini", "falha HTTP 503", retryable=True, retry_after=8),
            {"resumo": "ok", "conceitos": []},
        ]
        with patch.object(ai.time, "sleep") as sleep, patch.object(
            ai, "_completion", side_effect=responses
        ):
            agent.analyze("[0:01] SDK.", "teste")
        sleep.assert_called_once_with(8)
        self.assertEqual(agent.attempts, 2)

    def test_retry_after_parsed_from_upstream_503_response(self):
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/test:generateContent"
        error = urllib.error.HTTPError(
            endpoint, 503, "busy", {"Retry-After": "7"}, io.BytesIO(b'{"error":"busy"}')
        )
        with patch.object(ai.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(ProviderError) as caught:
                ai._send(endpoint, {"contents": []}, {"x-goog-api-key": "fixture"}, "gemini")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.retry_after, 7)

    def test_teacher_uses_same_exponential_wait(self):
        agent = router()
        with patch.object(ai.time, "sleep") as sleep, patch.object(
            ai, "_teacher_completion",
            side_effect=[ProviderError("gemini", "503", retryable=True),
                         ProviderError("gemini", "503", retryable=True),
                         {"resposta": "ok"}],
        ) as completion:
            self.assertEqual(agent.teach("Mensagem").payload["resposta"], "ok")
        self.assertEqual(agent.attempts, 3)
        self.assertEqual(completion.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5])

    def test_failure_exhausts_three_retries_but_does_not_blacklist(self):
        agent = router()
        with patch.object(ai.time, "sleep") as sleep, patch.object(
            ai, "_completion", side_effect=ProviderError("gemini", "503", retryable=True)
        ) as completion:
            with self.assertRaises(AllProvidersFailed):
                agent.analyze("trecho", "contexto")
        self.assertEqual(agent.attempts, 4)
        self.assertEqual(completion.call_count, 4)
        self.assertEqual([x.args[0] for x in sleep.call_args_list], [2, 5, 10])
        self.assertEqual(agent.blocked, set())

    def test_budget_caps_retries_and_never_sleeps_after_exhaustion(self):
        agent = router(limit="2")
        with patch.object(ai.time, "sleep") as sleep, patch.object(
            ai, "_completion", side_effect=ProviderError("gemini", "503", retryable=True)
        ) as completion:
            with self.assertRaises(BudgetStopped):
                agent.analyze("trecho", "contexto")
        self.assertEqual(agent.attempts, 2)
        self.assertEqual(completion.call_count, 2)
        sleep.assert_called_once_with(2)


class GroundedConceptTests(unittest.TestCase):
    def test_literal_quote_spanning_two_timestamped_lines_is_accepted(self):
        original = (
            "[0:43] Hoje vamos falar da arquitetura baseada em eventos, tá?\n"
            "[0:46] E mensageria dentro do nosso sistema.\n"
        )
        result = Application._clean_result({
            "resumo": "Aula sobre eventos e mensagens.",
            "conceitos": [{
                "nome": "Arquitetura Baseada em Eventos e Mensageria",
                "evidencia": "arquitetura baseada em eventos, ta? E mensageria",
                "explicacao": "A fala descreve eventos e mensagens.",
                "tempo": "0:43",
            }],
        }, original)
        self.assertEqual(len(result["conceitos"]), 1)
        self.assertEqual(result["conceitos"][0]["confianca"], "citacao_literal")
        self.assertEqual(result["conceitos_a_conferir"], [])

    def test_literal_name_takes_precedence_over_quote(self):
        original = "[0:05] Hoje vamos estudar Docker."
        result = Application._clean_result({
            "conceitos": [{"nome": "Docker", "explicacao": "Ferramenta mencionada",
                           "evidencia": "citação não existente"}]
        }, original)
        self.assertEqual(result["conceitos"][0]["confianca"], "nome_literal")

    def test_short_label_sustained_by_verbatim_quote(self):
        original = "[0:10] A imagem fica dentro do contêiner.\n[0:11] E o Docker gerencia."
        result = Application._clean_result({
            "conceitos": [
                {"nome": "Imagem Docker",
                 "evidencia": "A imagem fica dentro do contêiner. E o Docker gerencia."},
                {"nome": "Docker", "evidencia": ""},
            ],
        }, original)
        self.assertEqual([x["confianca"] for x in result["conceitos"]],
                         ["citacao_literal", "nome_literal"])

    def test_asr_name_never_autocorrected_without_valid_quote(self):
        original = "[0:20] Os posts foram configurados.\n[0:22] E o Winch Framework."
        result = Application._clean_result({"conceitos": [
            {"nome": "PostgreSQL", "evidencia": "A ferramenta exata foi demonstrada"},
            {"nome": "Entity Framework Core", "evidencia": "E o Winch Framework."},
            {"nome": "RabbitMQ", "evidencia": "Uma citação inventada que não está na fonte."},
        ]}, original)
        self.assertEqual([x["nome"] for x in result["conceitos"]],
                         ["Entity Framework Core"])
        self.assertEqual(result["conceitos"][0]["confianca"], "citacao_literal")
        self.assertEqual({x["nome"] for x in result["conceitos_a_conferir"]},
                         {"PostgreSQL", "RabbitMQ"})

    def test_quote_does_not_match_if_invented_or_partial_word(self):
        original = "[0:15] Usamos Docker hoje para ver contêineres."
        result = Application._clean_result({
            "conceitos": [
                {"nome": "PostgreSQL",
                 "evidencia": "Usamos Docker ontem para ver contêineres"},
                {"nome": "Mensageria",
                 "evidencia": "Usamos Docker hoje para ver contêineres avançados."},
            ]
        }, original)
        self.assertEqual(result["conceitos"], [])
        self.assertEqual(len(result["conceitos_a_conferir"]), 2)


class ReportMetricTests(unittest.TestCase):
    def test_accepted_by_literal_name_versus_quote_and_attempt_count(self):
        text = "[0:01] Docker é usado na aula.\n[0:02] A classe filha herda os atributos."
        payload = {"resumo": "Docker e classe filha.",
                   "conceitos": [{"nome": "Docker", "evidencia": ""},
                                 {"nome": "Herança", "evidencia": "A classe filha herda os atributos."},
                                 {"nome": "PostgreSQL", "evidencia": ""}]}
        clean = Application._clean_result(payload, text)
        inspected = inspect_result(payload, clean, text)
        self.assertEqual(inspected["conceitos_por_nome"], 1)
        self.assertEqual(inspected["conceitos_por_citacao"], 1)
        self.assertEqual(inspected["conceitos_a_conferir"], 1)
        report = report_markdown({"gerado_em": "teste", "limite": 6, "trechos": [
            {"aula": "A131-V01", "trecho": 1, "ok": True, "motivo": "SUCESSO",
             "chamadas": [{"usageMetadata": {}}], "tentativas": 3,
             "novas_tentativas": 2, **inspected},
        ]})
        self.assertIn("Por nome | Por citação", report)
        self.assertIn(" | 1 | 1 | 1 | ", report)
        self.assertIn("3 (2)", report)


if __name__ == "__main__":
    unittest.main()
