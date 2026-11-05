"""Assistente de sugestões GitHub: fonte pública REST, somente leitura e sem gravação.

As datas dos commits são evidências Git; a data do post Classroom é apenas
um indício da data de gravação. Não transformar sugestões em vínculos sem aceite.
"""
from __future__ import annotations

from datetime import date, datetime
import json
import os
import re
from urllib import error, parse, request

from .lesson_code_config import _safe_repo, lesson_dates

MAX_RESPONSE = 9_000_000


class MappingError(ValueError):
    pass


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _candidate_id(kind, ref, path=""):
    return kind + ":" + ref + (":" + path if path else "")


def _version(path):
    return bool(re.fullmatch(r"V\d{1,3}(?:[._-]\d{1,3})?", path, re.I))


class GithubMapping:
    def __init__(self, token=None):
        self.token = token if token is not None else os.environ.get("TRAMA_GITHUB_TOKEN", "").strip()
        self.rate = {"restantes": None, "limite": None, "reset": None, "consultas": 0}
        self._opener = request.build_opener(_NoRedirect)

    def _get(self, repo, endpoint):
        if not _safe_repo(repo):
            raise MappingError("Use um link HTTPS de repositório github.com, sem credenciais.")
        parts = parse.urlsplit(repo.rstrip("/").removesuffix(".git")).path.strip("/").split("/")
        owner, name = parts
        url = f"https://api.github.com/repos/{parse.quote(owner)}/{parse.quote(name)}/{endpoint}"
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "TRAMA-lesson-mapper"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = request.Request(url, headers=headers)
        try:
            with self._opener.open(req, timeout=20) as response:
                self.rate["consultas"] += 1
                for key, header in (("restantes", "X-RateLimit-Remaining"),
                                    ("limite", "X-RateLimit-Limit"),
                                    ("reset", "X-RateLimit-Reset")):
                    raw = response.headers.get(header)
                    if raw is not None and raw.isdigit():
                        self.rate[key] = int(raw)
                size = response.headers.get("Content-Length", "")
                if size.isdigit() and int(size) > MAX_RESPONSE:
                    raise MappingError("Resposta GitHub grande demais para o assistente.")
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise MappingError("Resposta GitHub excede 9 MB.")
                return json.loads(raw.decode("utf-8"))
        except error.HTTPError as exc:
            self.rate["consultas"] += 1
            for key, header in (("restantes", "X-RateLimit-Remaining"),
                                ("limite", "X-RateLimit-Limit"),
                                ("reset", "X-RateLimit-Reset")):
                raw = exc.headers.get(header) if exc.headers else None
                if raw is not None and raw.isdigit():
                    self.rate[key] = int(raw)
            if exc.code in (401, 404):
                raise MappingError("Repositório não encontrado ou sem permissão. Para repos privados configure TRAMA_GITHUB_TOKEN.") from None
            if exc.code in (403, 429):
                raise MappingError("GitHub recusou a consulta (cota ou permissão). Configure TRAMA_GITHUB_TOKEN e tente novamente.") from None
            raise MappingError(f"GitHub retornou HTTP {exc.code}; repositório não consultado.") from None
        except (error.URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError):
            raise MappingError("Não foi possível consultar a API REST do GitHub.") from None

    def catalogue(self, repo):
        """Up to 300 recent commits in three pages, tags and ONE recursive tree.

        Pagination is capped and stops early near the unauthenticated rate limit.
        Older classes beyond this window remain unguessed and can be mapped manually.
        """
        if not _safe_repo(repo):
            raise MappingError("URL de repositório inválida.")
        first = self._get(repo, "commits?per_page=100")
        if not isinstance(first, list):
            raise MappingError("Formato inesperado da API de commits.")
        commits = list(first)
        batch = first
        history_partial = False
        for page in (2, 3):
            if len(batch) < 100:
                break
            remaining = self.rate.get("restantes")
            if isinstance(remaining, int) and remaining <= 5:
                history_partial = True
                break
            try:
                batch = self._get(repo, f"commits?per_page=100&page={page}")
            except MappingError:
                history_partial = True
                break
            if not isinstance(batch, list):
                history_partial = True
                break
            commits.extend(batch)
        history_partial = history_partial or len(commits) >= 300
        tags = self._get(repo, "tags?per_page=100")
        if not isinstance(tags, list):
            raise MappingError("Formato inesperado da API de tags.")
        candidates = []
        dates = {}
        version_dates = {}  # Inferred from commit SUBJECT, not proof that a folder was created then.
        for item in commits[:300]:
            if not isinstance(item, dict):
                continue
            sha = item.get("sha", "")
            if not re.fullmatch(r"[a-fA-F0-9]{40}", str(sha)):
                continue
            meta = item.get("commit") or {}
            info = meta.get("committer") or meta.get("author") or {}
            when = _date(info.get("date"))
            subject = str(meta.get("message", "")).splitlines()[0][:130]
            dates[sha] = when
            # A commit mentioning V3 might refer to a folder V3, but is only
            # a weak clue. Preserve provenance in candidate labels.
            if when:
                for version in re.findall(r"(?i)(?<![A-Za-z0-9])V[0-9]{1,3}(?![A-Za-z0-9])", subject):
                    version_dates.setdefault(version.casefold(), when)
            candidates.append({"id": _candidate_id("commit", sha), "tipo": "commit",
                               "ref_tipo": "commit", "ref": sha, "pasta": "",
                               "data": when, "rotulo": f"Commit {sha[:9]} — {subject}",
                               "fonte_data": "git_commit", "sugestao_anterior": None})
        if not dates:
            raise MappingError("O repositório não tem commits acessíveis.")
        newest_sha = next(iter(dates))
        for tag in tags[:100]:
            name = tag.get("name") if isinstance(tag, dict) else ""
            sha = (tag.get("commit") or {}).get("sha", "") if isinstance(tag, dict) else ""
            if not isinstance(name, str) or not 1 <= len(name) <= 160:
                continue
            # Annotated tags can point to tag objects; date remains unknown.
            when = dates.get(sha, "")
            candidates.append({"id": _candidate_id("tag", name), "tipo": "tag",
                               "ref_tipo": "tag", "ref": name, "pasta": "",
                               "data": when, "rotulo": f"Tag {name}",
                               "fonte_data": "git_commit" if when else "sem_data_verificada",
                               "sugestao_anterior": None})
        tree = self._get(repo, f"git/trees/{newest_sha}?recursive=1")
        if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
            raise MappingError("Não foi possível obter a árvore Git da revisão.")
        dirs = set()
        for entry in tree["tree"][:80000]:
            if not isinstance(entry, dict) or entry.get("type") != "tree":
                continue
            path = entry.get("path", "")
            if isinstance(path, str) and path and _version(path.rsplit("/", 1)[-1]):
                dirs.add(path)
        # Git Trees doesn't provide folder creation dates. Never invent them.
        for folder in sorted(dirs)[:200]:
            hint = version_dates.get(folder.rsplit("/", 1)[-1].casefold(), "")
            candidates.append({"id": _candidate_id("pasta", newest_sha, folder),
                               "tipo": "pasta", "ref_tipo": "commit",
                               "ref": newest_sha, "pasta": folder, "data": hint,
                               "rotulo": f"Pasta {folder} (revisão {newest_sha[:9]})",
                               "fonte_data": "mensagem_commit_indicativa" if hint else "sem_data_verificada",
                               "sugestao_anterior": None})
        by_path = {x["pasta"]: x for x in candidates if x["tipo"] == "pasta"}
        for candidate in by_path.values():
            path = candidate["pasta"]
            match = re.search(r"(?i)^V(\d+)$", path.rsplit("/", 1)[-1])
            if not match or int(match.group(1)) <= 1:
                continue
            previous = path.rsplit("/", 1)
            older = (previous[0] + "/" if len(previous) == 2 else "") + "V" + str(int(match.group(1)) - 1)
            if older in by_path:
                candidate["sugestao_anterior"] = {"ref_tipo": "commit", "ref": newest_sha,
                                                   "pasta": older}
        return {"candidatos": candidates[:650], "truncado": bool(tree.get("truncated")),
                "historico_parcial": history_partial,
                "limite_amostra": {"commits": 300, "tags": 100},
                "taxa": self.rate, "autenticado": bool(self.token)}

    @staticmethod
    def suggestions(catalogue, lessons, overrides=None):
        """Somente ordena sugestões; a interface decide quais serão gravadas."""
        overrides = overrides or {}
        candidates = catalogue.get("candidatos", [])
        results = []
        for lesson in lessons[:500]:
            name = lesson["aula"]
            given = overrides.get(name, lesson.get("data") or "")
            day = ""
            if given:
                try:
                    day = date.fromisoformat(given).isoformat()
                except (ValueError, TypeError):
                    day = ""
            dated = []
            if day:
                for c in candidates:
                    if not c.get("data"):
                        continue
                    try:
                        delta = (date.fromisoformat(day) - date.fromisoformat(c["data"])).days
                    except ValueError:
                        continue
                    dated.append((abs(delta), 0 if delta >= 0 else 1,
                                  {'pasta': 0, 'tag': 1, 'commit': 2}.get(c.get('tipo'), 3), c))
                dated.sort(key=lambda item: (item[0], item[1]))
            best = dated[0][3]["id"] if dated and dated[0][0] <= 30 else ""
            results.append({"aula": name, "data": day,
                            "origem_data": "informada_usuario" if name in overrides else lesson.get("origem_data", ""),
                            "candidato_id": best,
                            "motivo": ("Data próxima (não comprova correspondência)" if best else
                                       "Sem sugestão confiável; selecione manualmente")})
        return results


def preview_mapping(vault, repo, overrides=None):
    catalogue = GithubMapping().catalogue(repo)
    lessons = lesson_dates(vault)
    return {**catalogue, "aulas": GithubMapping.suggestions(catalogue, lessons, overrides),
            "repo": repo.rstrip("/").removesuffix(".git")}
