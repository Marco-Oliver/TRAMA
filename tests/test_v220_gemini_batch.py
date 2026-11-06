"""Network-free acceptance of live-batch report, token usage, privacy and three lessons."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge import ai
from tools.teste_gemini import run, scrub, failure_kind


def payload():
    return {"resumo": "Aula de demonstração do SDK no terminal.",
            "tipo_aula": "tecnica", "pessoas": [], "atividades": [],
            "ferramentas": [], "marcos": [], "conceitos": [],
            "exemplos": [], "duvidas": [], "nomes_a_conferir": []}


class LiveBatchScriptTests(unittest.TestCase):
    def test_offline_three_lessons_first_max_tokens_next_two_continue(self):
        with tempfile.TemporaryDirectory(prefix="trama-live-batch-") as temp:
            root = Path(temp)
            inputs = root / "testes" / "aulas"
            inputs.mkdir(parents=True)
            for number in (1, 2, 3):
                (inputs / f"Aula-{number:03d}-V01.txt").write_text(
                    "[0:01] O professor explica o SDK e o terminal.", encoding="utf-8")
            sent = []

            def fake_send(url, body, headers, provider):
                sent.append(body)
                self.assertEqual(provider, "gemini")
                self.assertIn("systemInstruction", body)
                self.assertIn("responseJsonSchema", body["generationConfig"])
                self.assertEqual(body["generationConfig"]["thinkingConfig"]["thinkingLevel"],
                                 "minimal")
                return {
                    "candidates": [{"finishReason": "MAX_TOKENS" if len(sent) == 1 else "STOP",
                                    "content": {"parts": [{"text": json.dumps(payload())}]}}],
                    "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 40,
                                      "thoughtsTokenCount": 12},
                }

            output = root / "testes" / "resultado"
            with patch.dict("os.environ", {"GEMINI_API_KEY": "fictional-API-key",
                                          "FREE_TIER_CONFIRMED": "YES"}), \
                 patch.object(ai, "_send", side_effect=fake_send):
                result = run(inputs, output, 12)
            self.assertEqual(len(result["trechos"]), 3)
            self.assertFalse(result["trechos"][0]["ok"])
            self.assertEqual(result["trechos"][0]["motivo"], "MAX_TOKENS")
            self.assertTrue(all(x["ok"] for x in result["trechos"][1:]))
            self.assertEqual(len(sent), 3)
            report = (output / "relatorio_teste.md").read_text(encoding="utf-8")
            self.assertIn("## 1. Resumo geral", report)
            self.assertIn("## 2. Tabela por aula", report)
            self.assertIn("## 3. Lista de falhas", report)
            self.assertIn("## 4. Amostras", report)
            self.assertIn("raciocínio=36", report)
            self.assertEqual(len(list((output / "respostas").glob("*.json"))), 3)
            self.assertFalse((root / "Obsidian").exists())

    def test_secret_scrubber_handles_remote_messages(self):
        secret = "example-private-test-key-1234"
        self.assertNotIn(secret, json.dumps(scrub(
            {"error": f"authorization: {secret}", "field": secret}, [secret])))

    def test_local_run_requires_explicit_free_tier(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.txt").write_text("[0:01] SDK", encoding="utf-8")
            with patch.dict("os.environ", {"GEMINI_API_KEY": "fake-key",
                                          "FREE_TIER_CONFIRMED": "NO"}):
                with self.assertRaisesRegex(ValueError, "FREE_TIER_CONFIRMED"):
                    run(root, root.parent / (root.name + "-output"), 2)


if __name__ == "__main__":
    unittest.main()
