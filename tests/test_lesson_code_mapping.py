"""Etapa 1 GitHub por aula: cadastro, sugestões sem persistência e falhas isoladas."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from knowledge_bridge.bridge import Bridge, load_local_ui
from knowledge_bridge.github_mapping import GithubMapping
from knowledge_bridge.lesson_code_config import read_config, save_lessons, validate_lesson, lesson_dates
from knowledge_bridge.store import Store

A = "a" * 40
B = "b" * 40
REPO = "https://github.com/organizador/certificados"


def sample():
    return {
        "professor": [
            {"id": "backend", "rotulo": "Professor API",
             "repo": REPO, "ref_tipo": "branch", "ref": "main", "pasta": "V3",
             "anterior": {"ref_tipo": "branch", "ref": "main", "pasta": "V2"}},
            {"id": "frontend", "rotulo": "Professor Front",
             "repo": "https://github.com/organizador/front",
             "ref_tipo": "tag", "ref": "v3", "pasta": ""}
        ],
        "dupla": [
            {"id": "dupla-api", "rotulo": "Eu e Pedro",
             "professor_id": "backend", "repo": "https://github.com/aluno/api",
             "ref_tipo": "commit", "ref": A, "pasta": ""}
        ],
    }


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / "vault"
        self.vault.mkdir()

    def test_two_professor_one_student_and_atomic_replace(self):
        self.assertEqual(validate_lesson("Aula-131", sample()), [])
        with patch("knowledge_bridge.lesson_code_config.os.replace", wraps=os.replace) as replace:
            result = save_lessons(self.vault, {"Aula-131": sample()})
            replace.assert_called_once()
        self.assertEqual(result["saved"], ["Aula-131"])
        file = self.vault / ".base-conhecimento/aulas-github.json"
        raw = json.loads(file.read_text(encoding="utf-8"))
        self.assertEqual(len(raw["aulas"]["Aula-131"]["professor"]), 2)
        self.assertEqual(len(raw["aulas"]["Aula-131"]["dupla"]), 1)
        self.assertNotIn("TRAMA_GITHUB_TOKEN", file.read_text())
        self.assertFalse(list(file.parent.glob(".aulas-github-*")))

    def test_invalid_lesson_isolated_without_erasing_it(self):
        file = self.vault / ".base-conhecimento/aulas-github.json"
        file.parent.mkdir(parents=True)
        file.write_text(json.dumps({"schema": 1, "aulas": {
            "Aula-131": sample(),
            "Aula-132": {"professor": [{"id": "x"}], "dupla": []}
        }}), encoding="utf-8")
        data = read_config(self.vault)
        self.assertFalse(data["fatal"])
        self.assertIn("Aula-131", data["aulas"])
        self.assertNotIn("Aula-132", data["aulas"])
        self.assertTrue(any("Aula-132.professor[0].repo" in issue for issue in data["erros"]))
        save_lessons(self.vault, {"Aula-133": sample()})
        final = json.loads(file.read_text(encoding="utf-8"))
        self.assertIn("Aula-132", final["aulas"])
        self.assertIn("Aula-133", final["aulas"])

    def test_invalid_root_does_not_get_overwritten(self):
        file = self.vault / ".base-conhecimento/aulas-github.json"
        file.parent.mkdir(parents=True)
        file.write_text("{broken json", encoding="utf-8")
        self.assertTrue(read_config(self.vault)["fatal"])
        with self.assertRaises(ValueError):
            save_lessons(self.vault, {"Aula-131": sample()})
        self.assertEqual(file.read_text(), "{broken json")

    def test_forbidden_secrets_and_path_traversal(self):
        row = sample()
        row["professor"][0]["repo"] = "https://user:token@github.com/a/b"
        row["professor"][0]["pasta"] = "../private"
        err = validate_lesson("Aula-131", row)
        self.assertTrue(any(".repo:" in item for item in err))
        self.assertTrue(any(".pasta:" in item for item in err))
        row["professor"][0]["repo"] = REPO
        row["professor"][0]["pasta"] = ""
        row["dupla"][0]["professor_id"] = "does-not-exist"
        self.assertTrue(any("professor não encontrado" in x for x in validate_lesson("Aula-131", row)))

    def test_classroom_date_is_labelled_only_as_context_date(self):
        store = Store(self.vault)
        try:
            store.upsert_source({"id":"source-131","original_path":"synthetic",
                "kind":"transcript","digest":"sha","label":"Aula-131-V01.txt",
                "lesson":"Aula-131","video":"V01","stored_path":"x"})
        finally:
            store.close()
        folder = self.vault / "99-Anexos/Contexto-Classroom"
        folder.mkdir(parents=True)
        (folder / "Aula-131.json").write_text('{"data":"05/11/2026"}', encoding="utf-8")
        self.assertEqual(lesson_dates(self.vault), [{
            "aula":"Aula-131","data":"2026-11-05","origem_data":"contexto_classroom"}])


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / "vault"
        self.vault.mkdir()
        self.bridge = Bridge()
        self.bridge.settings = {"vault":str(self.vault)}

    @staticmethod
    def catalog():
        return {"repo":REPO, "candidatos":[
            {"id":"commit:"+A,"tipo":"commit","ref_tipo":"commit","ref":A,
             "pasta":"","data":"2026-11-04","rotulo":"Commit de teste",
             "sugestao_anterior":None},
            {"id":"pasta:"+A+":V3","tipo":"pasta","ref_tipo":"commit","ref":A,
             "pasta":"V3","data":"","rotulo":"Pasta V3",
             "sugestao_anterior":{"ref_tipo":"commit","ref":A,"pasta":"V2"}}
        ],"aulas":[{"aula":"Aula-131","data":"2026-11-05",
                     "candidato_id":"commit:"+A,"origem_data":"contexto_classroom",
                     "motivo":"Data aproximada"}]}

    def test_three_rest_calls_commit_tag_and_one_recursive_tree(self):
        calls=[]
        def fake(self, repo, endpoint):
            calls.append(endpoint)
            if endpoint.startswith("commits?"):
                return [{"sha":A,"commit":{"committer":{"date":"2026-11-04T10:00:00Z"},
                                      "message":"Versão V3"}}]
            if endpoint.startswith("tags?"):
                return [{"name":"v3","commit":{"sha":A}}]
            if endpoint.startswith("git/trees/"):
                return {"truncated":False,"tree":[
                    {"type":"tree","path":"V1"},{"type":"tree","path":"V2"},
                    {"type":"tree","path":"V3"},{"type":"blob","path":"V3/test.cs"}]}
            raise AssertionError(endpoint)
        with patch.object(GithubMapping, "_get", fake):
            result = GithubMapping(token="").catalogue(REPO)
        self.assertEqual(len(calls),3)
        self.assertEqual(sum("recursive=1" in x for x in calls),1)
        folder = next(x for x in result["candidatos"] if x["pasta"]=="V3")
        self.assertEqual(folder["sugestao_anterior"]["pasta"],"V2")
        self.assertEqual(folder["data"],"2026-11-04")  # date hint from commit subject, not tree
        self.assertEqual(folder["fonte_data"],"mensagem_commit_indicativa")
        suggestions=GithubMapping.suggestions(result,[{
            "aula":"Aula-131","data":"2026-11-05",
            "origem_data":"contexto_classroom"}])
        self.assertTrue(suggestions[0]["candidato_id"].startswith("pasta:"))  # same day: pasta beats commit

    def test_preview_never_writes_and_confirm_only(self):
        data=self.catalog()
        self.bridge._mapping_preview=data
        file=self.vault/".base-conhecimento/aulas-github.json"
        rows=[{"aula":"Aula-131","candidato_id":"pasta:"+A+":V3",
               "confirmar_anterior":False}]
        no=self.bridge.apply_lesson_mappings(rows,False)
        self.assertFalse(no["ok"])
        self.assertFalse(file.exists())
        yes=self.bridge.apply_lesson_mappings(rows,True)
        self.assertTrue(yes,yes)
        self.assertTrue(yes["ok"],yes)
        item=read_config(self.vault)["aulas"]["Aula-131"]["professor"][0]
        self.assertEqual(item["pasta"],"V3")
        self.assertNotIn("anterior",item)
        self.assertFalse(self.bridge.apply_lesson_mappings(rows,True)["ok"])

    def test_explicit_previous_confirmation(self):
        self.bridge._mapping_preview=self.catalog()
        result=self.bridge.apply_lesson_mappings([
            {"aula":"Aula-131","candidato_id":"pasta:"+A+":V3",
             "confirmar_anterior":True}],True)
        self.assertTrue(result["ok"],result)
        item=read_config(self.vault)["aulas"]["Aula-131"]["professor"][0]
        self.assertEqual(item["anterior"]["pasta"],"V2")

    def test_form_save_works_without_github_or_ai(self):
        saved=self.bridge.save_lesson_code("Aula-131",sample(),True)
        self.assertTrue(saved["ok"],saved)
        loaded=self.bridge.lesson_code_config("Aula-131")
        self.assertEqual(len(loaded["aulas"]["Aula-131"]["professor"]),2)
        self.assertEqual(len(loaded["aulas"]["Aula-131"]["dupla"]),1)

    def test_bundled_html_includes_new_ui_and_strict_csp(self):
        html=load_local_ui()
        self.assertIn('id="lesson-code-dialog"',html)
        self.assertIn("preview_lesson_mappings",html)
        self.assertIn("script-src 'sha256-",html)
        self.assertNotIn('<script src="lesson_code.js"',html)


if __name__ == "__main__":
    unittest.main()
