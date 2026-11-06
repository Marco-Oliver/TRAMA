"""JSON/SQLite transaction safety for GitHub lesson registrations."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.bridge import Bridge
from knowledge_bridge.lesson_code_config import read_config, save_lessons
from knowledge_bridge.store import Store
from knowledge_bridge.github_lesson_state import preview_invalidations

REPO = "https://github.com/example/course"
SHA = "a"*40


def record(two=True):
    teacher=[{"id":"backend","rotulo":"Professor backend","repo":REPO,
              "ref_tipo":"branch","ref":"main","pasta":"V3",
              "anterior":{"ref_tipo":"branch","ref":"main","pasta":"V2"}}]
    if two:
        teacher.append({"id":"front","rotulo":"Professor frontend",
                        "repo":"https://github.com/example/web",
                        "ref_tipo":"tag","ref":"v2","pasta":""})
    return {"professor": teacher, "dupla": []}


class LessonStateTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault=Path(self.temp.name)/"vault"
        self.vault.mkdir()
        self.bridge=Bridge()
        self.bridge.settings={"vault":str(self.vault)}
        save_lessons(self.vault,{"Aula-131":record()})
        db=Store(self.vault)
        db.freeze_github_ref("Aula-131","professor","backend","current",
                             REPO,"branch","main","V3",SHA)
        db.freeze_github_ref("Aula-131","professor","backend","previous",
                             REPO,"branch","main","V2",SHA)
        db.freeze_github_ref("Aula-131","professor","front","current",
                             "https://github.com/example/web","tag","v2","",SHA)
        db.close()
        self.path=self.vault/".base-conhecimento/aulas-github.json"

    def frozen(self):
        db=Store(self.vault)
        try:
            return [dict(r) for r in db.conn.execute(
                "SELECT * FROM github_lesson_refs ORDER BY role,repository_id,slot")]
        finally:
            db.close()

    def test_change_folder_requires_extra_confirmation_and_clears_only_changed_slot(self):
        changed=record()
        changed["professor"][0]["pasta"]="V4"
        impact=self.bridge.lesson_code_changes("Aula-131",changed)
        self.assertTrue(impact["ok"],impact)
        self.assertEqual([(x["repository_id"],x["slot"]) for x in impact["invalidated"]],
                         [("backend","current")])
        original=self.path.read_bytes()
        denied=self.bridge.save_lesson_code("Aula-131",changed,True)
        self.assertFalse(denied["ok"],denied)
        self.assertEqual(original,self.path.read_bytes())
        saved=self.bridge.save_lesson_code("Aula-131",changed,True,False,"",True)
        self.assertTrue(saved["ok"],saved)
        remaining={(r["repository_id"],r["slot"]) for r in self.frozen()}
        self.assertEqual(remaining,{("backend","previous"),("front","current")})

    def test_removing_repo_and_previous_reference_prunes_locks(self):
        changed=record(two=False)
        changed["professor"][0].pop("anterior")
        self.assertTrue(self.bridge.save_lesson_code("Aula-131",changed,True,False,"",True)["ok"])
        self.assertEqual([(r["repository_id"],r["slot"]) for r in self.frozen()],
                         [("backend","current")])

    def test_json_save_failure_rolls_back_sqlite(self):
        old_json=self.path.read_bytes()
        old_rows=self.frozen()
        changed=record()
        changed["professor"][0]["ref"]="feature"
        with patch("knowledge_bridge.github_lesson_state.save_lessons",side_effect=OSError("disk full")):
            result=self.bridge.save_lesson_code("Aula-131",changed,True,False,"",True)
        self.assertFalse(result["ok"])
        self.assertEqual(self.path.read_bytes(),old_json)
        self.assertEqual(self.frozen(),old_rows)

    def test_remove_json_failure_never_deletes_frozen_rows(self):
        old_json=self.path.read_bytes()
        old_rows=self.frozen()
        with patch("knowledge_bridge.github_lesson_state.delete_lesson",side_effect=OSError("disk full")):
            result=self.bridge.remove_lesson_code("Aula-131",True)
        self.assertFalse(result["ok"])
        self.assertEqual(self.path.read_bytes(),old_json)
        self.assertEqual(self.frozen(),old_rows)

    def test_sqlite_commit_failure_restores_json_and_rows(self):
        old_json=self.path.read_bytes()
        old_rows=self.frozen()
        changed=record(two=False)
        with patch("knowledge_bridge.github_lesson_state._commit",side_effect=OSError("commit failed")):
            result=self.bridge.save_lesson_code("Aula-131",changed,True,False,"",True)
        self.assertFalse(result["ok"])
        self.assertEqual(self.path.read_bytes(),old_json)
        self.assertEqual(self.frozen(),old_rows)

    def test_successful_remove_clears_both_stores(self):
        self.assertTrue(self.bridge.remove_lesson_code("Aula-131",True)["ok"])
        self.assertEqual(self.frozen(),[])
        self.assertNotIn("Aula-131",read_config(self.vault)["aulas"])


if __name__=="__main__":
    unittest.main()
