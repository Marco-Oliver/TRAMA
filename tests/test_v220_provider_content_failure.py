"""Regression: invalid AI content must not stop independent lessons."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.ai import AllProvidersFailed, BudgetStopped, FreeAIRouter, ProviderError
from knowledge_bridge.pipeline import Application


def result_payload():
    return {
        "resumo": "Aula de teste sobre configuração do SDK e ambiente de desenvolvimento.",
        "tipo_aula": "tecnica", "pessoas": [], "atividades": [], "ferramentas": [],
        "marcos": [], "conceitos": [], "exemplos": [], "duvidas": [],
        "nomes_a_conferir": [],
    }


def router(limit="12"):
    return FreeAIRouter({
        "FREE_TIER_CONFIRMED": "YES", "GEMINI_API_KEY": "fake-only",
        "FREE_PROVIDER_ORDER": "gemini", "MAX_REQUESTS_PER_RUN": limit,
    })


class ProviderErrorBatchRegressions(unittest.TestCase):
    def test_max_tokens_in_first_of_three_lessons_does_not_pause_batch(self):
        with tempfile.TemporaryDirectory(prefix="trama-independent-batch-") as directory:
            root = Path(directory)
            app = Application(root / "isolated-obsidian", root / "missing.env",
                              log=lambda *_: None)
            app.ai = router()
            try:
                for number in (1, 2, 3):
                    path = root / f"Aula-{number:03d}-V01.txt"
                    path.write_text(f"[0:01] Hoje o professor explica o SDK na aula {number}.",
                                    encoding="utf-8")
                    self.assertTrue(app.add_file(path))
                responses = [ProviderError("gemini", "MAX_TOKENS"), result_payload(),
                             result_payload()]
                with patch("knowledge_bridge.ai._completion", side_effect=responses) as provider:
                    app.process()
                    self.assertEqual(provider.call_count, 3)
                states = {src["lesson"]: src["status"]
                          for src in app.store.sources("transcript")}
                self.assertEqual(states, {"Aula-001": "NEEDS_REVIEW",
                                          "Aula-002": "PUBLISHED",
                                          "Aula-003": "PUBLISHED"})
                self.assertEqual(app.ai.blocked, set())
                self.assertEqual(app.ai.active(), ["gemini"])
            finally:
                app.close()

    def test_router_distinguishes_bad_content_from_exhausted_provider(self):
        agent = router()
        with patch("knowledge_bridge.ai._completion",
                   side_effect=ProviderError("gemini", "MAX_TOKENS")):
            with self.assertRaises(AllProvidersFailed):
                agent.analyze("[0:01] SDK", "offline fixture")
        self.assertEqual(agent.blocked, set())
        self.assertEqual(agent.active(), ["gemini"])

    def test_teacher_uses_the_same_failure_classification(self):
        agent = router()
        with patch("knowledge_bridge.ai._teacher_completion",
                   side_effect=ProviderError("gemini", "JSON inválido")):
            with self.assertRaises(AllProvidersFailed):
                agent.teach("Explique o SDK")

    def test_real_local_budget_still_stops_batch(self):
        agent = router(limit="1")
        with patch("knowledge_bridge.ai._completion",
                   side_effect=ProviderError("gemini", "MAX_TOKENS")):
            with self.assertRaises(BudgetStopped):
                agent.analyze("[0:01] SDK", "offline fixture")


if __name__ == "__main__":
    unittest.main()
