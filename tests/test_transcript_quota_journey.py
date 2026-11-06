"""End-to-end quota QA with near-hourly synthetic transcripts, no Gemini access.

Exercises actual AI router, local 12-request cap, cached continuation,
per-project 429 handling, no source deletion and no double calls.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from knowledge_bridge.ai import FreeAIRouter, ProviderError
from knowledge_bridge.content import chunks
from knowledge_bridge.pipeline import Application


def classroom_sized_transcript() -> str:
    # 60 timestamped minutes of invented teaching; ~80k characters.
    return "\n".join(
        f"[{minute}:00] O professor explica o SDK e demonstra o programa no terminal. "
        + "Este exemplo é hipotético e repetido somente para testar o tamanho. " * 25
        for minute in range(60)
    )


def offline_result():
    return {
        "resumo": "Aula de teste fictícia sobre SDK, ferramentas do curso e terminal. "
                  "O processamento é simulado sem contato com serviços externos.",
        "tipo_aula": "tecnica",
        "pessoas": [],
        "atividades": [],
        "ferramentas": [],
        "marcos": [],
        "conceitos": [],
        "exemplos": [],
        "duvidas": [],
        "nomes_a_conferir": [],
    }


def router():
    return FreeAIRouter({
        "FREE_TIER_CONFIRMED":"YES",
        "GEMINI_API_KEY":"local-fake-key-never-sent",
        "FREE_PROVIDER_ORDER":"gemini",
        "MAX_REQUESTS_PER_RUN":"12",
    })


class CourseQuotaJourneyTests(unittest.TestCase):
    def test_hourlong_text_chunking_is_estimated_from_real_chunker(self):
        text=classroom_sized_transcript()
        pieces=chunks(text)
        self.assertGreater(len(text),60_000)
        self.assertGreaterEqual(len(pieces),2)
        self.assertLessEqual(len(pieces),4)
        self.assertTrue(all(0<len(piece)<=40_000 for piece in pieces))
        self.assertLess(len(pieces),len(chunks(text,max_chars=11_500)))
        # One call per uncached chunk, not one call per entire recording.
        self.assertEqual(len(pieces),len(chunks(text)))

    def test_twelve_call_budget_and_restart_reuses_all_successful_segments(self):
        with tempfile.TemporaryDirectory(prefix="trama-budget-hourlong-") as directory:
            base=Path(directory)
            original=classroom_sized_transcript()
            inputs=[]
            # More characters per chunk means more lessons are needed to
            # exhaust twelve calls; keep the resume/budget assertion intact.
            chunks_per_lesson=len(chunks(original))
            lesson_count=12//chunks_per_lesson+1
            for number in range(1,lesson_count+1):
                path=base/f"Aula-{number:03d}-V01.txt"
                path.write_text(original,encoding="utf-8")
                inputs.append(path)
            expected_chunks=lesson_count*chunks_per_lesson
            self.assertGreater(expected_chunks,12)
            vault=base/"cofre-isolado"
            first=Application(vault,base/"sem-chave.env",log=lambda *_:None)
            first.ai=router()
            with patch("knowledge_bridge.ai._completion",return_value=offline_result()) as fake:
                try:
                    for path in inputs:
                        self.assertTrue(first.add_file(path))
                    first.process()
                    self.assertEqual(fake.call_count,12)
                    states=[s["status"] for s in first.store.sources("transcript")]
                    self.assertEqual(states.count("PUBLISHED"),12//chunks_per_lesson)
                    self.assertEqual(states.count("WAITING_FOR_PROVIDER"),1)
                    completed=first.store.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
                    self.assertEqual(completed,12)
                finally:
                    first.close()
            resumed=Application(vault,base/"sem-chave.env",log=lambda *_:None)
            resumed.ai=router()
            with patch("knowledge_bridge.ai._completion",return_value=offline_result()) as fake:
                try:
                    resumed.process()
                    self.assertEqual(fake.call_count,expected_chunks-12)
                    self.assertTrue(all(s["status"]=="PUBLISHED"
                                        for s in resumed.store.sources("transcript")))
                    self.assertEqual(resumed.store.conn.execute(
                        "SELECT COUNT(*) FROM chunks").fetchone()[0],expected_chunks)
                    resumed.process()
                    self.assertEqual(fake.call_count,expected_chunks-12)
                    self.assertTrue((vault/"02-Minhas-Aulas/Aula-001/00-Visao-geral.md").is_file())
                    self.assertTrue((vault/f"02-Minhas-Aulas/Aula-{lesson_count:03d}/00-Visao-geral.md").is_file())
                finally:
                    resumed.close()
            for path in inputs:
                self.assertEqual(path.read_text(encoding="utf-8"),original)

    def test_free_quota_429_marks_pending_and_retries_after_restart_not_in_loop(self):
        with tempfile.TemporaryDirectory(prefix="trama-429-resume-") as directory:
            base=Path(directory)
            vault=base/"vault-only-test"
            originals={}
            first=Application(vault,base/"no-token.env",log=lambda *_:None)
            first.ai=router()
            try:
                for n in (3,4):
                    path=base/f"Aula-{n:03d}-V01.txt"
                    path.write_text(f"[0:04] Hoje mostramos SDK e ferramentas da aula {n}.\n",
                                    encoding="utf-8")
                    originals[path.name]=path.read_bytes()
                    self.assertTrue(first.add_file(path))
                with patch("knowledge_bridge.ai._completion",
                           side_effect=ProviderError("gemini","429 simulated",quota=True)) as fake:
                    first.process()
                    self.assertEqual(fake.call_count,1,"Never retry a blocked quota in a loop.")
                    self.assertEqual(sum(s["status"]=="WAITING_FOR_PROVIDER"
                                         for s in first.store.sources("transcript")),1)
                    self.assertEqual(sum(s["status"]=="READY"
                                         for s in first.store.sources("transcript")),1)
            finally:
                first.close()
            second=Application(vault,base/"no-token.env",log=lambda *_:None)
            second.ai=router()
            with patch("knowledge_bridge.ai._completion",return_value=offline_result()) as fake:
                try:
                    second.process()
                    self.assertEqual(fake.call_count,2)
                    self.assertTrue(all(s["status"]=="PUBLISHED"
                                        for s in second.store.sources("transcript")))
                    second.process()
                    self.assertEqual(fake.call_count,2)
                finally:
                    second.close()
            for name,content in originals.items():
                self.assertEqual((base/name).read_bytes(),content)


if __name__=="__main__":
    unittest.main()
