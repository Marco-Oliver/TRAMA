"""Acceptance tests for a long, entirely INVENTED message-broker lesson.

Original privately supplied course material is NOT included in the repository.
Only generated fixture text enters this test suite. No Gemini/API requests.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.ai import AIResult
from knowledge_bridge.content import (
    chunks, suspected_technical_transcription, timed_lines,
)
from knowledge_bridge.pipeline import Application


class OfflineLessonAI:
    def __init__(self):
        self.calls=0

    def active(self):
        return ["offline-test"]

    def analyze(self, source, context):
        self.calls+=1
        return AIResult({
            "resumo": (
                "Exemplo fictício de mensageria: a API recebe solicitações, "
                "a fila desacopla o processamento e consumidores tratam os eventos. "
                "Os nomes técnicos observados na transcrição precisam ser "
                "conferidos com o áudio antes da normalização."
            ),
            "tipo_aula":"tecnica",
            "conceitos":[
                {"nome":"RabbitMQ","explicacao":"Possível broker mencionado.","tempo":"0:08"},
                {"nome":"MassTransit","explicacao":"Possível abstração de mensageria.","tempo":"0:08"},
                {"nome":"message queue","explicacao":"Possível fila de mensagens.","tempo":"0:12"},
                {"nome":"consumer","explicacao":"Consumidor de mensagens.","tempo":"0:20"},
            ],
            "pessoas":[],"atividades":[],"ferramentas":[],"marcos":[],
            "exemplos":[],"duvidas":[],"nomes_a_conferir":[],
        },"fixture-no-network","local")


def invented_transcript():
    intro=[
        "[0:01] Nossa aula é sobre filas e mensageria.",
        "[0:03] Bem-vindos à aulinha 136.",
        "[0:08] Vamos usar Rapit MQ e message transit neste exemplo.",
        "[0:12] Um message kill ajuda a separar a API e o processamento.",
        "[0:16] A resposta accepted seria HTTP 204 neste desenho de teste.",
        "[0:20] O consumer vai processar a mensagem recebida.",
    ]
    # A realistic two-chunk source with hundreds of short timestamped
    # lines; these are made-up sentences, not any user's actual transcript.
    filler=[
        f"[{i//60}:{i%60:02d}] "
        "Exemplo fictício: a API recebe pedidos e o consumidor processa "
        "a fila de eventos de modo desacoplado."
        for i in range(25,200)
    ]
    return "\n".join(intro+filler)+"\n"


class MessagingLessonAcceptanceTests(unittest.TestCase):
    def test_phonetic_hints_are_review_only_and_time_anchored(self):
        source=invented_transcript()
        hints=suspected_technical_transcription(source)
        labels={candidate:(stamp,heard) for stamp,heard,candidate in hints}
        self.assertEqual(labels["RabbitMQ"][0],"0:08")
        self.assertEqual(labels["MassTransit"][0],"0:08")
        self.assertEqual(labels["message queue"][0],"0:12")
        self.assertEqual(labels[
            "conferir HTTP 202 Accepted / HTTP 204 No Content"],
            ("0:16", "Accepted ... 204"))
        self.assertLessEqual(len(hints),8)
        self.assertEqual(len(hints),len(set(x[2] for x in hints)))
        # Correctly transcribed technical terms do not produce corrections.
        self.assertEqual(suspected_technical_transcription(
            "[0:01] RabbitMQ e MassTransit usando uma message queue.\n"),[])

    def test_offline_import_two_chunks_qa_review_notes_and_reimport(self):
        text=invented_transcript()
        self.assertEqual(len(chunks(text)),2)
        self.assertEqual(timed_lines("\n".join(chunks(text))),timed_lines(text))
        with tempfile.TemporaryDirectory(prefix="trama-messaging-acceptance-") as tmp:
            base=Path(tmp)
            original=base/"A137 - V01 - Broker fictício.txt"
            original.write_text(text,encoding="utf-8")
            vault=base/"TRAMA-TESTE"
            app=Application(vault,base/"sem-credencial.env",log=lambda *_:None)
            fake=OfflineLessonAI()
            app.ai=fake
            try:
                self.assertTrue(app.add_file(original))
                app.process()
                self.assertEqual(fake.calls,2)
                sources=app.store.sources("transcript")
                self.assertEqual(len(sources),1)
                self.assertEqual(sources[0]["status"],"PUBLISHED")
                self.assertEqual((vault/sources[0]["stored_path"]).read_text(encoding="utf-8"),text)
                folder=vault/"02-Minhas-Aulas"/"Aula-137"
                overview=(folder/"00-Visao-geral.md").read_text(encoding="utf-8")
                note=next(p for p in folder.glob("*.md") if p.name!="00-Visao-geral.md")
                content=note.read_text(encoding="utf-8")
                for field in ("Numeração da aula", "aula 136", "Aula-137"):
                    self.assertIn(field,content)
                self.assertIn("Numeração a conferir",overview)
                for term in ("Rapit MQ","RabbitMQ","message transit",
                             "MassTransit","message kill","message queue",
                             "Accepted ... 204"):
                    self.assertIn(term,content)
                self.assertIn("O áudio não foi conferido",content)
                self.assertIn("Termos sugeridos pela IA para conferir",content)
                # No unverified spelling automatically becomes a concept note.
                concept_dir=vault/"01-Meu-Conhecimento"/"Conceitos"
                self.assertFalse((concept_dir/"rabbitmq.md").exists())
                self.assertFalse((concept_dir/"masstransit.md").exists())
                self.assertTrue((concept_dir/"consumer.md").exists())
                self.assertFalse((vault/"02-Minhas-Aulas"/"Aula-136").exists())
                self.assertEqual(original.read_text(encoding="utf-8"),text)
                app.process()
                self.assertEqual(fake.calls,2)
                self.assertFalse(app.add_file(original))
                self.assertEqual(len(app.store.sources("transcript")),1)
            finally:
                app.close()

    def test_transcript_symlink_is_blocked_before_any_model_request(self):
        """Even matching bytes must not allow a symlinked catalog attachment."""
        with tempfile.TemporaryDirectory(prefix="trama-transcript-attachment-") as directory:
            base=Path(directory)
            original=base/"A137 - V01 - Teste de integridade.txt"
            original.write_text("[0:01] Um documento fictício seguro.\n",encoding="utf-8")
            app=Application(base/"cofre-isolado",base/"sem-chave.env",log=lambda *_:None)
            fake=OfflineLessonAI()
            app.ai=fake
            try:
                self.assertTrue(app.add_file(original))
                src=app.store.sources("transcript")[0]
                stored=app.store.vault/src["stored_path"]
                backup=app.store.vault/"anexo-simulacao-interno.txt"
                backup.write_bytes(stored.read_bytes())
                stored.unlink()
                try:
                    stored.symlink_to(backup)
                except (OSError,NotImplementedError):
                    self.skipTest("This Windows runner disallows symbolic links.")
                with self.assertRaisesRegex(ValueError,"caminho inseguro"):
                    app._verified_transcript(src)
                self.assertEqual(fake.calls,0)
                self.assertEqual(original.read_text(encoding="utf-8"),
                                 "[0:01] Um documento fictício seguro.\n")
            finally:
                app.close()

    def test_no_automated_fact_fix_or_technical_hints_from_unrelated_lessons(self):
        unrelated=(
            "[0:01] Estamos trabalhando com SQL e a interface da aplicação.\n"
            "[0:10] A API responde com o resultado e o aluno usa C#.\n"
        )
        self.assertEqual(suspected_technical_transcription(unrelated),[])
        self.assertNotIn("HTTP 202",unrelated)


if __name__=="__main__":
    unittest.main()
