"""Offline, content-cache, rate-limit and publication performance regressions."""
from __future__ import annotations

import hashlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from knowledge_bridge.github_cache import GithubCache
from knowledge_bridge.github_code import GithubCodeReader
from knowledge_bridge.github_lesson_index import LessonRepositoryIndex
from knowledge_bridge.github_mapping import GithubMapping, GithubRateLimitError, MappingError
from knowledge_bridge.lesson_code_config import save_lessons, read_config
from knowledge_bridge.publishing import Publisher
from knowledge_bridge.store import Store

REPO = "https://github.com/example/course"
A = "a" * 40
B = "b" * 40
OLD = b"import { interval } from 'rxjs';\nconst ticks=interval(1000);\n"


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\x00" + data,
                        usedforsecurity=False).hexdigest()


def mapped(lesson):
    return {"professor": [{"id": "teacher", "rotulo": "Professor", "repo": REPO,
                           "ref_tipo": "branch", "ref": "main", "pasta": "V3"}],
            "dupla": []}


class FrozenOfflineAndPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.cache_dir = self.root / "cache"
        self.patch_cache = patch("knowledge_bridge.github_cache.DATA_HOME", self.root)
        self.patch_cache.start()
        self.addCleanup(self.patch_cache.stop)
        self.store = Store(self.vault)
        self.addCleanup(self.store.close)
        self.calls = []
        self.original = self.vault / "99-Anexos/Transcricoes-Originais/Aula-131-V01.txt"
        Publisher(self.store)
        self.original.write_text("00:01 O professor explicou interval().\n", encoding="utf-8")
        digest = hashlib.sha256(self.original.read_bytes()).hexdigest()
        self.store.upsert_source({"id": "lesson", "kind": "transcript",
            "original_path": str(self.original), "label": self.original.name,
            "lesson": "Aula-131", "video": "V01", "digest": digest,
            "stored_path": self.original.relative_to(self.vault).as_posix()})
        save_lessons(self.vault, {"Aula-131": mapped("Aula-131")})
        self.store.freeze_github_ref("Aula-131", "professor", "teacher", "current",
                                     REPO, "branch", "main", "V3", A, private=False)

    def get(self, client, repo, endpoint):
        self.calls.append(endpoint)
        if endpoint == f"git/trees/{A}?recursive=1":
            return {"truncated": False, "tree": [{
                "type": "blob", "mode": "100644",
                "path": "V3/old.ts", "size": len(OLD), "sha": blob(OLD)}]}
        raise AssertionError("Unexpected HTTP: " + endpoint)

    def raw(self, reader, repo, sha, path, private):
        self.assertEqual((sha, path, private), (A, "V3/old.ts", False))
        return OLD

    def build_online(self):
        with patch.object(GithubMapping, "_get",
                          lambda client, repo, endpoint: self.get(client, repo, endpoint)), \
             patch.object(GithubCodeReader, "_raw",
                          lambda reader, repo, sha, path, private: self.raw(reader, repo, sha, path, private)):
            Publisher(self.store).rebuild()

    def note(self):
        return next(p for p in (self.vault / "02-Minhas-Aulas/Aula-131").glob("*.md")
                    if p.name != "00-Visao-geral.md")

    def section(self):
        data = self.note().read_text(encoding="utf-8")
        return data.split("## Relações com códigos e projetos", 1)[1].split(
            "## Termos suspeitos da transcrição", 1)[0]

    def test_cache_first_frozen_note_and_metadata_remain_offline(self):
        self.build_online()
        initial = self.note().read_bytes()
        self.calls.clear()
        with patch.object(GithubMapping, "_get",
                          side_effect=AssertionError("Not even private metadata online")), \
             patch.object(GithubCodeReader, "_raw",
                          side_effect=AssertionError("No blob download")):
            Publisher(self.store).rebuild()
        self.assertEqual(initial, self.note().read_bytes())
        self.assertIn("V3/old.ts", self.note().read_text(encoding="utf-8"))
        self.assertEqual(self.calls, [])

    def test_cache_miss_preserves_previous_code_section_with_warning(self):
        self.build_online()
        before = self.section()
        for file in (self.root / "github-cache").glob("*.entry"):
            file.unlink()
        with patch.object(GithubMapping, "_get",
                          side_effect=MappingError("Rede indisponível")):
            Publisher(self.store).rebuild()
        after = self.section()
        self.assertIn("V3/old.ts", after)
        self.assertIn("/blob/" + A + "/", after)
        self.assertIn("TRAMA (offline)", after)
        self.assertEqual(before.strip(), after.split("> **TRAMA (offline):**")[0].strip())
        overview = (self.vault / "02-Minhas-Aulas/Aula-131/00-Visao-geral.md").read_text(encoding="utf-8")
        self.assertIn("TRAMA (offline)", overview)
        self.assertIn("V3/old.ts", overview)

    def test_old_sqlite_schema_is_migrated_without_losing_sha(self):
        # Exercise upgrade on a new DB with the column removed from an old schema.
        import sqlite3
        vault = self.root / "old-vault"
        vault.mkdir()
        database = vault / ".base-conhecimento"
        database.mkdir()
        con = sqlite3.connect(database / "estado.sqlite3")
        con.execute("""CREATE TABLE github_lesson_refs
          (lesson TEXT, role TEXT, repository_id TEXT, slot TEXT,
           repo_url TEXT, ref_kind TEXT, ref_name TEXT, folder TEXT,
           commit_sha TEXT, frozen_at TEXT)""")
        con.execute("INSERT INTO github_lesson_refs VALUES (?,?,?,?,?,?,?,?,?,?)",
                    ("Aula-131", "professor", "teacher", "current", REPO,
                     "branch", "main", "V3", A, "yesterday"))
        con.commit()
        con.close()
        migrated = Store(vault)
        try:
            row = migrated.github_ref("Aula-131", "professor", "teacher")
            self.assertEqual(row["commit_sha"], A)
            self.assertIsNone(row["private"])
            migrated.freeze_github_ref("Aula-131", "professor", "teacher", "current",
                                       REPO, "branch", "main", "V3", B, private=True)
            row = migrated.github_ref("Aula-131", "professor", "teacher")
            self.assertEqual((row["commit_sha"], row["private"]), (A, 1))
        finally:
            migrated.close()

    def test_one_config_and_payload_read_per_publication_memo(self):
        pub = Publisher(self.store)
        with patch("knowledge_bridge.lesson_code_config.read_config", wraps=read_config) as config, \
             patch.object(self.store, "repositories", wraps=self.store.repositories) as repos:
            pub.lesson_repo_index.begin_run()
            first = pub._lesson_repos("Aula-131")
            second = pub._lesson_repos("Aula-131")
        self.assertIs(first, second)
        self.assertEqual(config.call_count, 1)
        self.assertEqual(repos.call_count, 1)

    def test_bulk_without_token_warns_before_remote_snapshots(self):
        save_lessons(self.vault, {f"Aula-{n:03d}": mapped(n) for n in range(131, 137)})
        index = LessonRepositoryIndex(self.store)
        index.begin_run()
        self.assertTrue(index._no_token_bulk)
        with patch.object(GithubMapping, "_get",
                          side_effect=AssertionError("Bulk must warn BEFORE requests")) as get:
            index.for_lesson("Aula-131")
            get.assert_not_called()
        self.assertIn("configure o token do GitHub", index.warning("Aula-131"))
        self.assertIn("Aula-131", index.failed_lessons)


