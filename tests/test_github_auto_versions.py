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
from knowledge_bridge.github_auto_versions import (GithubAutoMapper, role_for,
    version_number, project_version_mentions, _early_review)
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

    def test_paused_rate_does_not_claim_a_new_lesson_has_no_code(self):
        lesson=self.txt(10,"Hoje vemos HttpClient")
        self.app.add_file(lesson)
        self.app.store.save_auto_repository(
            REPO,"professor",False,"index_paused",versions=[],
            message='{"retry_at":9999999999}')
        self.app.publisher.rebuild()
        note=self.content_note(10)
        self.assertIn("Associação temporariamente pendente", note)
        self.assertIn("não significa ausência de código",note)
        self.assertNotIn("*Nenhum vínculo com código encontrado ainda.",note)

    def test_role_and_version_name_detection(self):
        self.assertEqual(role_for(REPO),"professor")
        self.assertEqual(role_for("https://github.com/Marco-Oliver/dupla"),"dupla")
        self.assertEqual([version_number(v) for v in ("v0","v1","V2","versao-3")],[0,1,2,3])



    def _default_branch_mock(self, branch="main", same_sha=False):
        original = self.api.get
        final = SHAS[3] if same_sha else "f" * 40

        def rest(client, repo, endpoint):
            if endpoint == "":
                return {"private":False, "default_branch":branch}
            if endpoint == "branches?per_page=100&page=1":
                return original(client,repo,endpoint)+[
                    {"name":branch,"commit":{"sha":final}}]
            if endpoint == "commits?per_page=1&sha="+branch:
                return [{"sha":final}]
            if endpoint == f"compare/{SHAS[3]}...{final}":
                return {"files":[{"filename":"src/FinalService.ts",
                                  "status":"added","patch":"@@ -0,0 +1 @@"}],
                        "commits":[{"commit":{"committer":{
                            "date":"2026-02-01T10:00:00Z"}}}]}
            return original(client,repo,endpoint)

        self.api.get = rest
        return final

    def test_main_is_last_if_head_differs_from_version_tags(self):
        head = self._default_branch_mock("main")
        versions=GithubAutoMapper(self.app.store).discover(REPO)
        self.assertEqual([v["name"] for v in versions],
                         ["v0","v1","V2","versao-3","main"])
        self.assertEqual(versions[-1]["sha"],head)
        self.assertEqual(versions[-1]["number"],4)
        self.assertTrue(versions[-1]["is_default"])
        self.assertEqual(versions[-1]["changed_paths"],["src/FinalService.ts"])
        self.assertIn((REPO,f"compare/{SHAS[3]}...{head}"),self.api.calls)
        self.assertEqual(sum(endpoint=="commits?per_page=1&sha=main"
                             for _,endpoint in self.api.calls),1)

    def test_another_default_branch_and_duplicate_head(self):
        head=self._default_branch_mock("develop",same_sha=True)
        versions=GithubAutoMapper(self.app.store).discover(REPO)
        self.assertEqual(len(versions),4)
        self.assertEqual(versions[-1]["sha"],head)
        self.assertFalse(any(v.get("is_default") for v in versions))

    def test_300_file_diff_uses_git_blob_identities_not_truncated_compare(self):
        original = self.api.get

        def truncated(client,repo,endpoint):
            if endpoint == f"compare/{SHAS[0]}...{SHAS[1]}":
                return {"files":[{"filename":f"bogus/file{i}.ts","status":"added"}
                                 for i in range(300)],
                        "commits":[{"commit":{"committer":{
                            "date":"2026-01-03T10:00:00Z"}}}]}
            return original(client,repo,endpoint)

        self.api.get = truncated
        mapper=GithubAutoMapper(self.app.store)
        versions=mapper.discover(REPO)
        self.assertEqual(len(versions),4)
        second=versions[1]
        self.assertEqual(second["diff_source"],"git_trees")
        self.assertEqual(second["changed_paths"],["src/NoteService.ts"])
        self.assertEqual(second["changed_lines"],{})
        delta=mapper._delta(REPO,second,versions[0])
        self.assertIn("NoteService",str(delta))
        self.assertNotIn("bogus",str(delta))
        trees=[endpoint for _,endpoint in self.api.calls
               if endpoint.startswith("git/trees/")]
        self.assertIn(f"git/trees/{SHAS[0]}?recursive=1",trees)
        self.assertIn(f"git/trees/{SHAS[1]}?recursive=1",trees)

    def test_early_review_signal_is_derived_from_verified_transcript(self):
        early=self.txt(10,"Primeiro vamos fazer a revisão")
        late=self.txt(11,"Projeto LoginService")
        late.write_text("00:01 Criamos LoginService\n12:00 revisão rápida\n",
                        encoding="utf-8")
        for path in (early,late):
            self.app.add_file(path)
        matcher=GithubAutoMapper(self.app.store)
        samples=matcher._texts()
        self.assertIn("Aula-010",samples)
        self.assertIn("Aula-011",samples)
        self.assertTrue(matcher._review_titles["Aula-010"])
        self.assertFalse(matcher._review_titles["Aula-011"])


