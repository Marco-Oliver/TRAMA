"""Per-lesson immutable GitHub code indices; never compare a frozen lesson to HEAD.

The index is cached by (repository URL, commit SHA, folder), outside the vault.
Private content uses GithubCache's Windows DPAPI policy; there is no plaintext
cache or checkout of private code.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

from .code_intel import (DOC_EXTS, MAX_FILE_BYTES, SENSITIVE_NAMES,
                         SOURCE_EXTS, index_repository)
from .github_cache import GithubCache
from .github_code import GithubCodeReader
from .github_mapping import MappingError


class LessonRepositoryIndex:
    """Choose either a frozen per-lesson snapshot or the original global index."""

    def __init__(self, store, reader=None, cache=None):
        self.store = store
        self.cache = cache if cache is not None else GithubCache(vault=store.vault)
        self.reader = reader if reader is not None else GithubCodeReader(cache=self.cache)
        self._snapshots = {}
        self.errors = {}

    @staticmethod
    def _key(repo, sha, folder):
        return (repo.rstrip("/").removesuffix(".git").casefold(), sha.lower(), folder)

    def _snapshot(self, repo, sha, folder):
        key = self._key(repo, sha, folder)
        if key in self._snapshots:
            return self._snapshots[key]
        private = self.reader.is_private(repo)
        cache_key = ("lesson-index-v1", *key)
        saved = self.cache.get(cache_key, private=private)
        if saved:
            try:
                decoder = zlib.decompressobj()
                raw = decoder.decompress(saved, 2_000_001)
                if len(raw) <= 2_000_000 and decoder.eof and not decoder.unconsumed_tail:
                    parsed = json.loads(raw)
                    if (isinstance(parsed, dict)
                            and parsed.get("identity") == list(key)
                            and isinstance(parsed.get("index"), dict)):
                        self._snapshots[key] = parsed["index"]
                        return parsed["index"]
            except (ValueError, TypeError, zlib.error, UnicodeDecodeError):
                pass

        listing = self.reader.list_files(repo, sha, folder)
        # A truncated list would silently omit files that might change matches.
        if listing["truncated"]:
            raise MappingError("Árvore congelada incompleta; índice da aula não publicado.")
        candidates = []
        for item in listing["files"]:
            path = item["path"]
            suffix = Path(path).suffix.lower()
            if (not isinstance(item.get("size"), int) or item["size"] > MAX_FILE_BYTES
                    or suffix not in SOURCE_EXTS | DOC_EXTS | {".json"}
                    or any(word in path.casefold() for word in SENSITIVE_NAMES)):
                continue
            candidates.append(path)

        def source(path):
            try:
                row = self.reader.read_file(repo, sha, path)
            except MappingError as exc:
                if "Arquivo binário" in str(exc) or "UTF-8" in str(exc):
                    return None
                raise
            return row["content"], row["size"]

        payload = index_repository(Path("."), candidates, read_source=source)
        self._snapshots[key] = payload
        packed = zlib.compress(json.dumps({"identity": list(key), "index": payload},
                                          ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.cache.put(cache_key, packed, private=private)
        return payload

    def for_lesson(self, lesson):
        count, frozen = self.store.github_lesson_refs(lesson)
        self.errors.pop(lesson, None)
        if count == 0:
            # Never change legacy connections for lessons without a GitHub mapping.
            return [({**dict(repo), "frozen": False, "folder": ""},
                     json.loads(repo["payload"])) for repo in self.store.repositories()]
        if count < 0:
            self.errors[lesson] = "Cadastro GitHub inválido; relações de código bloqueadas."
            return []
        if count > len(frozen):
            self.errors[lesson] = "congele a versão desta aula"
        result = []
        seen = set()
        for row in frozen:
            key = self._key(row["repo_url"], row["commit_sha"], row["folder"])
            if key in seen:
                continue
            seen.add(key)
            try:
                payload = self._snapshot(row["repo_url"], row["commit_sha"], row["folder"])
            except (MappingError, ValueError, OSError, RuntimeError) as exc:
                self.errors[lesson] = ("Índice da versão congelada indisponível; "
                                       "nenhuma relação foi substituída pelo HEAD: "
                                       + str(exc)[:110])
                continue
            url = row["repo_url"]
            result.append(({
                "url": url, "sha": row["commit_sha"],
                "name": url.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1],
                "status": "FROZEN", "folder": row["folder"], "frozen": True,
            }, payload))
        return result

    def warning(self, lesson):
        count, frozen = self.store.github_lesson_refs(lesson)
        if count == 0:
            return "versão não congelada: relação pode não corresponder ao código desta aula"
        if count < 0:
            return "Cadastro GitHub inválido; código não vinculado."
        if lesson in self.errors:
            return self.errors[lesson]
        if count > len(frozen):
            return "Código GitHub pendente: congele a versão desta aula."
        return ""
