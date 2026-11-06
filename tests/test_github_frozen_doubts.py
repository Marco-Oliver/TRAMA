"""Outcome tests: five real Aula 131 ASR doubts against frozen delivery-app v1.

Mocks reproduce verified source lines at d4f1fe18bd, including exact file/line
numbers. No LLM, real token, live network, or changing main branch is used.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.github_code import GithubCodeReader
from knowledge_bridge.github_mapping import GithubMapping
from knowledge_bridge.frozen_code_resolution import match_frozen_question
from knowledge_bridge.pipeline import Application
from knowledge_bridge.code_intel import index_repository

REPO = "https://github.com/academiadoprogramador-fullstack/delivery-app-2026"
FROZEN = "d4f1fe18bd398f9cf0057197a67c6b508ab4e7b3"
MAIN = "07d67e85336fb76edb237b74873ffdf8278d7c17"

CONTROLLER = "src/Api/Modulos/Clientes/ClientesController.cs"
CONFIG = "src/Infraestrutura/Orm/Config/ClienteConfiguration.cs"
JWT = "src/Api/Compartilhado/Auth/JwtProvider.cs"
DB = "src/Infraestrutura/Orm/DeliveryAppDbContext.cs"


def source_with_lines(size, values):
    lines = ["" for _ in range(size)]
    for line, value in values.items():
        lines[line - 1] = value
    return ("\n".join(lines) + "\n").encode("utf-8")


# These lines are quoted from the PUBLIC v1 SHA, not reconstructed from main.
SOURCE = {
    CONTROLLER: source_with_lines(130, {
        84: "        ",
        85: "            return Created(string.Empty, new AutenticacaoClienteResponse(",
        86: "                usuario.Id,",
        111: "        ",
        112: "        var resultadoAutenticacao = await signInManager.CheckPasswordSignInAsync(",
        113: "            usuario,",
    }),
    CONFIG: source_with_lines(33, {
        7: "",
        8: "public sealed class ClienteConfiguration : IEntityTypeConfiguration<Cliente>",
        9: "{",
    }),
    JWT: source_with_lines(48, {
        11: "",
        12: "public sealed class JwtProvider(IOptions<JwtOptions> jwtOptions)",
        13: "{",
    }),
    DB: source_with_lines(120, {
        8: "",
        9: "public sealed class DeliveryAppDbContext(",
        10: "    DbContextOptions<DeliveryAppDbContext> options,",
    }),
}


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data,
                        usedforsecurity=False).hexdigest()


class FrozenV1DoubtsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        cache = patch("knowledge_bridge.github_cache.DATA_HOME", self.folder / "cached")
        cache.start()
        self.addCleanup(cache.stop)
        self.app = Application(self.folder / "vault",
                               self.folder / "no-provider.env", log=lambda _s: None)
        self.addCleanup(self.app.close)
        self.api_calls = []
        self.raw_calls = []

        def get(_client, repo, endpoint):
            self.api_calls.append((repo, endpoint))
            self.assertEqual(repo, REPO)
            self.assertEqual(endpoint, f"git/trees/{FROZEN}?recursive=1")
            return {"truncated": False, "tree": [
                {"path": path, "mode": "100644", "type": "blob",
                 "size": len(data), "sha": git_blob(data)}
                for path, data in SOURCE.items()
            ]}

        def raw(_reader, repo, sha, path, private):
            self.raw_calls.append((repo, sha, path, private))
            self.assertEqual((repo, sha, private), (REPO, FROZEN, False))
            return SOURCE[path]

        http = patch.object(GithubMapping, "_get", get)
        blob = patch.object(GithubCodeReader, "_raw", raw)
        http.start()
        blob.start()
        self.addCleanup(http.stop)
        self.addCleanup(blob.stop)

    def _prepare(self):
        txt = self.folder / "A131 - V05 - Transcricao revisada.txt"
        txt.write_text(
            "00:04 check password saind assim\n"
            "00:25 in type configuration\n"
            "00:55 altwtider / JWT Provider\n"
            "01:21 status 2011\n"
            "02:15 DB Contact\n"
            "05:11 observação que não corresponde a nenhum identificador\n",
            encoding="utf-8",
        )
        self.app.add_file(txt)
        source = next(s for s in self.app.store.sources("transcript")
                      if s["label"] == txt.name)
        self.app.store.save_analysis(source["id"], source["digest"], "fixture", "no-ai", {
            "resumo": "Trechos de autenticação, configuração ORM, JWT e HTTP.",
            "tipo_aula": "tecnica",
            "conceitos": [
                {"nome":"DB Contact","explicacao":"Rótulo da transcrição; precisa de revisão."},
                {"nome":"DbContext","explicacao":"Contexto de dados do Entity Framework."},
            ],
            "conceitos_a_conferir": [
                {"nome":"DB Contact"}, {"nome":"Entity Framework"},
                {"nome":"migrações"},
            ],
            "duvidas": [
                "check password saind assim",
                "in type configuration",
                "altwtider / JWT Provider",
                "status 2011",
                "observação que não corresponde a nenhum identificador",
            ],
        })
        # Simulate an existing global MAIN index: it must NEVER supply
        # phonetic code evidence, even when it contains a plausible word.
        self.app.store.save_repo(
            REPO, "delivery-app-2026", MAIN, {
                "symbols": [], "evidence": [], "identifiers": [{
                    "name": "UnrelatedMainOnly",
                    "path": "src/MainOnly.cs", "line": 1, "snippet": "1: MAIN",
                    "line_text": "MAIN",
                }],
            }, "INDEXED",
        )
        ok = self.app.store.set_auto_decision(
            REPO, "Aula-131", "professor", False,
            {"sha":FROZEN,"kind":"branch","name":"v1","folder":""},
            "alta",
        )
        self.assertTrue(ok)
        return source

    def _note(self):
        folder = self.app.store.vault / "02-Minhas-Aulas" / "Aula-131"
        notes = [p for p in folder.glob("*.md") if p.name != "00-Visao-geral.md"]
        self.assertEqual(len(notes), 1)
        return notes[0].read_text(encoding="utf-8")

    def test_v05_all_five_corrected_and_unrelated_question_not_matched(self):
        self._prepare()
        self.app.publisher.rebuild()
        note = self._note()
        expected = [
            ("CheckPasswordSignInAsync", CONTROLLER, 112),
            ("IEntityTypeConfiguration", CONFIG, 8),
            ("JwtProvider", JWT, 12),
            ("Created", CONTROLLER, 85),
            ("DbContext", DB, 9),
        ]
        for name, path, line in expected:
            with self.subTest(identifier=name):
                self.assertIn(name, note)
                self.assertIn(REPO + "/blob/" + FROZEN + "/" + path +
                              "#L" + str(line), note)
                self.assertIn(str(line) + ":", note)
        self.assertGreaterEqual(note.count("Provável no código"), 5)
        self.assertIn("EXPLICADA_PELO_CODIGO", note)
        self.assertIn("nome provável no código", note.casefold())
        self.assertIn("DB Contact", note)
        self.assertNotIn("/blob/" + MAIN, note)
        self.assertIn("PENDENTE", note)

        uncertainties = {
            row["question"]: row for row in self.app.store.uncertainties_for_source(
                next(s["id"] for s in self.app.store.sources("transcript")))
        }
        for phrase in ("check password saind assim", "in type configuration",
                       "altwtider / JWT Provider", "status 2011"):
            self.assertEqual(uncertainties[phrase]["status"], "EXPLICADA_PELO_CODIGO")
        self.assertEqual(
            uncertainties["observação que não corresponde a nenhum identificador"]["status"],
            "PENDENTE",
        )
        self.assertTrue(self.raw_calls)
        self.assertTrue(all(sha == FROZEN for _repo, sha, _path, _private in self.raw_calls))
        self.assertTrue(all(FROZEN in endpoint for _repo, endpoint in self.api_calls))
        # DB Contact should share the existing DbContext concept file.
        concepts = self.app.store.vault / "01-Meu-Conhecimento" / "Conceitos"
        self.assertTrue((concepts / "dbcontext.md").exists())
        self.assertFalse((concepts / "db-contact.md").exists())
        self.assertIn("DB Contact", (concepts / "dbcontext.md").read_text(encoding="utf-8"))
        suspect = note.split("## Termos suspeitos da transcrição", 1)[1]
        self.assertNotIn("Entity Framework", suspect)
        self.assertNotIn("migrações", suspect)
        self.assertIn("CheckPasswordSignInAsync", suspect)

        target = os.getenv("TRAMA_TEST_NOTE_OUTPUT", "")
        if target:
            output = Path(target)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(note, encoding="utf-8")
            print("V05_TEST_NOTE=" + output.as_posix(), flush=True)

    def test_unrelated_phrases_never_match_even_with_code_present(self):
        payload = index_repository(Path("."), list(SOURCE), read_source=lambda p: (
            SOURCE[p].decode("utf-8"), len(SOURCE[p])))
        repo = {"url":REPO,"sha":FROZEN,"frozen":True,"version":"v1"}
        for phrase in ("status 500", "Entity Framework", "migrações",
                       "a configuração está concluída", "pagamento da entrega",
                       "só usamos uma interface no projeto"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(match_frozen_question(phrase, [(repo,payload)]))
        self.assertIsNone(match_frozen_question(
            "check password saind assim",
            [({**repo, "frozen":False, "sha":MAIN},payload)]))

    def test_no_frozen_lesson_never_uses_main_for_asr_answer(self):
        self._prepare()
        self.app.store.conn.execute(
            "DELETE FROM github_lesson_refs WHERE lesson='Aula-131'")
        self.app.store.conn.commit()
        self.app.publisher.rebuild()
        for row in self.app.store.uncertainties():
            self.assertNotEqual(row["status"], "EXPLICADA_PELO_CODIGO")
        self.assertNotIn("CheckPasswordSignInAsync", self._note())


if __name__ == "__main__":
    unittest.main()
