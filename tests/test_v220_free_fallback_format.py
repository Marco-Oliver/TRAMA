"""Offline regressions for Groq and OpenRouter fallback request contracts."""
import json
import unittest
from unittest.mock import patch

from knowledge_bridge import ai


def summary():
    return {"resumo": "Resumo simulado", "conceitos": []}


class FreeFallbackRequestTests(unittest.TestCase):
    def test_json_mode_and_eight_thousand_tokens_in_both_flows(self):
        for provider in ("groq", "openrouter"):
            with self.subTest(provider=provider):
                model = ai.ALLOWED[provider][0]
                response = {"choices": [{"finish_reason": "stop",
                                         "message": {"content": json.dumps(summary())}}]}
                with patch.object(ai, "_send", return_value=response) as send:
                    self.assertEqual(ai._completion(provider, model, "fictional", "Return JSON"),
                                     summary())
                    body = send.call_args.args[1]
                    self.assertEqual(body["max_tokens"], 8000)
                    self.assertEqual(body.get("response_format"),
                                     {"type": "json_object"} if provider == "groq" else None)

                teacher_reply = {"choices": [{"finish_reason": "stop",
                                              "message": {"content": '{"resposta":"simulada"}'}}]}
                with patch.object(ai, "_send", return_value=teacher_reply) as send:
                    self.assertEqual(ai._teacher_completion(provider, model, "fictional",
                                                             "Respond as JSON"),
                                     {"resposta": "simulada"})
                    body = send.call_args.args[1]
                    self.assertEqual(body["max_tokens"], 8000)
                    self.assertEqual(body.get("response_format"),
                                     {"type": "json_object"} if provider == "groq" else None)

    def test_openrouter_free_model_id_is_retained(self):
        self.assertEqual(ai.ALLOWED["openrouter"][0], "openrouter/free")


if __name__ == "__main__":
    unittest.main()
