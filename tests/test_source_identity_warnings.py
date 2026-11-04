"""Regression for source metadata vs opening transcript speech.

Only synthetic snippets, never a learner's attached TXT. No real providers,
external network, personal vault, or release publishing.
"""
import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.content import (
    lesson_identity, opening_lesson_number_mismatch, timed_lines, chunks
)
from knowledge_bridge.pipeline import Application


class SourceIdentityWarningTests(unittest.TestCase):
    def test_timed_learner_transcript_keeps_original_identity_and_flags_opening(self):
        with tempfile.TemporaryDirectory(prefix="trama-lesson-mismatch-") as folder:
            root=Path(folder)
            transcript=root/"A137 - V01 - Filas e mensageria.txt"
            raw=(
                "[0:01] Bom dia a todos.\n"
                "[0:03] Bem-vindos à nossa aulinha 136.\n"
                "[0:12] Hoje começamos mensageria e filas de mensagens.\n"
                "[1:00] Vamos conversar sobre processamento assíncrono.\n"
                "[2:10] A API recebe um pedido.\n"
                "[3:00] RabbitMQ atua como broker no exemplo.\n"
            )
            transcript.write_text(raw,encoding="utf-8")
            app=Application(root/"TRAMA-TESTE",root/"sem-chave.env",log=lambda *_:None)
            try:
                self.assertEqual(lesson_identity(transcript.name),("Aula-137","V01"))
                self.assertTrue(app.add_file(transcript))
                app.publisher.rebuild()
                registered=app.store.sources("transcript")
                self.assertEqual(len(registered),1)
                self.assertEqual(registered[0]["lesson"],"Aula-137")
                folder_note=app.store.vault/"02-Minhas-Aulas"/"Aula-137"
                overview=(folder_note/"00-Visao-geral.md").read_text(encoding="utf-8")
                note_files=[p for p in folder_note.glob("*.md")
                            if p.name!="00-Visao-geral.md"]
                self.assertEqual(len(note_files),1)
                note=note_files[0].read_text(encoding="utf-8")
                for page in (overview,note):
                    self.assertIn("Numeração",page)
                    self.assertIn("aula 136",page)
                    self.assertIn("0:03",page)
                    self.assertIn("Aula-137",page)
                self.assertFalse((app.store.vault/"02-Minhas-Aulas"/"Aula-136").exists())
                self.assertEqual(transcript.read_text(encoding="utf-8"),raw)
                self.assertEqual(timed_lines("\n".join(chunks(raw))),timed_lines(raw))
            finally:
                app.close()

    def test_first_matching_label_prevents_false_flag_from_previous_lecture(self):
        text=(
            "[0:01] Esta é a aula 137.\n"
            "[0:25] Agora recapitulamos a aula 136 de ontem.\n"
        )
        self.assertIsNone(opening_lesson_number_mismatch(text,"Aula-137"))
        self.assertEqual(opening_lesson_number_mismatch(
            "[0:01] Aulinha 136 na gravação.\n","Aula-137"),("0:01",136))

    def test_number_mentioned_long_after_opening_is_not_altered(self):
        text="[0:03] Introdução às filas.\n[4:25] Na aula 136 vimos a API.\n"
        self.assertIsNone(opening_lesson_number_mismatch(text,"Aula-137"))
        self.assertIsNone(opening_lesson_number_mismatch(text,"Aulas-Sem-Numero"))

if __name__=="__main__":
    unittest.main()
