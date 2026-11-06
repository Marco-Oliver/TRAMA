"""Optional real-response replay. No authentic course data is committed by default."""
import json
from pathlib import Path
import unittest

from knowledge_bridge.ai import _extract_json, _gemini_text
from knowledge_bridge.pipeline import Application

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gemini_real"


class AuthorizedGeminiFixtureTests(unittest.TestCase):
    def test_authorized_successful_response_is_cleaned_without_network(self):
        files = sorted(FIXTURES.glob("*.json"))
        if not files:
            self.skipTest("Nenhuma resposta real autorizada foi adicionada.")
        record = json.loads(files[0].read_text(encoding="utf-8"))
        response = record.get("response") if isinstance(record.get("response"), dict) else None
        transcript = record.get("transcript") or ""
        if response is None:
            calls = record.get("chamadas", [])
            response = next((c.get("response") for c in calls
                             if isinstance(c.get("response"), dict)), None)
        if response is None:
            self.skipTest("A fixture ainda não contém uma resposta Gemini bem-sucedida.")
        raw = _extract_json(_gemini_text(response, "gemini"))
        clean = Application._clean_result(raw, transcript)
        self.assertIsInstance(clean["resumo"], str)
        self.assertIsInstance(clean["conceitos"], list)
        self.assertIsInstance(clean["conceitos_a_conferir"], list)


if __name__ == "__main__":
    unittest.main()
