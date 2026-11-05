"""Stage 1 GitHub lesson mapping contract: offline, deterministic, no real API calls."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.bridge import Bridge, load_local_ui
from knowledge_bridge.github_mapping import GithubMapping, preview_mapping
from knowledge_bridge.lesson_code_config import read_config, save_lessons, validate_lesson, lesson_dates
from knowledge_bridge.store import Store


PROFESSOR = {
    "id": "backend", "rotulo": "Professor - API",
    "repo": "https://github.com/exemplo/api",
    "ref_tipo": "branch", "ref": "main", "pasta": "V3",
}
FRONT = {
    "id": "frontend", "rotulo": "Professor - Front",
    "repo": "https://github.com/exemplo/web",
    "ref_tipo": "tag", "ref": "v3", "pasta": "",
}
DUPLA = {
    "id": "dupla-backend", "rotulo": "Dupla - API",
    "repo": "https://github.com/dupla/api",
    "ref_tipo": "commit", "ref": "a"*40,
    "pasta": "", "professor_id": "backend",
}


class LessonCodeConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / "cofre"
        self.vault.mkdir()
        self.path = self.vault / ".base-conhecimento" / "aulas-github.json"

    def lesson(self):
        return {"professor": [dict(PROFESSOR), dict(FRONT)], "dupla": [dict(DUPLA)]}

    def test_two_teacher_repos_one_pair_atomic_save_and_reload(self):
        saved = save_lessons(self.vault, {"Aula-131": self.lesson()})
        self.assertTrue(saved["ok"])
        loaded = read_config(self.vault)
        self.assertEqual(loaded["erros"], [])
        self.assertEqual(len(loaded["aulas"]["Aula-131"]["professor"]), 2)
        self.assertEqual(len(loaded["aulas"]["Aula-131"]["dupla"]), 1)
        self.assertEqual(loaded["aulas"]["Aula-131"]["dupla"][0]["professor_id"], "backend")
        self.assertFalse(list(self.path.parent.glob(".aulas-github-*")))
        self.assertNotIn("TRAMA_GITHUB_TOKEN", self.path.read_text(encoding="utf-8"))

    def test_unrelated_legacy_lesson_is_preserved(self):
        save_lessons(self.vault, {"Aula-002": {"professor": [dict(PROFESSOR)], "dupla": []}})
        save_lessons(self.vault, {"Aula-131": self.lesson()})
        self.assertIn("Aula-002", read_config(self.vault)["aulas"])

    def test_invalid_lesson_does_not_block_other_valid_lessons(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"schema": 1, "aulas": {
            "Aula-001": {"professor": [dict(PROFESSOR)], "dupla": []},
            "Aula-002": {"professor": [dict(PROFESSOR, repo="https://evil.test/a/b")], "dupla": []},
        }}), encoding="utf-8")
        loaded = read_config(self.vault)
        self.assertFalse(loaded["fatal"])
        self.assertIn("Aula-001", loaded["aulas"])
        self.assertNotIn("Aula-002", loaded["aulas"])
        self.assertTrue(any("Aula-002" in issue and "repo" in issue for issue in loaded["erros"]))
        save_lessons(self.vault, {"Aula-003": {"professor": [], "dupla": []}})
        self.assertIn("Aula-002", json.loads(self.path.read_text())["aulas"])

    def test_syntactically_invalid_json_remains_untouched(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        original = b'{"schema":1,"aulas":{BROKEN'
        self.path.write_bytes(original)
        loaded = read_config(self.vault)
        self.assertTrue(loaded["fatal"])
        with self.assertRaises(ValueError):
            save_lessons(self.vault, {"Aula-131": self.lesson()})
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_fields_and_tokens_in_urls_rejected(self):
        for url in (
            "https://github.com/u/r?token=secret",
            "https://token@github.com/u/r",
            "https://evil.example/u/r",
        ):
            with self.subTest(url=url):
                bad = self.lesson()
                bad["professor"][0]["repo"] = url
                errors = validate_lesson("Aula-131", bad)
                self.assertTrue(any(".repo:" in x for x in errors), errors)
        bad = self.lesson()
        bad["professor"][0]["github_token"] = "sensitive"
        self.assertTrue(validate_lesson("Aula-131", bad))

    def test_optional_previous_is_valid_and_never_inferred(self):
        data = self.lesson()
        self.assertNotIn("anterior", data["professor"][0])
        self.assertEqual(validate_lesson("Aula-131", data), [])
        data["professor"][0]["anterior"] = {"ref_tipo": "commit", "ref": "b"*40, "pasta": "V2"}
        self.assertEqual(validate_lesson("Aula-131", data), [])
        bad = self.lesson()
        bad["professor"][0]["anterior"] = {"ref_tipo": "branch", "ref": "main", "pasta": "../secrets"}
        self.assertTrue(any("anterior" in s for s in validate_lesson("Aula-131", bad)))

    def test_duplicate_and_unknown_teacher_references(self):
        data = self.lesson()
        data["professor"].append(dict(PROFESSOR))
        self.assertTrue(any("duplicado" in issue for issue in validate_lesson("Aula-131", data)))
        data = self.lesson()
        data["dupla"][0]["professor_id"] = "inexistente"
        self.assertTrue(any("professor_id" in issue for issue in validate_lesson("Aula-131", data)))

    def test_no_credentials_are_accepted_in_json(self):
        data = self.lesson()
        data["dupla"][0]["token"] = "ghp_fake_secret"
        issues = validate_lesson("Aula-131", data)
        self.assertTrue(issues)

    def test_dates_without_context_remain_unknown(self):
        db = Store(self.vault)
        self.addCleanup(db.close)
        db.upsert_source({"id":"001", "kind":"transcript", "original_path":"x",
                          "digest":"d", "label":"Aula-001-V01.txt", "lesson":"Aula-001",
                          "video":"V01", "stored_path":"x"})
        self.assertEqual(lesson_dates(self.vault)[0]["data"], "")

    def test_classroom_date_is_not_claimed_as_recording_date(self):
        db = Store(self.vault)
        self.addCleanup(db.close)
        db.upsert_source({"id":"001", "kind":"classroom", "original_path":"classroom:001",
                          "digest":"d", "label":"Contexto", "lesson":"Aula-001",
                          "video":"", "stored_path":"contexto.json"})
        folder = self.vault / "99-Anexos" / "Contexto-Classroom"
        folder.mkdir(parents=True)
        (folder / "Aula-001.json").write_text('{"data":"03/11/2026"}', encoding="utf-8")
        row = lesson_dates(self.vault)[0]
        self.assertEqual(row["data"], "2026-11-03")
        self.assertEqual(row["origem_data"], "contexto_classroom")


class MappingSuggestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)
        db = Store(self.vault)
        db.upsert_source({"id":"131", "kind":"classroom", "original_path":"classroom:131",
                          "digest":"d", "label":"Aula-131", "lesson":"Aula-131",
                          "video":"", "stored_path":"contexto.json"})
        db.close()
        folder = self.vault / "99-Anexos" / "Contexto-Classroom"
        folder.mkdir(parents=True)
        (folder / "Aula-131.json").write_text('{"data":"04/11/2026"}', encoding="utf-8")
        self.repo = "https://github.com/exemplo/api"
        self.sha = "a"*40
        self.other = "b"*40
        self.payloads = {
            "commits?per_page=100": [
                {"sha":self.sha,"commit":{"message":"V3", "committer":{"date":"2026-11-03T15:00:00Z"}}},
                {"sha":self.other,"commit":{"message":"V2", "committer":{"date":"2026-10-25T15:00:00Z"}}}
            ],
            "tags?per_page=100": [{"name":"v3","commit":{"sha":self.sha}}],
            f"git/trees/{self.sha}?recursive=1": {"tree":[
                {"type":"tree","path":"V3"},
                {"type":"tree","path":"V2"},
                {"type":"blob","path":"V3/src/app.cs"}
            ], "truncated":False},
        }

    def test_git_trees_is_one_recursive_request_and_no_writes(self):
        received = []
        def mocked(_self, repo, endpoint):
            self.assertEqual(repo, self.repo)
            received.append(endpoint)
            return self.payloads[endpoint]
        with patch.object(GithubMapping, "_get", mocked):
            preview = preview_mapping(self.vault, self.repo)
        self.assertEqual(len(received), 3)
        self.assertEqual(received.count(f"git/trees/{self.sha}?recursive=1"), 1)
        self.assertTrue(any(x["tipo"]=="pasta" and x["pasta"]=="V3"
                            for x in preview["candidatos"]))
        self.assertTrue(preview["aulas"][0]["candidato_id"])
        self.assertFalse((self.vault/".base-conhecimento"/"aulas-github.json").exists())

    def test_optional_previous_is_a_suggestion_only(self):
        with patch.object(GithubMapping, "_get", side_effect=lambda repo, endpoint:self.payloads[endpoint]):
            catalog = GithubMapping().catalogue(self.repo)
        folder = next(x for x in catalog["candidatos"] if x["tipo"]=="pasta" and x["pasta"]=="V3")
        self.assertEqual(folder["sugestao_anterior"]["pasta"], "V2")
        self.assertFalse((self.vault/".base-conhecimento"/"aulas-github.json").exists())

    def test_missing_date_gives_no_guess(self):
        rows = GithubMapping.suggestions({"candidatos":[{"id":"commit:any","data":"2026-11-03"}]},
                                         [{"aula":"Aula-011","data":"","origem_data":"nao_informada"}])
        self.assertEqual(rows[0]["candidato_id"], "")


class MappingBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault=Path(self.temp.name)
        self.bridge=Bridge()
        self.bridge.settings={"vault": str(self.vault)}

    def test_bulk_requires_preview_and_confirmation(self):
        sel=[{"aula":"Aula-131","candidato_id":"commit:test"}]
        self.assertFalse(self.bridge.apply_lesson_mappings(sel,confirmed=False)["ok"])
        self.assertFalse(self.bridge.apply_lesson_mappings(sel,confirmed=True)["ok"])
        self.assertFalse((self.vault/".base-conhecimento"/"aulas-github.json").exists())

    def test_manual_save_requires_confirmation(self):
        data={"professor":[dict(PROFESSOR)],"dupla":[]}
        self.assertFalse(self.bridge.save_lesson_code("Aula-131",data,confirmed=False)["ok"])
        self.assertTrue(self.bridge.save_lesson_code("Aula-131",data,confirmed=True)["ok"])

    def test_packaged_editor_js_is_inline_and_hashed(self):
        html=load_local_ui()
        self.assertIn("lesson-code-dialog",html)
        self.assertIn("Assistente de mapeamento GitHub",html)
        self.assertIn("data-map-previous",html)
        self.assertNotIn('src="lesson_code.js"',html)
        self.assertIn("lesson-map-repo",html)


if __name__=="__main__":
    unittest.main()