class SpeechReviewAndCascadeTests(unittest.TestCase):
    def test_only_project_versioning_clues_count(self):
        negatives = [
            "A131 - V02 - Introdução à API",
            "V02 - parte da gravação",
            "A131 - V02\n00:01 Revisando a API",
            "00:01 Estamos usando .NET versão 8.",
            "00:02 Angular versão 17 tem signals.",
            "00:03 HTTP versão 2 suporta multiplexação.",
            "00:04 O Node versão 20 está instalado.",
            "00:05 C# versão 12 e SQL versão 3.",
            "00:06 Vamos subir Angular versão 17 na aula.",
        ]
        for sample in negatives:
            with self.subTest(text=sample):
                self.assertEqual(project_version_mentions(sample), set())
                score, code, speech = GithubAutoMapper._score(
                    sample, {"symbols": [], "evidence": [], "files": []}, 8)
                self.assertEqual(speech, 0)
        positives = [
            ("vou jogar isso para a V1", 1),
            ("agora vamos subir na v2", 2),
            ("vou criar a branch v3", 3),
            ("mandar para a versão 4", 4),
            ("fiz o commit na V5", 5),
        ]
        for sample, number in positives:
            with self.subTest(text=sample):
                self.assertEqual(project_version_mentions(sample), {number})
                self.assertEqual(GithubAutoMapper._score(
                    sample, {"symbols": [], "evidence": [], "files": []}, number)[2], 6)

    def test_speech_alone_cannot_outweigh_even_filename_code_evidence(self):
        spoken = GithubAutoMapper._score("vamos jogar para a V8",
            {"symbols": [], "evidence": [], "files": []}, 8)[0]
        code = GithubAutoMapper._score("Novo HttpClient",
            {"symbols": [], "evidence": [], "files": ["src/HttpClient.ts"]}, 2)[0]
        self.assertGreater(code, spoken)

    def test_review_title_or_first_two_minutes_only(self):
        self.assertTrue(_early_review("00:01 aula normal", "A01 - Revisão de lógica.txt"))
        self.assertTrue(_early_review("00:15 Revisão do conteúdo\n10:00 continuar"))
        self.assertTrue(_early_review("01:59 Vamos revisar\n14:00 outros assuntos"))
        self.assertFalse(_early_review("00:15 implementação\n11:55 revisão do detalhe"))
        self.assertFalse(_early_review("00:15 implementação\n02:01 revisão"))
        self.assertFalse(_early_review("sem timestamps e revisão apenas no meio"))

    def test_dotnet_version_eight_does_not_cascade_to_later_lessons(self):
        versions = [{"number":i, "sha":str(i % 10)*40} for i in range(9)]
        diffs = [{"symbols": [], "evidence": [], "files": [f"src/Feature{i}.ts"]}
                 for i in range(9)]
        transcripts = [
            "00:10 vou criar a branch v2 com Feature2",
            "00:10 Feature2",
            "00:10 Estamos usando .NET versão 8. Continuamos em Feature2.",
            "00:10 Feature2 e os testes",
            "00:10 Estamos na Feature2",
        ]
        lessons = [f"Aula-{i:03d}" for i in range(1,6)]
        scores = {lesson:[GithubAutoMapper._score(text, delta, v["number"])[0]
                          for delta,v in zip(diffs,versions)]
                  for lesson,text in zip(lessons,transcripts)}
        plan = GithubAutoMapper._optimize(lessons,versions,scores,{}, {})
        self.assertEqual(plan,[2,2,2,2,2])

if __name__ == "__main__":
    unittest.main()
