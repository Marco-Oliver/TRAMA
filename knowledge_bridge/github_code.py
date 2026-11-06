"""Bounded, read-only GitHub REST code inspection at immutable commit SHAs.

No checkout, shell, arbitrary remote URL, redirects, or implicit branch refresh.
Git Trees are fetched once per reader/repository/SHA and only regular blobs are
eligible for content. Returned text is for local preview, not auto-publication.
"""
from __future__ import annotations

import base64
import binascii
import difflib
import hashlib
import re
from urllib import error, parse, request

from .github_mapping import GithubMapping, MappingError, _NoRedirect
from .lesson_code_config import _safe_path, _safe_repo

SHA_RE = re.compile(r"^[a-fA-F0-9]{40}$")
MAX_FILE = 300_000
MAX_FILES = 5000
MAX_DIFF = 140_000


def _sha(value):
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise MappingError("SHA Git inválido; selecione uma revisão congelada.")
    return value.lower()


def _path(value, allow_empty=False):
    if not _safe_path(value) or (not allow_empty and not value):
        raise MappingError("Caminho Git inválido ou fora do repositório.")
    return value


def _blob_sha(data):
    """Verify file bytes against their Git blob identity."""
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\x00" + data, usedforsecurity=False).hexdigest()


class GithubCodeReader:
    def __init__(self, client=None, cache=None):
        self.client = client if client is not None else GithubMapping()
        self.cache = cache
        self._trees = {}
        self._privacy = {}
        self._raw_opener = request.build_opener(_NoRedirect)

    def is_private(self, repo):
        if not _safe_repo(repo):
            raise MappingError("Repositório GitHub inválido.")
        if repo not in self._privacy:
            response = self.client._get(repo, "")
            if not isinstance(response, dict) or type(response.get("private")) is not bool:
                raise MappingError("GitHub não confirmou a privacidade do repositório.")
            self._privacy[repo] = response["private"]
        return self._privacy[repo]

    def tree(self, repo, sha):
        sha = _sha(sha)
        if not _safe_repo(repo):
            raise MappingError("Repositório GitHub inválido.")
        key = (repo, sha)
        if key not in self._trees:
            payload = self.client._get(repo, f"git/trees/{sha}?recursive=1")
            if (not isinstance(payload, dict) or not isinstance(payload.get("tree"), list)
                    or payload.get("truncated") or len(payload["tree"]) > 80000):
                raise MappingError("Árvore Git incompleta ou muito grande; não é seguro conferir arquivos.")
            files = {}
            for row in payload["tree"]:
                if not isinstance(row, dict) or row.get("type") != "blob" or row.get("mode") not in ("100644", "100755"):
                    continue  # Never follow symbolic links (120000) or submodules (160000).
                name, size, blob_sha = row.get("path"), row.get("size"), row.get("sha")
                if (_safe_path(name) and name and isinstance(size, int) and 0 <= size <= MAX_FILE
                        and isinstance(blob_sha, str) and SHA_RE.fullmatch(blob_sha)):
                    files[name] = {"size": size, "blob_sha": blob_sha.lower()}
            self._trees[key] = files
        return self._trees[key]

    def list_files(self, repo, sha, folder=""):
        folder = _path(folder, True)
        files = self.tree(repo, sha)
        prefix = folder + "/" if folder else ""
        filtered = [{"path": path, "size": data["size"]}
                    for path, data in sorted(files.items()) if path.startswith(prefix)]
        return {"sha": _sha(sha), "folder": folder, "files": filtered[:MAX_FILES],
                "truncated": len(filtered) > MAX_FILES}

    def _raw(self, repo, sha, path, private):
        owner, name = parse.urlsplit(repo.rstrip("/").removesuffix(".git")).path.strip("/").split("/")
        encoded = "/".join(parse.quote(part, safe="") for part in path.split("/"))
        url = (f"https://raw.githubusercontent.com/{parse.quote(owner, safe='')}/"
               f"{parse.quote(name, safe='')}/{sha}/{encoded}")
        headers = {"User-Agent": "TRAMA-code-reader", "Accept": "text/plain"}
        if private and self.client.token:
            headers["Authorization"] = "Bearer " + self.client.token
        try:
            with self._raw_opener.open(request.Request(url, headers=headers), timeout=20) as stream:
                size = stream.headers.get("Content-Length", "")
                if size.isdigit() and int(size) > MAX_FILE:
                    raise MappingError("Arquivo GitHub acima do limite de 300 KB.")
                data = stream.read(MAX_FILE + 1)
        except (error.URLError, TimeoutError, OSError):
            return None  # Fallback: GitHub Contents REST, never a redirect destination.
        return data

    def read_file(self, repo, sha, path):
        sha = _sha(sha)
        path = _path(path)
        file_info = self.tree(repo, sha).get(path)
        if file_info is None:
            raise MappingError("Arquivo não encontrado na árvore do SHA congelado.")
        private = self.is_private(repo)
        cache_key = ("file", repo, sha, path)
        data = self.cache.get(cache_key, private=private) if self.cache else None
        if data is None:
            data = self._raw(repo, sha, path, private)
            if data is None or len(data) > MAX_FILE or _blob_sha(data) != file_info["blob_sha"]:
                # Fall back to GitHub's authenticated Contents API at the exact SHA.
                endpoint = ("contents/" + parse.quote(path, safe="/") +
                            "?ref=" + parse.quote(sha, safe=""))
                response = self.client._get(repo, endpoint)
                if (not isinstance(response, dict) or response.get("type") != "file"
                        or response.get("encoding") != "base64"
                        or response.get("sha", "").lower() != file_info["blob_sha"]):
                    raise MappingError("Arquivo GitHub não corresponde ao blob da árvore congelada.")
                try:
                    data = base64.b64decode(response["content"], validate=False)
                except (ValueError, TypeError, binascii.Error, KeyError):
                    raise MappingError("Conteúdo GitHub inválido.") from None
                if len(data) > MAX_FILE or _blob_sha(data) != file_info["blob_sha"]:
                    raise MappingError("Conteúdo diverge do SHA congelado ou excede 300 KB.")
            if self.cache:
                self.cache.put(cache_key, data, private=private)
        if len(data) > MAX_FILE or _blob_sha(data) != file_info["blob_sha"]:
            raise MappingError("Cache corrompido ou conteúdo fora da revisão.")
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise MappingError("Arquivo binário ou texto que não está em UTF-8.") from None
        if "\x00" in content:
            raise MappingError("Arquivo binário não pode ser exibido como código.")
        return {"sha": sha, "path": path, "content": content,
                "size": len(data), "private": private, "blob_sha": file_info["blob_sha"]}

    def compare_commits(self, repo, base, head, folder=""):
        base, head, folder = _sha(base), _sha(head), _path(folder, True)
        if not _safe_repo(repo):
            raise MappingError("Repositório GitHub inválido.")
        result = self.client._get(repo, f"compare/{base}...{head}")
        if not isinstance(result, dict) or not isinstance(result.get("files"), list):
            raise MappingError("GitHub não retornou diferenças válidas.")
        prefix = folder + "/" if folder else ""
        filtered = []
        for file in result["files"]:
            if not isinstance(file, dict):
                continue
            path = file.get("filename")
            if not _safe_path(path) or not path.startswith(prefix):
                continue
            patch = file.get("patch") if isinstance(file.get("patch"), str) else ""
            filtered.append({"path": path, "status": str(file.get("status", ""))[:30],
                             "patch": patch[:MAX_DIFF], "changes": file.get("changes", 0)})
        return {"base": base, "head": head, "files": filtered[:100],
                "truncated": len(filtered) > 100 or bool(result.get("too_large")),
                "source": "github_compare_rest"}

    def diff_folders(self, repo, sha, before, after):
        sha, before, after = _sha(sha), _path(before), _path(after)
        if before == after:
            raise MappingError("Escolha duas pastas diferentes no mesmo commit.")
        tree = self.tree(repo, sha)  # exactly one recursive Git Trees REST request
        left_prefix, right_prefix = before + "/", after + "/"
        left = {path[len(left_prefix):]: path for path in tree if path.startswith(left_prefix)}
        right = {path[len(right_prefix):]: path for path in tree if path.startswith(right_prefix)}
        names = sorted(set(left) | set(right))
        results = []
        downloads = 0
        truncated = False
        # 40 *file downloads* total, rather than 40 two-sided comparisons (80).
        for relative in names:
            if len(results) >= 40:
                truncated = True
                break
            old_path, new_path = left.get(relative), right.get(relative)
            if (old_path and new_path and
                    tree[old_path]["blob_sha"] == tree[new_path]["blob_sha"]):
                continue
            needed = int(bool(old_path)) + int(bool(new_path))
            if downloads + needed > 40:
                truncated = True
                break
            downloads += needed
            old = self.read_file(repo, sha, old_path)["content"].splitlines(keepends=True) if old_path else []
            new = self.read_file(repo, sha, new_path)["content"].splitlines(keepends=True) if new_path else []
            if old == new:
                continue
            patch = "".join(difflib.unified_diff(old, new, fromfile=old_path or "(ausente)",
                                                 tofile=new_path or "(ausente)", n=3))
            results.append({"path": relative, "status": ("modified" if old_path and new_path else
                            "removed" if old_path else "added"), "patch": patch[:MAX_DIFF]})
        return {"sha": sha, "before": before, "after": after, "files": results,
                "truncated": truncated, "downloads": downloads, "source": "local_folder_diff"}
