"""Behavioral regression: old frozen SHA must determine code links and Obsidian output."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.github_code import GithubCodeReader
from knowledge_bridge.github_mapping import GithubMapping
from knowledge_bridge.github_lesson_index import LessonRepositoryIndex
from knowledge_bridge.lesson_code_config import save_lessons
from knowledge_bridge.publishing import Publisher
from knowledge_bridge.store import Store

REPO = "https://github.com/example/course"
OLD = "a" * 40
HEAD = "b" * 40
PULLED = "c" * 40
OLD_CODE = b"import { interval } from 'rxjs';\nconst ticks = interval(1000);\n"
HEAD_CODE = b"import { switchMap } from 'rxjs';\nconst other = switchMap(fn);\n"


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data,
                        usedforsecurity=False).hexdigest()


def global_index(concept, sha):
    return {"files": [{"path": "V3/new.ts", "size": len(HEAD_CODE)}],
            "total_files": 1, "technologies": ["TypeScript"],
            "evidence": [{"concept": concept, "path": "V3/new.ts", "line": 2,
                          "snippet": f"2: const other = {concept}(fn);",
                          "line_text": f"const other = {concept}(fn);"}],
            "symbols": [], "documentation": [], "history": [],
            "collaboration": False}


class FrozenLessonIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        patcher = patch("knowledge_bridge.github_cache.DATA_HOME", self.root / "data")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = Store(self.vault)
        self.addCleanup(self.db.close)
        self.db.save_repo(REPO, "course", HEAD, global_index("switchMap", HEAD), "INDEXED")
        self.calls = []

    def register_lesson(self, lesson="Aula-131"):
        save_lessons(self.vault, {lesson: {"professor": [{
            "id": "backend", "rotulo": "Professor", "repo": REPO,
            "ref_tipo": "branch", "ref": "main", "pasta": "V3"}], "dupla": []}})
        self.db.freeze_github_ref(lesson, "professor", "backend", "current",
                                  REPO, "branch", "main", "V3", OLD)

    def transcript(self, lesson="Aula-131", text="00:01 Usamos interval() e switchMap() na aula."):
        Publisher(self.db)
        original = (self.vault / "99-Anexos" / "Transcricoes-Originais" /
                    f"{lesson}-V01.txt")
        original.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        self.db.upsert_source({"id": lesson, "original_path": str(original),
            "kind": "transcript", "digest": digest, "label": original.name,
            "lesson": lesson, "video": "V01",
            "stored_path": original.relative_to(self.vault).as_posix()})

    def github_get(self, client, repo, endpoint):
        self.assertEqual(repo, REPO)
        self.calls.append(endpoint)
        if endpoint == "":
            return {"private": False}
        if endpoint == f"git/trees/{OLD}?recursive=1":
            return {"truncated": False, "tree": [{
                "type": "blob", "mode": "100644", "path": "V3/old.ts",
                "size": len(OLD_CODE), "sha": blob(OLD_CODE)}]}
        raise AssertionError("HEAD or unexpected network request: " + endpoint)

    def raw(self, reader, repo, sha, path, private):
        self.assertEqual((repo, sha, path, private),
                         (REPO, OLD, "V3/old.ts", False))
        return OLD_CODE

    def note(self, lesson="Aula-131"):
        path = self.vault / "02-Minhas-Aulas" / lesson
        detail = [p for p in path.rglob("*.md") if p.name != "00-Visao-geral.md"]
        self.assertEqual(len(detail), 1, detail)
        return detail[0].read_text(encoding="utf-8")

    def run_with_mock(self):
        with patch.object(GithubMapping, "_get", lambda client, repo, endpoint: self.github_get(client, repo, endpoint)), \
             patch.object(GithubCodeReader, "_raw", lambda reader, repo, sha, path, private: self.raw(reader, repo, sha, path, private)), \
             patch.object(GithubMapping, "resolve_sha",
                          side_effect=AssertionError("Never resolve moving branch")):
            return Publisher(self.db).rebuild()

    def test_frozen_old_commit_matches_old_code_even_when_head_is_newer(self):
        self.register_lesson()
        self.transcript()
        self.run_with_mock()
        text = self.note()
        self.assertIn("V3/old.ts", text)
        self.assertIn(OLD, text)
        self.assertIn("interval", text)
        self.assertNotIn("V3/new.ts", text)
        self.assertIn(f"git/trees/{OLD}?recursive=1", self.calls)
        self.assertFalse(any(HEAD in call for call in self.calls))
        projects = list((self.vault / "03-Meus-Projetos").glob("*.md"))
        self.assertTrue(any(OLD in p.read_text(encoding="utf-8") for p in projects))

    def test_unmapped_lesson_retains_global_relationship_and_warns(self):
        self.transcript("Aula-132")
        with patch.object(GithubMapping, "_get",
                          side_effect=AssertionError("Unmapped must be offline")):
            Publisher(self.db).rebuild()
        text = self.note("Aula-132")
        self.assertIn("V3/new.ts", text)
        self.assertIn("switchMap", text)
        self.assertIn("versão não congelada: relação pode não corresponder ao código desta aula", text)
        self.assertIn(HEAD, text)

    def test_pull_and_reindex_do_not_change_frozen_lesson_note(self):
        self.register_lesson()
        self.transcript()
        self.run_with_mock()
        before = self.note()
        self.db.save_repo(REPO, "course", PULLED, global_index("DestroyRef", PULLED),
                          "INDEXED")
        self.run_with_mock()
        after = self.note()
        self.assertEqual(before, after)
        self.assertIn(OLD, after)
        self.assertNotIn(PULLED, after)

    def test_registered_but_not_frozen_blocks_global_evidence(self):
        self.transcript()
        save_lessons(self.vault, {"Aula-131": {"professor": [{
            "id": "backend", "rotulo": "Professor", "repo": REPO,
            "ref_tipo": "branch", "ref": "main", "pasta": "V3"}], "dupla": []}})
        with patch.object(GithubMapping, "_get",
                          side_effect=AssertionError("Never inspect unfrozen code")):
            Publisher(self.db).rebuild()
        text = self.note()
        self.assertIn("congele a versão desta aula", text)
        self.assertNotIn("V3/new.ts", text)

    def test_snapshot_reused_for_two_lessons_same_sha_folder(self):
        for lesson in ("Aula-131", "Aula-132"):
            self.register_lesson(lesson)
            self.transcript(lesson)
        self.run_with_mock()
        self.assertEqual(self.calls.count(f"git/trees/{OLD}?recursive=1"), 1)
        self.assertIn("V3/old.ts", self.note("Aula-131"))
        self.assertIn("V3/old.ts", self.note("Aula-132"))
        self.calls.clear()
        self.run_with_mock()  # Fresh publisher, persisted index cache.
        self.assertEqual(self.calls.count(f"git/trees/{OLD}?recursive=1"), 0)


if __name__ == "__main__":
    unittest.main()
