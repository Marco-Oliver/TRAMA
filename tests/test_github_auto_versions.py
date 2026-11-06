"""End-to-end automatic version mapping: URL + TXT, no per-lesson Git setup."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.auto_ingest import AutoOrganizer
from knowledge_bridge.github_code import GithubCodeReader
from knowledge_bridge.github_mapping import GithubMapping
from knowledge_bridge.github_auto_versions import GithubAutoMapper, role_for, version_number
from knowledge_bridge.lesson_code_config import save_lessons
from knowledge_bridge.pipeline import Application
from knowledge_bridge.store import Store

REPO = "https://github.com/academiadoprogramador-fullstack/curso"
SHAS = [str(i + 1) * 40 for i in range(4)]
NAMES = ["LoginService","NoteService","CategoryService","ArchiveService"]
CONTENT = {f"src/{name}.ts":f"export class {name} {{}}\n".encode("utf-8") for name in NAMES}


def blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\x00"+data,
                        usedforsecurity=False).hexdigest()


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.downloads = []

    def get(self, client, repo, endpoint):
        self.calls.append((repo,endpoint))
        if endpoint == "":
            return {"private":False}
        if endpoint == "branches?per_page=100&page=1":
            return [{"name":name,"commit":{"sha":sha}} for name,sha in
                    zip(("v0","v1","V2","versao-3"),SHAS)]
        if endpoint == "tags?per_page=100&page=1":
            return []
        if endpoint.startswith("commits?per_page=1&sha="):
            import urllib.parse
            ref = urllib.parse.unquote(endpoint.split("sha=")[1])
            names = ("v0","v1","V2","versao-3")
            return [{"sha":SHAS[names.index(ref)]}]
        if endpoint.startswith("compare/"):
            base,head = endpoint.split("/")[-1].split("...")
            i = SHAS.index(head)
            self_index = SHAS.index(base)
            assert i == self_index + 1
            path = f"src/{NAMES[i]}.ts"
            return {"files":[{"filename":path,"status":"added","patch":"@@ +1 @@"}],
                    "commits":[{"commit":{"committer":{
                        "date":f"2026-01-{i+1:02d}T12:00:00Z"}}}]}
        if endpoint.startswith("git/trees/"):
            sha=endpoint.split("/")[2].split("?")[0]
            i=SHAS.index(sha)
            return {"truncated":False,"tree":[{
                "type":"blob","mode":"100644","path":path,
                "size":len(data),"sha":blob(data)}
                for path,data in list(CONTENT.items())[:i+1]]}
        raise AssertionError("unexpected HTTP endpoint: " + endpoint)

    def raw(self, reader, repo, sha, path, private):
        self.downloads.append((sha,path))
        return CONTENT[path]


class NoAI:
    attempts=0
    def active(self):return []


class AutoVersionsEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.vault=self.root/"vault"
        self.input=self.root/"txt"
        self.input.mkdir()
        self.cache_patcher=patch("knowledge_bridge.github_cache.DATA_HOME",self.root/"cache-home")
        self.cache_patcher.start()
        self.addCleanup(self.cache_patcher.stop)
        self.app=Application(self.vault,config=self.root/"none.env",log=lambda _:None)
        self.app.ai=NoAI()
        self.addCleanup(self.app.close)
        self.api=FakeGitHub()
        self.http=patch.object(GithubMapping,"_get",
            lambda client,repo,endpoint:self.api.get(client,repo,endpoint))
        self.raw=patch.object(GithubCodeReader,"_raw",
            lambda reader,repo,sha,path,private:self.api.raw(reader,repo,sha,path,private))
        self.http.start()
        self.raw.start()
        self.addCleanup(self.http.stop)
        self.addCleanup(self.raw.stop)

    def txt(self, lesson, value):
        path=self.input/f"A{lesson:02d} - V01 - Aula.txt"
        path.write_text("00:01 Hoje criamos "+value+".\n",encoding="utf-8")
        return path

    def content_note(self, lesson):
        folder=self.vault/"02-Minhas-Aulas"/f"Aula-{lesson:03d}"
        notes=[p for p in folder.glob("*.md") if p.name!="00-Visao-geral.md"]
        self.assertEqual(len(notes),1,notes)
        return notes[0].read_text(encoding="utf-8")

    def import_all(self):
        # Each version has two content lessons, plus an explicitly unrelated
        # lesson; the user provides only a repo link and TXT.
        examples=[("v0 LoginService"),("LoginService"),("v1 NoteService"),
                  ("NoteService"),("v2 CategoryService"),("CategoryService"),
                  ("v3 ArchiveService"),("ArchiveService")]
        paths=[self.txt(i,text) for i,text in enumerate(examples,1)]
        paths.append(self.txt(9,"revisão da v2 e quebra-cuca sem código"))
        return AutoOrganizer(self.app).run(paths,REPO,authorized=True)

    def test_url_txt_four_versions_eight_lessons_and_review_note(self):
        result=self.import_all()
        self.assertEqual(result["files"],9)
        self.assertEqual(result["automatic_versions"],9)
        self.assertEqual(len(self.app.store.auto_repositories()),1)
        registered=self.app.store.auto_repositories()[0]
        self.assertEqual(registered["role"],"professor")
        self.assertEqual(registered["status"],"ready")
        import json
        versions=json.loads(registered["versions_json"])
        self.assertEqual([v["number"] for v in versions],[0,1,2,3])
        self.assertEqual([v["sha"] for v in versions],SHAS)
        for lesson in range(1,9):
            count,refs=self.app.store.github_lesson_refs(f"Aula-{lesson:03d}")
            self.assertEqual(count,1,(lesson,refs))
            row=refs[0]
            index=(lesson-1)//2
            self.assertEqual(row["commit_sha"],SHAS[index],lesson)
            self.assertEqual(row["origem"],"automatica")
            self.assertIn(row["confianca"],("alta","media","baixa"))
            note=self.content_note(lesson)
            self.assertIn("Versão GitHub automática",note)
            self.assertIn(row["ref_name"],note)
            self.assertIn("confiança",note)
            self.assertIn(f"src/{NAMES[index]}.ts",note)
        self.assertEqual(self.app.store.github_lesson_refs("Aula-009"),(0,[]))
        review=self.content_note(9)
        self.assertNotIn("/blob/",review)
        self.assertIn("sem relação verificável",review)
        self.assertEqual(len([x for x in self.api.calls if x[1].startswith("git/trees/")]),4)
        # Four snapshots, content-addressed file cache: 1+1+1+1 downloads.
        self.assertEqual(len(self.api.downloads),4)

    def test_reprocessing_keeps_sha_and_manual_edit_wins(self):
        self.import_all()
        before={lesson:self.app.store.github_lesson_refs(f"Aula-{lesson:03d}")[1][0]["commit_sha"]
                for lesson in range(1,9)}
        self.assertEqual(self.app.assign_github_versions()["mapped"],0)
        after={lesson:self.app.store.github_lesson_refs(f"Aula-{lesson:03d}")[1][0]["commit_sha"]
               for lesson in range(1,9)}
        self.assertEqual(before,after)
        # The user manually chooses a different revision in advanced Git.
        manual={"professor":[{"id":"my-choice","rotulo":"Professor",
                              "repo":REPO,"ref_tipo":"commit","ref":SHAS[3],"pasta":""}],
                "dupla":[]}
        save_lessons(self.vault,{"Aula-002":manual})
        self.app.store.freeze_github_ref("Aula-002","professor","my-choice","current",
                                         REPO,"commit",SHAS[3],"",SHAS[3],private=False)
        self.assertEqual(self.app.assign_github_versions()["mapped"],0)
        count,locked=self.app.store.github_lesson_refs("Aula-002")
        self.assertEqual(count,1)
        self.assertEqual(locked[0]["commit_sha"],SHAS[3])
        self.assertEqual(locked[0]["origem"],"manual")
        self.assertEqual(self.app.store.github_lesson_refs("Aula-003")[1][0]["commit_sha"],SHAS[1])

    def test_rate_limit_pauses_without_changing_existing_decisions(self):
        self.import_all()
        first=self.app.store.github_lesson_refs("Aula-001")[1][0]["commit_sha"]
        with patch.object(GithubMapping,"_get",side_effect=AssertionError("should not query completed mapping")):
            self.assertEqual(self.app.assign_github_versions()["mapped"],0)
        self.assertEqual(self.app.store.github_lesson_refs("Aula-001")[1][0]["commit_sha"],first)

    def test_rate_limit_during_snapshots_pauses_until_reset(self):
        from knowledge_bridge.github_mapping import GithubRateLimitError
        from knowledge_bridge.github_lesson_index import LessonRepositoryIndex
        import time
        self.import_all()
        before=self.app.store.github_lesson_refs("Aula-001")[1][0]["commit_sha"]
        with patch.object(LessonRepositoryIndex, "_snapshot",
                          side_effect=GithubRateLimitError(time.time()+3600, 429)):
            response=self.app.assign_github_versions(recalculate=True)
        self.assertEqual(response["mapped"],0)
        self.assertEqual(self.app.store.auto_repositories()[0]["status"],"index_paused")
        self.assertEqual(self.app.store.github_lesson_refs("Aula-001")[1][0]["commit_sha"],before)
        with patch.object(GithubMapping, "_get",
                          side_effect=AssertionError("Must await reset")):
            response=self.app.assign_github_versions()
        self.assertEqual(response["mapped"],0)
        self.assertEqual(self.app.store.auto_repositories()[0]["status"],"index_paused")

    def test_low_confidence_warning_reaches_obsidian(self):
        self.import_all()
        repo=self.app.store.auto_repositories()[0]
        import json
        selected=json.loads(repo["versions_json"])[0]
        self.assertTrue(self.app.store.set_auto_decision(
            REPO,"Aula-001","professor",False,selected,"baixa",recalculate=True))
        self.app.publisher.rebuild()
        self.assertIn("versão estimada; confira", self.content_note(1))
        self.assertIn("confiança **baixa**", self.content_note(1))

    def test_role_and_version_name_detection(self):
        self.assertEqual(role_for(REPO),"professor")
        self.assertEqual(role_for("https://github.com/Marco-Oliver/dupla"),"dupla")
        self.assertEqual([version_number(v) for v in ("v0","v1","V2","versao-3")],[0,1,2,3])


if __name__ == "__main__":
    unittest.main()