class ContentBlobCacheTests(unittest.TestCase):
    def test_two_commits_nine_identical_files_only_eleven_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = GithubCache(root=Path(tmp) / "blobs")
            old = {f"src/f{i}.ts": f"export const n{i} = {i};\n".encode()
                   for i in range(10)}
            new = dict(old)
            new["src/f9.ts"] = b"export const n9 = 99;\n"
            trees = {A: old, B: new}

            class Api:
                token = "token-present"
                def _get(self, repo, endpoint):
                    for sha, mapping in trees.items():
                        if endpoint == f"git/trees/{sha}?recursive=1":
                            return {"truncated": False, "tree": [{
                                "type": "blob", "mode": "100644", "path": path,
                                "size": len(data), "sha": blob(data)}
                                for path, data in mapping.items()]}
                    raise AssertionError(endpoint)

            reader = GithubCodeReader(Api(), cache=cache)
            reader._privacy[REPO] = False
            downloads = []

            def fake_raw(repo, sha, path, private):
                downloads.append((sha, path))
                return trees[sha][path]

            with patch.object(reader, "_raw", side_effect=fake_raw):
                for sha in (A, B):
                    for path in sorted(trees[sha]):
                        reader.read_file(REPO, sha, path)
            self.assertEqual(len(downloads), 11)
            self.assertEqual(len([x for x in downloads if x[0] == B]), 1)

    def test_private_cache_never_falls_back_to_public_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = GithubCache(root=Path(tmp) / "cache")
            key = ("git-blob-v2", blob(OLD))
            cache.put(key, OLD, private=False)
            self.assertIsNone(cache.get(key, private=True))


class GithubRateLimitTests(unittest.TestCase):
    def test_403_429_stop_with_retry_timestamp_from_headers(self):
        for code in (403, 429):
            with self.subTest(code=code):
                client = GithubMapping(token="")
                reset = str(int(time.time()) + 120)
                error = HTTPError("https://api.github.com/", code, "rate limit",
                                  {"X-RateLimit-Reset": reset, "X-RateLimit-Remaining": "0"},
                                  io.BytesIO())
                opener = Mock()
                opener.open.side_effect = error
                client._opener = opener
                with self.assertRaises(GithubRateLimitError) as first:
                    client._get(REPO, "git/trees/" + A)
                self.assertIn("tente novamente após", str(first.exception))
                with self.assertRaises(GithubRateLimitError):
                    client._get(REPO, "git/trees/" + B)
                self.assertEqual(opener.open.call_count, 1)

    def test_rate_limit_does_not_turn_frozen_lesson_into_no_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            db = Store(vault)
            try:
                save_lessons(vault, {"Aula-131": mapped("Aula-131")})
                db.freeze_github_ref("Aula-131", "professor", "teacher", "current",
                                     REPO, "branch", "main", "V3", A, private=False)
                index = LessonRepositoryIndex(db)
                index.begin_run()
                count = []
                def refused(client, repo, endpoint):
                    count.append(endpoint)
                    raise GithubRateLimitError(time.time() + 120, 429)
                with patch.object(GithubMapping, "_get", refused):
                    self.assertEqual(index.for_lesson("Aula-131"), [])
                self.assertEqual(len(count), 1)
                self.assertIn("tente novamente após", index.warning("Aula-131"))
                self.assertIn("Aula-131", index.failed_lessons)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
