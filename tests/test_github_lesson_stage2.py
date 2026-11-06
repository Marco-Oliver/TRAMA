"""Stage 2: frozen GitHub commit identities are persistent and immutable."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.bridge import Bridge
from knowledge_bridge.store import Store
from knowledge_bridge.lesson_code_config import save_lessons
from knowledge_bridge.github_mapping import GithubMapping

SHA_A = "a" * 40
SHA_B = "b" * 40
REPO = "https://github.com/example/course"


def sample():
    return {"professor":[{"id":"backend","rotulo":"Professor",
             "repo":REPO,"ref_tipo":"branch","ref":"main","pasta":"V3",
             "anterior":{"ref_tipo":"branch","ref":"main","pasta":"V2"}}],
            "dupla":[]}


class FrozenShaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / "vault"
        self.vault.mkdir()
        self.bridge = Bridge()
        self.bridge.settings = {"vault":str(self.vault)}
        save_lessons(self.vault, {"Aula-131":sample()})

    def test_store_never_replaces_sha_and_survives_restart(self):
        db = Store(self.vault)
        try:
            first = db.freeze_github_ref("Aula-131","professor","backend","current",
                                         REPO,"branch","main","V3",SHA_A)
            self.assertTrue(first["created"])
            second = db.freeze_github_ref("Aula-131","professor","backend","current",
                                          REPO,"branch","main","V3",SHA_B)
            self.assertFalse(second["created"])
            self.assertEqual(second["sha"],SHA_A)
            with self.assertRaises(ValueError):
                db.freeze_github_ref("Aula-131","professor","backend","current",
                                     REPO,"branch","develop","V3",SHA_B)
        finally:
            db.close()
        reopened = Store(self.vault)
        try:
            self.assertEqual(reopened.github_ref("Aula-131","professor","backend")["commit_sha"],SHA_A)
        finally:
            reopened.close()

    def test_freeze_requires_explicit_consent_and_never_resolves_twice(self):
        self.assertFalse(self.bridge.freeze_lesson_code("Aula-131","professor","backend")["ok"])
        with patch.object(GithubMapping,"resolve_sha",return_value=SHA_A) as resolver:
            first=self.bridge.freeze_lesson_code("Aula-131","professor","backend",True)
            self.assertTrue(first["ok"],first)
            self.assertTrue(first["created"])
            second=self.bridge.freeze_lesson_code("Aula-131","professor","backend",True)
            self.assertTrue(second["ok"],second)
            self.assertFalse(second["created"])
            self.assertEqual(second["sha"],SHA_A)
            resolver.assert_called_once()
        frozen=self.bridge.frozen_lesson_code("Aula-131")
        self.assertEqual(frozen["refs"][0]["commit_sha"],SHA_A)

    def test_unfreeze_requires_confirmation_and_allows_refreeze_after_branch_moves(self):
        with patch.object(GithubMapping, "resolve_sha", return_value=SHA_A):
            pinned=self.bridge.freeze_lesson_code("Aula-131","professor","backend",True)
        self.assertTrue(pinned["ok"], pinned)
        self.assertEqual(pinned["sha"],SHA_A)
        denied=self.bridge.unfreeze_lesson_code("Aula-131","professor","backend","current",False)
        self.assertFalse(denied["ok"])
        self.assertEqual(self.bridge.frozen_lesson_code("Aula-131")["refs"][0]["commit_sha"],SHA_A)
        cleared=self.bridge.unfreeze_lesson_code("Aula-131","professor","backend","current",True)
        self.assertTrue(cleared["ok"],cleared)
        self.assertEqual(self.bridge.frozen_lesson_code("Aula-131")["refs"],[])
        with patch.object(GithubMapping, "resolve_sha", return_value=SHA_B):
            new=self.bridge.freeze_lesson_code("Aula-131","professor","backend",True)
        self.assertTrue(new["ok"],new)
        self.assertEqual(new["sha"],SHA_B)
        self.assertTrue(new["created"])
        self.assertFalse(self.bridge.unfreeze_lesson_code("Aula-131","professor",
                          "backend","invalid-slot",True)["ok"])

    def test_previous_folder_is_distinct_slot_and_deletion_clears_locks(self):
        with patch.object(GithubMapping,"resolve_sha",return_value=SHA_A):
            self.assertTrue(self.bridge.freeze_lesson_code("Aula-131","professor","backend",True)["ok"])
            older=self.bridge.freeze_lesson_code("Aula-131","professor","backend",True,True)
        self.assertTrue(older["ok"],older)
        db=Store(self.vault)
        try:
            self.assertEqual(db.github_ref("Aula-131","professor","backend","previous")["folder"],"V2")
        finally:
            db.close()
        self.assertTrue(self.bridge.remove_lesson_code("Aula-131",True)["ok"])
        reopened=Store(self.vault)
        try:
            self.assertIsNone(reopened.github_ref("Aula-131","professor","backend"))
            self.assertIsNone(reopened.github_ref("Aula-131","professor","backend","previous"))
        finally:
            reopened.close()

    def test_resolver_rejects_bad_ref_and_accepts_only_full_sha(self):
        def fake(_client, repo, endpoint):
            self.assertEqual(repo,REPO)
            self.assertEqual(endpoint,"commits?per_page=1&sha=main")
            return [{"sha": SHA_A}]
        with patch.object(GithubMapping,"_get",fake):
            self.assertEqual(GithubMapping(token="").resolve_sha(REPO,"branch","main"),SHA_A)
        with self.assertRaises(ValueError):
            GithubMapping(token="").resolve_sha(REPO,"branch","../secret")


if __name__ == "__main__":
    unittest.main()
