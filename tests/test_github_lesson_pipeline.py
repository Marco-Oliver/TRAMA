"""Lesson reprocessing and optional AI code comparison honor frozen SHA only."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from knowledge_bridge.bridge import Bridge
from knowledge_bridge.github_mapping import GithubMapping
from knowledge_bridge.lesson_code_config import save_lessons
from knowledge_bridge.store import Store

REPO="https://github.com/example/course"
A="a"*40
B="b"*40

def mapping():
    return {"professor":[{"id":"backend","rotulo":"Professor","repo":REPO,
            "ref_tipo":"branch","ref":"main","pasta":"V3"}],"dupla":[]}

class ProcessingFrozenShaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault=Path(self.temp.name)/"vault"
        self.vault.mkdir()
        self.bridge=Bridge()
        self.bridge.settings={"vault":str(self.vault),"confirmed_free":True}
        save_lessons(self.vault,{"Aula-131":mapping()})

    def test_mapped_lesson_filters_unfrozen_and_moved_branch_code(self):
        db=Store(self.vault)
        try:
            self.assertFalse(db.github_lesson_repo_allowed("Aula-131",REPO,A))
            db.freeze_github_ref("Aula-131","professor","backend","current",
                                 REPO,"branch","main","V3",A)
            self.assertTrue(db.github_lesson_repo_allowed("Aula-131",REPO,A))
            self.assertFalse(db.github_lesson_repo_allowed("Aula-131",REPO,B))
            self.assertTrue(db.github_lesson_repo_allowed("Aula-999",REPO,B))
        finally:
            db.close()

    def test_reprocessing_uses_locked_sha_after_mock_branch_advances(self):
        with patch.object(GithubMapping,"resolve_sha",return_value=A):
            self.assertTrue(self.bridge.freeze_lesson_code(
                "Aula-131","professor","backend",True)["ok"])
        app=Mock()
        app.store.sources.return_value=[{"lesson":"Aula-131","status":"PUBLISHED"}]
        with patch.object(self.bridge._key_vault,"configured",return_value={"gemini":True}), \
             patch.object(self.bridge,"_make_application",return_value=app), \
             patch.object(GithubMapping,"resolve_sha",return_value=B) as moved:
            result=self.bridge.process_lesson("Aula-131",True,force=True)
        self.assertTrue(result["ok"],result)
        self.assertEqual(result["code_shas"][0]["sha"],A)
        self.assertFalse(result["code_pending_freeze"])
        moved.assert_not_called()
        db=Store(self.vault)
        try:
            self.assertTrue(db.github_lesson_repo_allowed("Aula-131",REPO,A))
            self.assertFalse(db.github_lesson_repo_allowed("Aula-131",REPO,B))
        finally:
            db.close()

    def test_processing_without_frozen_reference_warns_not_autopins(self):
        app=Mock()
        app.store.sources.return_value=[{"lesson":"Aula-131","status":"PUBLISHED"}]
        with patch.object(self.bridge._key_vault,"configured",return_value={"gemini":True}), \
             patch.object(self.bridge,"_make_application",return_value=app), \
             patch.object(GithubMapping,"resolve_sha",side_effect=AssertionError("No branch lookup")):
            result=self.bridge.process_lesson("Aula-131",True,force=True)
        self.assertTrue(result["ok"],result)
        self.assertTrue(result["code_pending_freeze"])
        self.assertIn("congele a versão desta aula",result["message"])
        self.assertEqual(result["code_shas"],[])

if __name__=="__main__":
    unittest.main()
