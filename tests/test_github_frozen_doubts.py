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
        16: "    DeliveryAppDbContext dbContext,",
        17: "    UserManager<IdentityUser<Guid>> userManager,",
        18: "    SignInManager<IdentityUser<Guid>> signInManager,",
        19: "    RoleManager<IdentityRole<Guid>> roleManager,",
        20: "    JwtProvider jwtProvider",
        84: "        ",
        85: "            return Created(string.Empty, new AutenticacaoClienteResponse(",
        86: "                usuario.Id,",
        106: "    {",
        107: "        var usuario = await userManager.FindByEmailAsync(request.Email.Trim());",
        108: "",
        111: "        ",
        112: "        var resultadoAutenticacao = await signInManager.CheckPasswordSignInAsync(",
        113: "            usuario,",
    }),
    CONFIG: source_with_lines(33, {
        7: "",
        8: "public sealed class ClienteConfiguration : IEntityTypeConfiguration<Cliente>",
        14: "        builder.HasKey(c => c.Id);",
        15: "        builder.Property(c => c.Id).ValueGeneratedNever();",
        16: "",
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
    "src/Api/Erros/ProblemDetailsTypes.cs": source_with_lines(18, {
        1: "namespace DeliveryApp.Api.Erros;",
        2: "public static class ProblemDetailsTypes",
        3: "{",
        5: '    public const string About = "https://example.org/types/Reference";',
        6: "}",
    }),
    "src/Api/Modulos/Clientes/AuthModel.cs": source_with_lines(22, {
        1: "using Microsoft.IdentityModel.Tokens;",
        2: "namespace DeliveryApp.Api.Modulos.Clientes;",
        3: "public class AuthModel",
        4: "{",
        5: "    public bool EstaAutenticado { get; set; }",
        6: "}",
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
            "03:00 sain in manager\n"
            "03:15 rói manager\n"
            "03:30 faind bai email\n"
            "03:45 user maneger\n"
            "04:00 valor generated never\n"
            "05:11 observação que não corresponde a nenhum identificador\n"
            "06:00 Grafia de ‘brotce’ ou ‘brute force’?\n",
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
                {"nome":"Autenticação","explicacao":"Conceito português correto."},
                {"nome":"Geração de token","explicacao":"Conceito português correto."},
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
                "sain in manager",
                "rói manager",
                "faind bai email",
                "user maneger",
                "valor generated never",
                "Grafia de ‘brotce’ ou ‘brute force’?",
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
            ("SignInManager", CONTROLLER, 18),
            ("RoleManager", CONTROLLER, 19),
            ("FindByEmailAsync", CONTROLLER, 107),
            ("UserManager", CONTROLLER, 17),
            ("ValueGeneratedNever", CONFIG, 15),
        ]
        for name, path, line in expected:
            with self.subTest(identifier=name):
                self.assertIn(name, note)
                self.assertIn(REPO + "/blob/" + FROZEN + "/" + path +
                              "#L" + str(line), note)
                self.assertIn(str(line) + ":", note)
        # One actual evidence block per phrase; no duplicates in other
        # sections, even for DB Contact -> DbContext.
        self.assertEqual(note.count("**Provável no código:**"), 9)
        doubts = note.split("## Dúvidas técnicas e passagens inaudíveis",1)[1]
        doubts = doubts.split("\n## ",1)[0]
        self.assertEqual(doubts.count("**Provável no código:**"), 9)
        self.assertEqual(note.count("**Trecho de 3 linhas do commit congelado:**"), 9)
        self.assertIn("EXPLICADA_PELO_CODIGO", note)
        self.assertIn("Dúvidas relacionadas a identificadores concretos da versão congelada", note)
        self.assertNotIn("*Nenhum vínculo com código encontrado ainda.", note)
        followup = note.split("### check password saind assim",1)[1].split("\n### ",1)[0]
        self.assertIn("ver dúvida técnica acima", followup)
        self.assertNotIn("**Provável no código:**", followup)
        self.assertNotIn("Nenhuma explicação posterior identificada", followup)
        self.assertEqual(note.count("**Nome provável no código:**"), 1)
        self.assertIn("DB Contact", note)
        # Keep unescaped generic type parameters in real fenced C# excerpts.
        self.assertIn("IEntityTypeConfiguration<Cliente>", note)
        self.assertIn("JwtProvider(IOptions<JwtOptions>", note)
        self.assertNotIn("IEntityTypeConfiguration&lt;Cliente&gt;", note)
        self.assertIn("```csharp", doubts)
        knowledge = note.split("## Conhecimentos relacionados",1)[1].split("\n## ",1)[0]
        self.assertEqual(knowledge.count("[[dbcontext|DbContext]]"), 1)
        self.assertNotIn("[[dbcontext|DB Contact]]", knowledge)
        self.assertNotIn("[[db-contact|DB Contact]]", knowledge)
        self.assertIn("[[autenticacao|Autenticação]]", knowledge)
        self.assertIn("[[geracao-de-token|Geração de token]]", knowledge)
        self.assertNotIn("EstaAutenticado", doubts)
        self.assertNotIn("Tokens", doubts)
        self.assertNotIn("Reference", doubts)
        self.assertNotIn("Autenticação — **Estado:**", note)
        self.assertNotIn("Geração de token — **Estado:**", note)
        self.assertNotIn("DB Contact — **Estado:**", note)
        self.assertIn("Grafia de ‘brotce’ ou ‘brute force’? — **Estado:** `PENDENTE`", note)
        self.assertNotIn("/blob/" + MAIN, note)
        self.assertIn("PENDENTE", note)

        uncertainties = {
            row["question"]: row for row in self.app.store.uncertainties_for_source(
                next(s["id"] for s in self.app.store.sources("transcript")))
        }
        for phrase in ("check password saind assim", "in type configuration",
                       "altwtider / JWT Provider", "status 2011",
                       "sain in manager", "rói manager", "faind bai email",
                       "user maneger", "valor generated never"):
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
        self.assertIn("Dúvidas técnicas e passagens inaudíveis acima", suspect)
        self.assertNotIn("**Provável no código:**", suspect)
        self.assertNotIn("/blob/" + FROZEN, suspect)

        target = os.getenv("TRAMA_TEST_NOTE_OUTPUT", "")
        if target:
            output = Path(target)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(note, encoding="utf-8")
            print("V05_TEST_NOTE=" + output.as_posix(), flush=True)

    def test_real_false_positives_are_not_code_evidence(self):
        payload = index_repository(Path("."), list(SOURCE), read_source=lambda p: (
            SOURCE[p].decode("utf-8"), len(SOURCE[p])))
        names = {item["name"] for item in payload["identifiers"]}
        self.assertNotIn("Reference", names)  # only inside a URL string
        self.assertNotIn("Tokens", names)  # only in a using directive
        repo = {"url":REPO, "sha":FROZEN, "frozen":True, "version":"v1"}
        for question in (
            "Grafia de ‘brotce’ ou ‘brute force’? A IA mencionou Reference",
            "brute force", "brotce", "Autenticação", "Geração de token",
        ):
            with self.subTest(question=question):
                self.assertIsNone(match_frozen_question(question, [(repo,payload)]))
        # Quoted payload, not the narrative or accidental code word outside.
        from knowledge_bridge.frozen_code_resolution import focus_question
        self.assertEqual(focus_question(
            "Grafia de ‘brotce’ ou ‘brute force’? Talvez Reference"),
            "brotce brute force")

    def test_unrelated_phrases_never_match_even_with_code_present(self):
        payload = index_repository(Path("."), list(SOURCE), read_source=lambda p: (
            SOURCE[p].decode("utf-8"), len(SOURCE[p])))
        repo = {"url":REPO,"sha":FROZEN,"frozen":True,"version":"v1"}
        for phrase in (
            "o professor usou o manager de usuário",
            "vamos fazer uma revisão",
            "a pasta de configuração",
            "não sei por que está falhando",
            "a aula terminou cedo hoje",
            "o controller tem uma classe pública",
            "fizemos mudanças no projeto",
            "vamos subir o código na branch",
            "o formulário de cadastro de pessoas",
            "a configuração da interface precisa mudar",
            "status 500", "Entity Framework", "migrações",
            "a configuração está concluída", "pagamento da entrega",
            "só usamos uma interface no projeto",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(match_frozen_question(phrase, [(repo,payload)]))
        self.assertIsNone(match_frozen_question(
            "check password saind assim",
            [({**repo, "frozen":False, "sha":MAIN},payload)]))

    def test_generic_pt_br_phonetics_on_real_v1_identifiers(self):
        payload = index_repository(Path("."), list(SOURCE), read_source=lambda p: (
            SOURCE[p].decode("utf-8"), len(SOURCE[p])))
        frozen = {"url":REPO, "sha":FROZEN, "frozen":True, "version":"v1"}
        cases = {
            "sain in manager":"SignInManager",
            "rói manager":"RoleManager",
            "faind bai email":"FindByEmailAsync",
            "user maneger":"UserManager",
            "valor generated never":"ValueGeneratedNever",
            "check password saind assim":"CheckPasswordSignInAsync",
            "in type configuration":"IEntityTypeConfiguration",
            "altwtider / JWT Provider":"JwtProvider",
            "DB Contact":"DbContext",
            "status 2011":"Created",
        }
        for heard, expected in cases.items():
            with self.subTest(heard=heard):
                match = match_frozen_question(heard, [(frozen, payload)])
                self.assertIsNotNone(match, heard)
                self.assertEqual(match["candidate"], expected)
                self.assertEqual(match["sha"], FROZEN)

    def test_later_question_reads_only_the_later_lesson_frozen_version(self):
        from knowledge_bridge.learning_review import refresh_uncertainties
        from knowledge_bridge.code_intel import index_repository
        import json
        self._prepare()
        followup = self.folder / "A132 - V01 - Retomada.txt"
        followup.write_text("00:10 Revisitamos CheckPasswordSignInAsync.\\n",
                            encoding="utf-8")
        self.app.add_file(followup)
        index = index_repository(
            Path("."), list(SOURCE), read_source=lambda path: (
                SOURCE[path].decode("utf-8"), len(SOURCE[path])))
        next_sha = "6" * 40

        class IndexedPerLesson:
            def __init__(self):
                self.requests = []
            def for_lesson(self, lesson):
                self.requests.append(lesson)
                if lesson == "Aula-131":
                    # Deliberate MAIN data must never resolve this doubt.
                    return [({"url":REPO,"sha":MAIN,"frozen":False},index)]
                if lesson == "Aula-132":
                    return [({"url":REPO,"sha":next_sha,"frozen":True,
                              "version":"v2"},index)]
                return []

        scoped = IndexedPerLesson()
        refresh_uncertainties(self.app.store, scoped)
        row = next(item for item in self.app.store.uncertainties()
                   if item["question"] == "check password saind assim")
        self.assertEqual(row["status"], "EXPLICADA_PELO_CODIGO")
        evidence = json.loads(row["evidence_json"])
        self.assertEqual(evidence[0]["sha"], next_sha)
        self.assertEqual(evidence[0]["lesson"], "Aula-132")
        self.assertEqual(evidence[0]["candidate"], "CheckPasswordSignInAsync")
        self.assertIn("Aula-132", scoped.requests)
        self.assertNotIn(MAIN, row["evidence_json"])

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
