"""Regression tests for concept identities, stored-file integrity and repo secret masking."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.ai import AIResult
from knowledge_bridge.code_intel import index_repository, redact_sensitive
from knowledge_bridge.pipeline import Application


class CriticalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = Application(self.root / "vault", self.root / "no-config.env", log=lambda _: None)
        self.addCleanup(self.app.close)

    def test_multichunk_c_sharp_and_cpp_remain_distinct(self):
        path = self.root / "Aula-001-V01.txt"
        path.write_text("[0:01] Aprendemos C, C# e C++.", encoding="utf-8")
        self.app.add_file(path)
        concepts = iter(["C", "C#", "C++", "C#"])
        def analyze(_text, _ctx):
            name = next(concepts)
            return AIResult({"resumo": name, "tipo_aula": "tecnica",
                             "conceitos": [{"nome": name, "explicacao": name, "tempo": "0:01"}]},
                            "gemini", "mock")
        self.app.ai.analyze = analyze
        with patch("knowledge_bridge.pipeline.chunks", return_value=[path.read_text(encoding="utf-8")] * 4):
            self.app.process()
        source = self.app.store.sources("transcript")[0]
        analysis = self.app.store.analysis(source["id"], source["digest"])
        self.assertEqual([x["nome"] for x in analysis["conceitos"]], ["C", "C#", "C++"])
        from knowledge_bridge.memory_atlas import make_atlas
        self.assertEqual({x["slug"] for x in make_atlas(self.app.store)["concepts"]},
                         {"c", "c-sharp", "c-plus-plus"})
        for filename in ("c.md", "c-sharp.md", "c-plus-plus.md"):
            self.assertTrue((self.app.store.vault / "01-Meu-Conhecimento" / "Conceitos" / filename).is_file())

    def test_same_size_corruption_is_rejected_without_overwrite(self):
        source = self.root / "Aula-002-V01.txt"
        source.write_bytes(b"[0:01] Original preserved")
        self.app.add_file(source)
        target = self.app.store.vault / self.app.store.sources("transcript")[0]["stored_path"]
        damaged = b"X" * source.stat().st_size
        target.write_bytes(damaged)
        with self.assertRaisesRegex(ValueError, "inconsistente"):
            self.app.add_file(source)
        self.assertEqual(target.read_bytes(), damaged)
        self.assertEqual(len(self.app.store.sources("transcript")), 1)

    def test_mutation_during_copy_cannot_register_partial_import(self):
        source = self.root / "Aula-003-V01.txt"
        source.write_bytes(b"known original content")
        from knowledge_bridge import publishing
        real_copy = publishing.shutil.copy2
        def corrupt_copy(original, target):
            result = real_copy(original, target)
            Path(target).write_bytes(b"changed during copy")
            return result
        with patch("knowledge_bridge.publishing.shutil.copy2", side_effect=corrupt_copy):
            with self.assertRaisesRegex(ValueError, "mudou durante a cópia"):
                self.app.add_file(source)
        self.assertEqual(len(self.app.store.sources()), 0)
        self.assertFalse(list((self.app.store.vault / "99-Anexos" / "Transcricoes-Originais").glob("*.txt")))

    def test_common_cloud_token_forms_and_assignments_are_masked(self):
        access = "AKIA" + "1234567890ABCDEF"
        stripe = "sk_live_" + "A" * 24
        checks = [
            ("aws_access_key_id=" + access, access),
            ("STRIPE_API_KEY = " + stripe, stripe),
            ("'api_key': 'dummykey123456789'", "dummykey123456789"),
            ('"password": "dummyPassword12345"', "dummyPassword12345"),
            ('{"clientSecret":"dummyClientSecret1234"}', "dummyClientSecret1234"),
            ("AWS_SECRET_ACCESS_KEY=dummyAwsSecret12345", "dummyAwsSecret12345"),
            ("Authorization: Bearer dummyBearerToken123456", "dummyBearerToken123456"),
            ("token: dummyunquotedtoken123", "dummyunquotedtoken123"),
        ]
        for original, secret in checks:
            with self.subTest(original=original[:20]):
                masked = redact_sensitive(original)
                self.assertNotIn(secret, masked)
                self.assertIn("[SEGREDO-OCULTO]", masked)
        self.assertEqual(redact_sensitive("class Controller { return true; }"),
                         "class Controller { return true; }")

    def test_indexed_repository_snippets_and_docs_mask_secrets(self):
        repo = self.root / "repo"
        repo.mkdir()
        access = "AKIA" + "ABCDEFGHIJKLMNOP"
        stripe = "sk_test_" + "B" * 24
        (repo / "app.cs").write_text(
            'class Controller {\n// ' + access + '\nvar token = "' + stripe + '";\n}\n',
            encoding="utf-8")
        (repo / "readme.txt").write_text(
            'config: "password": "dummySecretPassword123"\n', encoding="utf-8")
        output = index_repository(repo, ["app.cs", "readme.txt"])
        exported = str(output["evidence"]) + str(output["documentation"])
        for secret in (access, stripe, "dummySecretPassword123"):
            self.assertNotIn(secret, exported)
        self.assertIn("[SEGREDO-OCULTO]", exported)
