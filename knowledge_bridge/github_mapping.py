"""Assistente de sugestões GitHub: fonte pública REST, somente leitura e sem gravação.

As datas dos commits são evidências Git; a data do post Classroom é apenas
um indício da data de gravação. Não transformar sugestões em vínculos sem aceite.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import time
import json
import os
import re
from urllib import error, parse, request

from .lesson_code_config import _safe_repo, lesson_dates

MAX_RESPONSE = 9_000_000


class MappingError(ValueError):
    pass


class GithubRateLimitError(MappingError):
    """A 403/429 stops further remote work; reset information stays visible."""
    def __init__(self, retry_at=None, code=429):
        self.retry_at = retry_at
        self.code = code
        if retry_at is not None:
            when = datetime.fromtimestamp(retry_at, timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
            detail = "tente novamente após " + when
        else:
            detail = "GitHub não informou o horário de retomada; configure o token do GitHub ou revise a permissão"
        super().__init__(f"GitHub HTTP {code}: cota ou acesso bloqueado; {detail}.")


def github_limit_error(code, headers=None):
    """Prefer Retry-After, then GitHub reset epoch; do not invent a reset time."""
    headers = headers or {}
    retry_at = None
    retry = headers.get("Retry-After", "")
    if isinstance(retry, str) and retry.strip():
        if retry.strip().isdigit():
            retry_at = time.time() + min(int(retry.strip()), 86400 * 7)
        else:
            try:
                retry_at = parsedate_to_datetime(retry).timestamp()
            except (ValueError, TypeError, OverflowError):
                pass
    if retry_at is None:
        reset = headers.get("X-RateLimit-Reset", "")
        if str(reset).isdigit():
            retry_at = int(reset)
    return GithubRateLimitError(retry_at=retry_at, code=code)


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
        if token is None:
            token = os.environ.get("TRAMA_GITHUB_TOKEN", "").strip()
            if not token:
                try:
                    from .paths import DATA_HOME
                    from .secure_keys import KeyVault
                    token = KeyVault(DATA_HOME / "api_keys.dpapi.json").get_github_token()
                except (OSError, ValueError, RuntimeError):
                    token = ""
        self.token = token
        self.rate = {"restantes": None, "limite": None, "reset": None, "consultas": 0}
        self._quota_error = None
        self._opener = request.build_opener(_NoRedirect)

    def _get(self, repo, endpoint):
        if self._quota_error is not None:
            raise self._quota_error
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
            if exc.code in (301, 302, 307, 308):
                raise MappingError("O repositório mudou de nome/endereço (redirecionamento HTTP); atualize o link do GitHub manualmente.") from None
            if exc.code in (401, 404):
                raise MappingError("Repositório não encontrado ou sem permissão. Para repos privados configure TRAMA_GITHUB_TOKEN.") from None
            if exc.code in (403, 429):
                self._quota_error = github_limit_error(exc.code, exc.headers)
                raise self._quota_error from None
            raise MappingError(f"GitHub retornou HTTP {exc.code}; repositório não consultado.") from None
        except (error.URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError):
            raise MappingError("Não foi possível consultar a API REST do GitHub.") from None

    @staticmethod
    def _date_windows(lessons, overrides=None):
        """Windows covering ±30 days of each known lecture date, oldest first."""
        overrides = overrides or {}
        spans = []
        for item in lessons or []:
            if not isinstance(item, dict):
                continue
            name = item.get("aula")
            value = overrides.get(name, item.get("data", ""))
            try:
                day = date.fromisoformat(value)
            except (TypeError, ValueError):
                continue
            spans.append((day - timedelta(days=30), day + timedelta(days=30)))
        spans.sort()
        merged = []
        for first, last in spans:
            if merged and first <= merged[-1][1] + timedelta(days=1):
                merged[-1] = (merged[-1][0], max(merged[-1][1], last))
            else:
                merged.append((first, last))
        windows = []
        for first, last in merged:
            while first <= last:
                end = min(first + timedelta(days=44), last)
                windows.append((first, end))
                first = end + timedelta(days=1)
        return windows

    def resolve_sha(self, repo, ref_kind, ref):
        """Resolve branch/tag/commit once, only when the user confirms freezing."""
        if (ref_kind not in ("branch","tag","commit") or not isinstance(ref,str)
                or not re.fullmatch(r"[A-Za-z0-9_./-]{1,180}",ref)
                or ".." in ref or ref.startswith(("-", "/"))):
            raise MappingError("Referência Git inválida para congelamento.")
        if ref_kind == "commit" and not re.fullmatch(r"[a-fA-F0-9]{40}",ref):
            raise MappingError("SHA do commit deve ter 40 caracteres.")
        resolved = self._get(repo, "commits?per_page=1&sha=" + parse.quote(ref, safe=""))
        if not isinstance(resolved,list) or not resolved:
            raise MappingError("GitHub não encontrou a referência selecionada.")
        sha = resolved[0].get("sha") if isinstance(resolved[0],dict) else ""
        if not isinstance(sha,str) or not re.fullmatch(r"[a-fA-F0-9]{40}",sha):
            raise MappingError("GitHub não retornou um SHA de commit válido.")
        return sha.lower()

    def catalogue(self, repo, lessons=None, overrides=None, branch=""):
        """Read snapshots with bounded REST calls and date-window pagination.

        Git commit dates are metadata, not proof of lesson dates. Tree inspection
        always uses the branch tip (not a historical window's first commit).
        """
        if not _safe_repo(repo):
            raise MappingError("URL de repositório inválida.")
        if not isinstance(branch, str) or len(branch) > 180 or (branch and
                (not re.fullmatch(r"[A-Za-z0-9_./-]+", branch) or ".." in branch or
                 branch.startswith(("-", "/")) or branch.endswith("/") or "@{" in branch)):
            raise MappingError("Branch inválida. Informe o nome da branch, sem URL ou parâmetros.")
        sha_filter = ("&sha=" + parse.quote(branch, safe="")) if branch else ""
        windows = self._date_windows(lessons, overrides)
        queried_windows = []
        history_partial = False
        commits = []
        seen = set()
        newest_sha = ""

        def add(batch):
            for entry in batch:
                if not isinstance(entry, dict):
                    continue
                sha = entry.get("sha", "")
                if isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha) and sha not in seen:
                    seen.add(sha)
                    commits.append(entry)

        if windows:
            # A separate tip lookup matters: the newest commit inside an old
            # lesson interval is NOT necessarily the branch's current HEAD.
            tip = self._get(repo, "commits?per_page=1" + sha_filter)
            if not isinstance(tip, list) or not tip:
                raise MappingError("Branch sem commits acessíveis. Confirme o nome.")
            newest_sha = tip[0].get("sha", "")
            if not isinstance(newest_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", newest_sha):
                raise MappingError("A referência não retornou um SHA válido.")
            # Keep the tip as a manual option even when outside lesson dates.
            add(tip)
            page_count = 0
            max_pages = 18
            for start, end in windows:
                if page_count >= max_pages:
                    history_partial = True
                    break
                for page in range(1, 4):
                    remaining = self.rate.get("restantes")
                    if isinstance(remaining, int) and remaining <= 5:
                        history_partial = True
                        break
                    start_time = start.isoformat() + "T00:00:00Z"
                    end_time = end.isoformat() + "T23:59:59Z"
                    endpoint = ("commits?per_page=100" + sha_filter +
                                "&since=" + parse.quote(start_time, safe="") +
                                "&until=" + parse.quote(end_time, safe="") +
                                "&page=" + str(page))
                    try:
                        batch = self._get(repo, endpoint)
                    except MappingError:
                        history_partial = True
                        break
                    if not isinstance(batch, list):
                        history_partial = True
                        break
                    page_count += 1
                    if page == 1:
                        queried_windows.append([start.isoformat(), end.isoformat()])
                    add(batch)
                    if len(batch) < 100:
                        break
                    if page == 3 or page_count >= max_pages:
                        history_partial = True
                if history_partial and (page_count >= max_pages or
                         (isinstance(self.rate.get("restantes"), int) and
                          self.rate["restantes"] <= 5)):
                    break
        else:
            # No lesson date: retain a bounded recent-history fallback.
            first = self._get(repo, "commits?per_page=100" + sha_filter)
            if not isinstance(first, list):
                raise MappingError("Formato inesperado da API de commits.")
            add(first)
            if not commits:
                raise MappingError("O repositório não tem commits acessíveis.")
            newest_sha = commits[0]["sha"]
            batch = first
            for page in (2, 3):
                if len(batch) < 100:
                    break
                remaining = self.rate.get("restantes")
                if isinstance(remaining, int) and remaining <= 5:
                    history_partial = True
                    break
                try:
                    batch = self._get(repo, "commits?per_page=100" + sha_filter +
                                            "&page=" + str(page))
                except MappingError:
                    history_partial = True
                    break
                if not isinstance(batch, list):
                    history_partial = True
                    break
                add(batch)
            history_partial = history_partial or len(first) >= 100 and len(batch) >= 100

        if not commits:
            raise MappingError("Nenhum commit acessível no período selecionado.")

        # Preserve calls for the tree when unauthenticated quota is low.
        remaining = self.rate.get("restantes")
        if isinstance(remaining, int) and remaining <= 2:
            tags = []
            history_partial = True
        else:
            tags = self._get(repo, "tags?per_page=100")
            if not isinstance(tags, list):
                raise MappingError("Formato inesperado da API de tags.")

        candidates = []
        dates = {}
        version_dates = {}
        for item in commits:
            sha = item["sha"]
            meta = item.get("commit") or {}
            info = meta.get("committer") or meta.get("author") or {}
            when = _date(info.get("date"))
            subject = str(meta.get("message", "")).splitlines()[0][:130]
            dates[sha] = when
            if when:
                for version in re.findall(r"(?i)(?<![A-Za-z0-9])V[0-9]{1,3}(?![A-Za-z0-9])", subject):
                    version_dates.setdefault(version.casefold(), when)
            candidates.append({"id": _candidate_id("commit", sha), "tipo": "commit",
                               "ref_tipo": "commit", "ref": sha, "pasta": "",
                               "data": when, "rotulo": f"Commit {sha[:9]} — {subject}",
                               "fonte_data": "git_commit", "sugestao_anterior": None})
        for tag in tags[:100]:
            name = tag.get("name") if isinstance(tag, dict) else ""
            sha = (tag.get("commit") or {}).get("sha", "") if isinstance(tag, dict) else ""
            if not isinstance(name, str) or not 1 <= len(name) <= 160:
                continue
            when = dates.get(sha, "")
            candidates.append({"id": _candidate_id("tag", name), "tipo": "tag",
                               "ref_tipo": "tag", "ref": name, "pasta": "",
                               "data": when, "rotulo": f"Tag {name}",
                               "fonte_data": "git_commit" if when else "sem_data_verificada",
                               "sugestao_anterior": None})

        remaining = self.rate.get("restantes")
        if isinstance(remaining, int) and remaining <= 0:
            tree = {"tree": [], "truncated": True}
            history_partial = True
        else:
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
        return {"candidatos": candidates, "truncado": bool(tree.get("truncated")),
                "historico_parcial": history_partial,
                "limite_amostra": {"commits": 1801 if windows else 300, "tags": 100},
                "taxa": self.rate, "autenticado": bool(self.token), "branch": branch,
                "periodos_consultados": queried_windows, "consulta_por_periodo": bool(windows)}

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
                dated.sort(key=lambda item: (item[0], item[1], item[2]))
            covered = any(isinstance(span, (list, tuple)) and len(span) == 2 and
                          span[0] <= day <= span[1]
                          for span in catalogue.get("periodos_consultados", []))
            outside = bool(day and catalogue.get("consulta_por_periodo") and not covered)
            best = (dated[0][3]["id"] if dated and dated[0][0] <= 30 and not outside else "")
            results.append({"aula": name, "data": day,
                            "origem_data": "informada_usuario" if name in overrides else lesson.get("origem_data", ""),
                            "candidato_id": best,
                            "motivo": ("data fora do período consultado; consulte o repositório novamente" if outside else
                                       "Data próxima (não comprova correspondência)" if best else
                                       "Sem sugestão confiável; selecione manualmente")})
        return results


def preview_mapping(vault, repo, overrides=None, branch=""):
    lessons = lesson_dates(vault)
    catalogue = GithubMapping().catalogue(repo, lessons=lessons, overrides=overrides, branch=branch)
    return {**catalogue, "aulas": GithubMapping.suggestions(catalogue, lessons, overrides),
            "repo": repo.rstrip("/").removesuffix(".git")}
