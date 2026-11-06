"""Quality regression: names vs technical gaps, scoped re-analysis, offline notes."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from knowledge_bridge.ai import SYSTEM_INSTRUCTIONS
from knowledge_bridge.bridge import Bridge
from knowledge_bridge.content import study_windows
from knowledge_bridge.pipeline import Application


class ClassroomStudyQualityTests(unittest.TestCase):
    def test_proper_names_are_not_technical_doubts(self):
        raw = ("[0:02] Alguém chamou o professor de Thagão.\n"
               "[0:10] O comando do terminal ficou inaudível.\n")
        result = Application._clean_result({
            "resumo": "Apresentação inicial",
            "conceitos": [],
            "duvidas": ["Qual foi o comando que ele digitou?"],
            "nomes_a_conferir": ["Thagão", "Rash"],
        }, raw)
        self.assertIn("Thagão", result["nomes_a_conferir"])
        self.assertNotIn("Rash", result["nomes_a_conferir"])
        self.assertEqual(result["nomes_a_conferir"], ["Thagão"])
        self.assertNotIn("Thagão", result["duvidas"])
        self.assertEqual(len(result["duvidas"]), 1)
        self.assertIn("nomes_a_conferir", SYSTEM_INSTRUCTIONS)
        self.assertIn("comandos", SYSTEM_INSTRUCTIONS)

    def test_misclassified_model_names_do_not_become_programming_doubts(self):
        # Adversarial model response: intentionally WRONG categories.
        raw = ("[0:02] O apelido do professor é Thagão e citaram Rash.\\n"
               "[0:10] O comando mostrado no terminal ficou inaudível.\\n")
        result = Application._clean_result({
            "resumo": "Falaram de apelidos e do terminal.",
            "pessoas": [{"nome": "Thagão", "papel": "professor"}],
            "nomes_a_conferir": ["Rash"],
            "conceitos": [
                {"nome": "Rash", "explicacao": "falso conceito criado pela IA"},
                {"nome": "terminal", "explicacao": "Ambiente de comandos"}
            ],
            "duvidas": ["Thagão", "Rash?", "Qual foi o comando digitado?"],
        }, raw)
        self.assertEqual([x["nome"] for x in result["conceitos"]], ["terminal"])
        self.assertEqual(result["duvidas"], ["Qual foi o comando digitado?"])

    def test_non_ai_timeline_joins_neighboring_transcript_lines(self):
        transcript = "\n".join(
            f"[0:{i:02d}] Palavra {i} sobre SDK e terminal."
            for i in range(0, 24)
        )
        windows = study_windows(transcript, limit=4, span=4)
        self.assertEqual(len(windows), 4)
        self.assertEqual(windows[0][0], "0:00")
        self.assertIn("Palavra 0", windows[0][1])
        self.assertIn("Palavra 1", windows[0][1])
        self.assertNotIn("Palavra 20", windows[0][1])
        self.assertLessEqual(len(windows[0][1]), 440)

    def test_no_fabricated_timestamp_when_transcript_has_none(self):
        self.assertEqual(study_windows("Hoje falamos de dotnet sem horários"), [])


class ScopedReanalysisTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.vault = Path(self.folder.name)/"vault"
        self.vault.mkdir()
        self.bridge = Bridge()
        self.bridge.settings = {"vault": str(self.vault), "confirmed_free": True}

    def test_scoped_reanalysis_reuses_only_requested_lesson(self):
        app = Mock()
        app.store.sources.return_value = [
            {"lesson": "Aula-002", "status": "PUBLISHED"},
            {"lesson": "Aula-003", "status": "READY"}
        ]
        with patch.object(self.bridge._key_vault, "configured",
                          return_value={"gemini": True}), \
             patch.object(self.bridge, "_make_application", return_value=app):
            answer = self.bridge.process_lesson("Aula-002", True, True)
        self.assertTrue(answer["ok"], answer)
        app.process.assert_called_once_with(lesson_filter="Aula-002", force=True)
        app.close.assert_called_once()
        self.assertFalse(self.bridge._write_lock.locked())

    def test_pending_lesson_resumes_with_cached_chunks_instead_of_forcing_all(self):
        app = Mock()
        app.store.sources.return_value = [
            {"lesson":"Aula-002", "status":"PUBLISHED"},
            {"lesson":"Aula-003", "status":"READY"},
        ]
        with patch.object(self.bridge._key_vault, "configured",
                          return_value={"gemini":True}), \
             patch.object(self.bridge, "_make_application", return_value=app):
            answer=self.bridge.process_lesson("Aula-002", True)
        self.assertTrue(answer["ok"], answer)
        app.process.assert_called_once_with(lesson_filter="Aula-002",force=False)

    def test_actual_provider_error_categorized_instead_of_guessed_quota(self):
        waiting=[{"lesson":"Aula-002","status":"WAITING_FOR_PROVIDER"}]
        reply=self.bridge._processing_feedback(
            waiting,["Analisando A02", "Pausado sem cobrança: "
                     "Todos os provedores falharam ou atingiram cotas: "
                     "gemini: resposta estruturada inválida; nada será publicado"])
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["reason"],"invalid_ai_response")
        self.assertNotIn("cota da API",reply["message"])
        self.assertEqual(reply["pending"],1)
        quota=self.bridge._processing_feedback(
            waiting,["Pausado sem cobrança: "
                     "gemini: limite gratuito atingido (429)"])
        self.assertEqual(quota["reason"],"api_quota")
        self.assertIn("429",quota["message"])
        local=self.bridge._processing_feedback(
            waiting,["Pausado sem cobrança: "
                     "Limite de segurança de requisições por execução atingido"])
        self.assertEqual(local["reason"],"local_limit")
        self.assertIn("limite local",local["message"])

    def test_global_generate_reports_partial_failure_and_saves_progress(self):
        app=Mock()
        app.store.sources.return_value=[
            {"lesson":"Aula-002", "status":"PUBLISHED"},
            {"lesson":"Aula-002", "status":"WAITING_FOR_PROVIDER"},
        ]
        def interrupted_process():
            logs.append("Pausado sem cobrança: Limite de segurança de requisições por execução atingido")
        logs=[]
        def create_app(_vault, log):
            def interrupt():
                log("Pausado sem cobrança: Limite de segurança de requisições por execução atingido")
            app.process.side_effect=interrupt
            return app
        with patch.object(self.bridge, "_make_application", side_effect=create_app):
            result=self.bridge.process(True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"],"local_limit")
        self.assertEqual(result["pending"],1)
        app.close.assert_called_once()

    def test_consent_and_lesson_id_are_required(self):
        with patch.object(self.bridge, "_make_application",
                          side_effect=AssertionError("Should not start processing")):
            self.assertFalse(self.bridge.process_lesson("Aula-002", False)["ok"])
            self.assertFalse(self.bridge.process_lesson("../private", True)["ok"])
        self.assertFalse(self.bridge._write_lock.locked())

    def test_missing_key_never_starts_processing(self):
        with patch.object(self.bridge._key_vault, "configured",
                          return_value={"gemini": False, "groq": False}), \
             patch.object(self.bridge, "_make_application",
                          side_effect=AssertionError("No configured key")):
            result = self.bridge.process_lesson("Aula-002", True)
        self.assertFalse(result["ok"])
        self.assertIn("chave", result["message"].lower())

    def test_provider_failure_does_not_leave_lock_held(self):
        app = Mock()
        app.store.sources.return_value = [
            {"lesson": "Aula-002", "status": "READY"}
        ]
        app.process.side_effect = RuntimeError("token=secret123")
        with patch.object(self.bridge._key_vault, "configured",
                          return_value={"gemini": True}), \
             patch.object(self.bridge, "_make_application", return_value=app):
            result = self.bridge.process_lesson("Aula-002", True)
        self.assertFalse(result["ok"])
        self.assertNotIn("secret123", str(result))
        self.assertFalse(self.bridge._write_lock.locked())
        app.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
