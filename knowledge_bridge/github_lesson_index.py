"""Immutable GitHub lesson indices, cached offline before any network request.

A registered lesson compares only its frozen commit/folder. Private objects are
cached only through the encrypted GithubCache namespace, never as plaintext.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

from .code_intel import DOC_EXTS, MAX_FILE_BYTES, SENSITIVE_NAMES, SOURCE_EXTS, index_repository
from .github_cache import GithubCache
from .github_code import GithubCodeReader
from .github_mapping import MappingError, GithubRateLimitError


class LessonRepositoryIndex:
    """Select frozen snapshots or the historic global index for unmapped lessons."""

    def __init__(self, store, reader=None, cache=None):
        self.store = store
        self.cache = cache if cache is not None else GithubCache(vault=store.vault)
        self.reader = reader if reader is not None else GithubCodeReader(cache=self.cache)
        self._snapshots = {}
        self.errors = {}
        self.failed_lessons = set()
        self.notices = {}
        self._config = None
        self._global = None
        self._status = {}
        self._auto_none = set()
        self._auto_waiting = False
        self._rate_error = None
        self._no_token_bulk = False

    @staticmethod
    def _key(repo, sha, folder):
        return (repo.rstrip("/").removesuffix(".git").casefold(), sha.lower(), folder)

    def begin_run(self):
        """One config read and one global payload decode per publication."""
        from .lesson_code_config import read_config
        self._config = read_config(self.store.vault)
        self._global = [({**dict(repo), "frozen": False, "folder": ""},
                         json.loads(repo["payload"])) for repo in self.store.repositories()]
        self._status.clear()
        auto_repos = self.store.auto_repositories()
        self._auto_none = {lesson for row in auto_repos
            for lesson, decision in self.store.automatic_decisions(row["repo_url"]).items()
            if decision["decision"] == "none"}
        self._auto_waiting = any(row["status"] in
                                 ("pending","paused","index_paused") for row in auto_repos)
        self.errors.clear()
        self.failed_lessons.clear()
        self.notices.clear()
        self._rate_error = None
        registered = self._config.get("aulas", {})
        self._no_token_bulk = (len(registered) >= 5 and
                               not bool(getattr(self.reader.client, "token", "")))

    def _cached_snapshot(self, key, private):
        cache_key = ("lesson-index-v3", *key)
        saved = self.cache.get(cache_key, private=private)
        if not saved:
            return None
        try:
            decoder = zlib.decompressobj()
            raw = decoder.decompress(saved, 2_000_001)
            if (len(raw) > 2_000_000 or not decoder.eof or
                    decoder.unconsumed_tail or decoder.unused_data):
                return None
            parsed = json.loads(raw)
            if (isinstance(parsed, dict) and parsed.get("identity") == list(key)
                    and isinstance(parsed.get("index"), dict)):
                return parsed["index"]
        except (ValueError, TypeError, UnicodeDecodeError, zlib.error):
            pass
        return None

    def _snapshot(self, repo, sha, folder, private):
        key = self._key(repo, sha, folder)
        if key in self._snapshots:
            return self._snapshots[key]

        # New locks have a verified public/private bit. It must be used BEFORE
        # any GitHub metadata query, so the encrypted snapshot works offline.
        if private is None:
            if self._rate_error:
                raise self._rate_error
            if self._no_token_bulk:
                raise MappingError(
                    "configure o token do GitHub antes de verificar a privacidade "
                    "das revisões antigas em lote.")
            private = self.reader.is_private(repo)  # migration of old locks
            # Never assume an old, unknown-private lock is public.
        if type(private) is not bool:
            raise MappingError("Visibilidade do repositório não confirmada; recongele a privacidade online.")

        cached = self._cached_snapshot(key, private)
        if cached is not None:
            self._snapshots[key] = cached
            return cached
        if self._rate_error:
            raise self._rate_error
        if self._no_token_bulk:
            raise MappingError(
                "configure o token do GitHub antes de montar índices de muitas aulas; "
                "sem token, somente revisões já guardadas no cache serão usadas.")

        self.reader._privacy[repo] = private
        listing = self.reader.list_files(repo, sha, folder)
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

        # Snapshot schema v2 includes verified identifiers/call sites so
        # phonetic corrections are never resolved against moving HEAD.
        payload = index_repository(Path("."), candidates, read_source=source)
        self._snapshots[key] = payload
        packed = zlib.compress(json.dumps(
            {"identity": list(key), "index": payload},
            ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.cache.put(("lesson-index-v3", *key), packed, private=private)
        return payload

    def for_lesson(self, lesson):
        if self._config is None:
            self.begin_run()
        if lesson in self._status:
            return self._status[lesson][2]

        count, frozen = self.store.github_lesson_refs(lesson, config=self._config)
        self.errors.pop(lesson, None)
        if count == 0:
            if self._auto_waiting and lesson not in self._auto_none:
                self.notices[lesson] = (
                    "Associação GitHub pendente por limite de cota ou rede; "
                    "isso não significa que esta aula não tenha código.")
            # Explicitly excluded revision lessons do not acquire fake links
            # merely because a moving global HEAD happens to contain a term.
            chosen = [] if lesson in self._auto_none else self._global
            self._status[lesson] = (count, frozen, chosen)
            return chosen
        if count < 0:
            self.errors[lesson] = "Cadastro GitHub inválido; relações de código bloqueadas."
            self._status[lesson] = (count, frozen, [])
            return []

        if self._no_token_bulk:
            self.notices[lesson] = ("Há muitas aulas com código: configure o token do GitHub "
                                   "antes de montar índices em lote para evitar limite de consultas.")
        if count > len(frozen):
            self.errors[lesson] = "congele a versão desta aula"

        result = []
        seen = set()
        for row in frozen:
            key = self._key(row["repo_url"], row["commit_sha"], row["folder"])
            if key in seen:
                continue
            seen.add(key)
            privacy = row["private"]
            private = None if privacy is None else bool(privacy)
            try:
                payload = self._snapshot(row["repo_url"], row["commit_sha"], row["folder"], private)
            except GithubRateLimitError as exc:
                self._rate_error = exc  # no more remote calls this publication
                self.failed_lessons.add(lesson)
                self.errors[lesson] = str(exc)
                continue
            except (MappingError, ValueError, OSError, RuntimeError) as exc:
                self.failed_lessons.add(lesson)
                self.errors[lesson] = ("Índice congelado indisponível (sem fallback para HEAD): "
                                       + str(exc)[:190])
                continue
            url = row["repo_url"]
            result.append(({
                "url": url, "sha": row["commit_sha"],
                "name": url.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1],
                "status": "FROZEN", "folder": row["folder"], "frozen": True,
                "origin": row["origem"], "confidence": row["confianca"],
                "version": row["ref_name"],
            }, payload))
        self._status[lesson] = (count, frozen, result)
        return result

    def warning(self, lesson):
        if lesson not in self._status:
            self.for_lesson(lesson)
        count, frozen, _ = self._status[lesson]
        if count == 0:
            if lesson in self._auto_none:
                return "Aula sem relação verificável com as versões do código."
            if lesson in self.notices:
                return self.notices[lesson]
            return "versão não congelada: relação pode não corresponder ao código desta aula"
        messages = []
        if count < 0:
            messages.append("Cadastro GitHub inválido; código não vinculado.")
        if lesson in self.errors:
            messages.append(self.errors[lesson])
        elif count > len(frozen):
            messages.append("Código GitHub pendente: congele a versão desta aula.")
        if lesson in self.notices:
            messages.append(self.notices[lesson])
        for row in frozen:
            if row.get("origem") == "automatica":
                messages.append("Versão " + str(row["ref_name"]) +
                                " associada automaticamente; confiança " +
                                str(row["confianca"]) + ".")
                if row["confianca"] == "baixa":
                    messages.append("versão estimada; confira")
        return " ".join(messages)
