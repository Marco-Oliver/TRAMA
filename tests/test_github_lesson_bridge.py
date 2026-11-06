"""Public API -> immutable SQLite mapping -> mocked HTTP -> bounded cache."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from knowledge_bridge.bridge import Bridge, PublicApi, load_local_ui
from knowledge_bridge.github_code import GithubCodeReader
from knowledge_bridge.github_cache import GithubCache
from knowledge_bridge.github_mapping import GithubMapping
from knowledge_bridge.lesson_code_config import save_lessons
from knowledge_bridge.store import Store

REPO = "https://github.com/example/course"
A = "a"*40
B = "b"*40
NEW = b"new method\n"
OLD = b"old method\n"


def git_blob(contents):
    return hashlib.sha1(b"blob "+str(len(contents)).encode()+b"\x00"+contents,
                        usedforsecurity=False).hexdigest()


class LessonCodeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault=Path(self.temp.name)/"vault"
        self.vault.mkdir()
        self.bridge=Bridge()
        self.bridge.settings={"vault":str(self.vault)}
        self.cache_home=Path(self.temp.name)/"appdata"
        self.cache_patch=patch("knowledge_bridge.github_cache.DATA_HOME",self.cache_home)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        save_lessons(self.vault,{"Aula-131":{"professor":[{
          "id":"backend","rotulo":"Professor","repo":REPO,
          "ref_tipo":"branch","ref":"main","pasta":"V3",
          "anterior":{"ref_tipo":"branch","ref":"main","pasta":"V2"}}],"dupla":[]}})
        db=Store(self.vault)
        db.freeze_github_ref("Aula-131","professor","backend","current",
                              REPO,"branch","main","V3",A)
        db.freeze_github_ref("Aula-131","professor","backend","previous",
                              REPO,"branch","main","V2",B)
        db.close()
        self.calls=[]

    def fake_get(self, client, repo, endpoint):
        self.assertEqual(repo,REPO)
        self.calls.append(endpoint)
        if endpoint=="":
            return {"private":False}
        if endpoint==f"git/trees/{A}?recursive=1":
            return {"truncated":False,"tree":[
              {"type":"blob","mode":"100644","path":"V3/main.cs",
               "size":len(NEW),"sha":git_blob(NEW)},
              {"type":"blob","mode":"100644","path":"V2/main.cs",
               "size":len(OLD),"sha":git_blob(OLD)}]}
        if endpoint==f"compare/{B}...{A}":
            return {"files":[{"filename":"V3/main.cs","patch":"@@\n-old\n+new\n",
                              "status":"modified","changes":2}]}
        raise AssertionError("Unexpected HTTP endpoint "+endpoint)

    def fake_raw(self,reader,repo,sha,path,private):
        self.assertEqual(sha,A)
        return NEW if path=="V3/main.cs" else OLD

    def test_e2e_readonly_public_api_uses_frozen_sha_not_live_branch(self):
        api=PublicApi(self.bridge)
        with patch.object(GithubMapping,"_get",lambda client,repo,endpoint: self.fake_get(client,repo,endpoint)), \
             patch.object(GithubCodeReader,"_raw",lambda reader,repo,sha,path,private: self.fake_raw(reader,repo,sha,path,private)), \
             patch.object(GithubMapping,"resolve_sha",side_effect=AssertionError("branch refresh forbidden")), \
             patch("knowledge_bridge.github_cache.GithubCache",wraps=GithubCache) as built:
            listing=api.lesson_code_files("Aula-131","professor","backend")
            self.assertTrue(listing["ok"],listing)
            self.assertEqual(listing["sha"],A)
            self.assertEqual(listing["folder"],"V3")
            file=api.lesson_code_read_file("Aula-131","professor","backend","V3/main.cs")
            self.assertTrue(file["ok"],file)
            self.assertEqual(file["content"],NEW.decode())
            self.assertEqual(file["sha"],A)
            compared=api.lesson_code_compare("Aula-131","professor","backend")
            self.assertTrue(compared["ok"],compared)
            self.assertEqual((compared["base"],compared["head"]),(B,A))
            diff=api.lesson_code_diff_folders("Aula-131","professor","backend","V2","V3")
            self.assertTrue(diff["ok"],diff)
            self.assertEqual(diff["sha"],A)
            self.assertIn("git/trees/"+A+"?recursive=1",self.calls)
            self.assertTrue(all(c in ("",f"git/trees/{A}?recursive=1",f"compare/{B}...{A}")
                                for c in self.calls))
            self.assertGreaterEqual(built.call_count,4)
            self.assertTrue(all(call.kwargs["vault"].resolve()==self.vault.resolve()
                                for call in built.call_args_list),built.call_args_list)
        self.assertFalse((self.vault/"github-cache").exists())
        self.assertTrue((self.cache_home/"github-cache").exists())

    def test_ui_exposes_readonly_github_controls(self):
        html=load_local_ui()
        for ident in ("lesson-code-inspect-list","lesson-code-inspect-read",
                      "lesson-code-inspect-compare","lesson-code-inspect-diff"):
            self.assertIn('id="'+ident+'"',html)

    def test_without_frozen_sha_warns_and_never_calls_network(self):
        self.assertTrue(self.bridge.unfreeze_lesson_code(
            "Aula-131","professor","backend","current",True)["ok"])
        with patch.object(GithubMapping,"_get",side_effect=AssertionError("HTTP forbidden")), \
             patch.object(GithubMapping,"resolve_sha",side_effect=AssertionError("branch forbidden")):
            for method in (
                lambda: self.bridge.lesson_code_files("Aula-131","professor","backend"),
                lambda: self.bridge.lesson_code_read_file("Aula-131","professor","backend","V3/main.cs"),
                lambda: self.bridge.lesson_code_compare("Aula-131","professor","backend"),
            ):
                result=method()
                self.assertFalse(result["ok"],result)
                self.assertIn("congele a versão desta aula",result["message"])

    def test_scope_rejects_paths_outside_registered_folder(self):
        with patch.object(GithubMapping,"_get",side_effect=AssertionError("No HTTP")):
            result=self.bridge.lesson_code_read_file("Aula-131","professor","backend","V2/main.cs")
            self.assertFalse(result["ok"])
            self.assertIn("fora",result["message"])

    def test_reprocessing_does_not_repin_after_branch_advances(self):
        app=Mock()
        app.store.sources.return_value=[{"lesson":"Aula-131","status":"PUBLISHED"}]
        self.bridge.settings["confirmed_free"]=True
        with patch.object(self.bridge._key_vault,"configured",return_value={"gemini":True}), \
             patch.object(self.bridge,"_make_application",return_value=app), \
             patch.object(GithubMapping,"resolve_sha",return_value=B) as resolver, \
             patch.object(GithubMapping,"_get",lambda client,repo,endpoint: self.fake_get(client,repo,endpoint)):
            processed=self.bridge.process_lesson("Aula-131",True,True)
            self.assertTrue(processed["ok"],processed)
            listed=self.bridge.lesson_code_files("Aula-131","professor","backend")
            self.assertTrue(listed["ok"],listed)
            self.assertEqual(listed["sha"],A)
            resolver.assert_not_called()
        db=Store(self.vault)
        try:
            self.assertEqual(db.github_ref("Aula-131","professor","backend")["commit_sha"],A)
        finally:
            db.close()


if __name__=="__main__":
    unittest.main()
