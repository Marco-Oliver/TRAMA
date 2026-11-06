"""Automatic, evidence-first GitHub version association for imported TXT lessons.

The ordinary workflow needs only a repository URL and transcripts. All GitHub
content is read-only at immutable SHAs; imported code is never executed.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .github_cache import GithubCache
from .github_code import GithubCodeReader
from .github_lesson_index import LessonRepositoryIndex
from .github_mapping import GithubMapping, MappingError, GithubRateLimitError
from .lesson_code_config import _safe_repo, read_config
from .code_intel import concept_from_text, is_generic_code_term

PROFESSOR_ORG = "academiadoprogramador-fullstack"
VERSION = re.compile(r"^(?:v|vers[aã]o)[._ -]*(\d+)(?:[._-](\d+))*$", re.I)
# A version mention is only evidence when it refers to a project action.
# Video segment IDs and version numbers of languages/frameworks are not Git refs.
SPEECH = re.compile(r"(?<![a-z0-9_])(?:v|versao)[\s._:#-]*(\d{1,3})\b", re.I)
VIDEO_HEADER = re.compile(r"^\s*(?:a\d{1,4}\s*[-–|]\s*v\d+\b|v0\d+\b)", re.I)
TECH_BEFORE = re.compile(
    r"(?:\.net|angular|node(?:\.js)?|c#|http|java|typescript|react|postgres(?:ql)?|sql)\s*$", re.I)
PROJECT_VERBS = {
    "jogar", "jogando", "joguei", "jogou", "jogamos",
    "subir", "subindo", "subiu", "subimos", "subo",
    "criar", "criando", "criou", "criamos", "crio",
    "mandar", "mandando", "mandou", "mandamos", "mando",
    "branch", "branches", "commit", "commits", "commitar", "commitando",
}
REVIEW = re.compile(r"\b(?:revisao|revisamos|revisar|revisando|revisou|quebra.cuca|sem codigo|teorica|sem programar)\b", re.I)
TIMESTAMP = re.compile(r"^\s*\[?(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]?")
IGNORE = {"class","public","private","const","return","import","export","default",
          "from","using","namespace","string","number","true","false","void",
          "main","src","index","app","component","services","service","interface",
          "this","async","await","constructor","program","teste","test","codigo",
          "arquivo","aula","professor","versao","version","nova","novo","para"}


def normalized(text):
    return unicodedata.normalize("NFKD", str(text)).encode("ascii","ignore").decode().casefold()


def version_number(name):
    m = VERSION.fullmatch(normalized(name))
    if m is None:
        return None
    return int(m.group(1))


def role_for(repo):
    if not _safe_repo(repo):
        raise ValueError("Informe uma URL HTTPS de repositório GitHub válida.")
    owner = repo.rstrip("/").removesuffix(".git").split("/")[-2]
    return "professor" if owner.casefold() == PROFESSOR_ORG else "dupla"


def lesson_order(name):
    match = re.fullmatch(r"Aula-(\d{3,4})", name or "")
    return int(match.group(1)) if match else 999999


def _literal(text, term):
    term = normalized(term).strip()
    if len(term) < 3 or term in IGNORE or is_generic_code_term(term):
        return False
    return bool(re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])",
                          normalized(text)))


def _changed_lines(patch):
    """Read added-side line numbers from a bounded GitHub unified diff."""
    result=set()
    lineno=None
    for raw in str(patch)[:140000].splitlines():
        if raw.startswith("@@"):
            match=re.search(r"\+(\d+)(?:,(\d+))?",raw)
            lineno=int(match.group(1)) if match else None
        elif lineno is not None and raw.startswith("+") and not raw.startswith("+++"):
            result.add(lineno)
            lineno+=1
        elif lineno is not None and raw.startswith(" "):
            lineno+=1
    return sorted(result)


def project_version_mentions(text):
    """Conservative project-version clues from spoken TXT, not video/tech versions.

    Require a project verb or an explicit "para a v" / "na v" construction
    within six surrounding words on the same transcript line.
    """
    found = set()
    for raw in str(text).splitlines():
        line = normalized(raw)
        if VIDEO_HEADER.match(line):
            continue
        for match in SPEECH.finditer(line):
            digits = match.group(1)
            if len(digits) > 1 and digits.startswith("0"):
                continue  # V01, V02 etc. are recording parts, never project refs.
            if TECH_BEFORE.search(line[:match.start()]):
                continue
            before = re.findall(r"[a-z0-9]+", line[:match.start()])
            after = re.findall(r"[a-z0-9]+", line[match.end():])
            surrounding = before[-6:] + after[:6]
            explicit = bool(re.search(r"(?:para\s+(?:a\s+)?|na\s+)\s*(?:v|versao)\s*[._:#-]*\s*\d{1,3}\b",
                                      line[max(0,match.start()-30):match.end()]))
            if explicit or any(word in PROJECT_VERBS for word in surrounding):
                found.add(int(digits))
    return found


def _early_review(transcript, title=""):
    """Review is a lesson type only in its title or at/before minute two."""
    if REVIEW.search(normalized(title)):
        return True
    last_seconds = None
    for raw in str(transcript).splitlines():
        match = TIMESTAMP.match(raw)
        if match:
            hours, minutes, seconds = match.groups()
            last_seconds = int(hours or 0)*3600 + int(minutes)*60 + int(seconds)
        if last_seconds is not None and last_seconds <= 120 and REVIEW.search(normalized(raw)):
            return True
    return False


def _words(value):
    # Split PascalCase to match spoken terms in a natural-language TXT.
    value = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", str(value))
    return {t for t in re.findall(r"[a-z][a-z0-9_]{3,}", normalized(value))
            if t not in IGNORE}


class GithubAutoMapper:
    def __init__(self, store, client=None, reader=None, log=None):
        self.store = store
        self.client = client if client is not None else GithubMapping()
        self.cache = GithubCache(vault=store.vault)
        self.reader = reader if reader is not None else GithubCodeReader(
            client=self.client,cache=self.cache)
        self.index = LessonRepositoryIndex(store,reader=self.reader,cache=self.cache)
        self.log = log if log is not None else (lambda message: None)
        self.pending = []
        self._review_titles = {}

    def _paginate(self, repo, resource):
        entries = []
        # 1000 refs maximum: never report an unexamined tail as complete.
        for page in range(1, 11):
            rows = self.client._get(repo, f"{resource}?per_page=100&page={page}")
            if not isinstance(rows, list):
                raise MappingError("GitHub retornou uma lista de referências inválida.")
            entries.extend(rows)
            if len(rows) < 100:
                return entries
        raise MappingError("Mais de 1000 branches/tags; descubra versões em partes.")

    @staticmethod
    def _first_exclusive(compare):
        commits = compare.get("commits",[]) if isinstance(compare,dict) else []
        times = [str((c.get("commit",{}).get("committer") or
                      c.get("commit",{}).get("author") or {}).get("date",""))
                 for c in commits if isinstance(c,dict)]
        return min((s for s in times if re.match(r"^\d{4}-\d\d-\d\dT",s)),default="")

    def discover(self, repo):
        role = role_for(repo)
        repo = repo.rstrip("/").removesuffix(".git")
        previous = next((r for r in self.store.auto_repositories()
                         if r["repo_url"] == repo), None)
        if previous and previous["status"] in ("ready","no_versions"):
            return json.loads(previous["versions_json"])
        if previous and previous["status"] == "paused":
            try:
                limit = json.loads(previous["message"]).get("retry_at")
            except (ValueError,TypeError):
                limit = None
            if isinstance(limit,(int,float)) and time.time() < limit:
                self.pending.append("GitHub pausado por cota; retomar após "
                                    + datetime.fromtimestamp(limit).isoformat(timespec="minutes"))
                return None
        private = bool(previous["private"]) if previous and previous["private"] is not None else False
        try:
            metadata = self.client._get(repo,"")
            if not isinstance(metadata,dict) or type(metadata.get("private")) is not bool:
                raise MappingError("GitHub não confirmou a privacidade do repositório.")
            private = metadata["private"]
            self.reader._privacy[repo] = private
            default_branch = metadata.get("default_branch")
            candidates = []
            available_branches = set()
            for kind,resource in (("branch","branches"),("tag","tags")):
                for item in self._paginate(repo,resource):
                    name = item.get("name") if isinstance(item,dict) else None
                    if kind == "branch" and isinstance(name,str):
                        available_branches.add(name)
                    number = version_number(name)
                    if number is not None and isinstance(name,str):
                        candidates.append({"name":name,"number":number,"kind":kind})
            # A tag and branch with the same number are alternate names for a
            # single version; prefer tag, then stable lexical order.
            candidates.sort(key=lambda row:(row["number"],row["kind"] != "tag",row["name"].casefold()))
            selected={}
            for item in candidates:
                selected.setdefault(item["number"],item)
            versions = sorted(selected.values(),key=lambda x:x["number"])
            for version in versions:
                # A full commit SHA, resolved once and never reinterpreted.
                version["sha"] = self.client.resolve_sha(repo,version["kind"],version["name"])
                version["folder"] = ""
                version["first_exclusive_at"] = ""
                version["changed_paths"] = None
                version["changed_lines"] = {}
            # The default branch can contain progress beyond the last vN.
            # Do not invent a version for repositories with no vN candidates.
            main_name = default_branch if isinstance(default_branch,str) else (
                "main" if "main" in available_branches else "")
            if (versions and isinstance(main_name,str) and main_name in available_branches
                    and not any(v["name"] == main_name for v in versions)):
                main_sha = self.client.resolve_sha(repo,"branch",main_name)
                if main_sha not in {v["sha"] for v in versions}:
                    versions.append({
                        "name": main_name, "kind": "branch", "is_default": True,
                        "number": versions[-1]["number"]+1, "sha": main_sha,
                        "folder": "", "first_exclusive_at": "",
                        "changed_paths": None, "changed_lines": {},
                    })
            for i,version in enumerate(versions):
                if i == 0:
                    continue
                old = versions[i-1]["sha"]
                new = version["sha"]
                if old == new:
                    version["changed_paths"] = []
                    continue
                compared = self.client._get(repo,f"compare/{old}...{new}")
                if not isinstance(compared,dict):
                    raise MappingError("GitHub não retornou comparação verificável das versões.")
                files = compared.get("files")
                large = (compared.get("too_large") is True or
                         isinstance(files,list) and len(files) >= 300 or
                         isinstance(compared.get("total_files"),int) and
                         compared["total_files"] >= 300)
                if not isinstance(files,list) and not large:
                    raise MappingError("GitHub não retornou a lista de arquivos da comparação.")
                version["first_exclusive_at"] = self._first_exclusive(compared)
                if large:
                    # REST compare may cap its files to 300. Full verified Git
                    # trees have blob identities, so detect added/modified
                    # content without trusting an incomplete files list.
                    before = self.reader.tree(repo,old)
                    after = self.reader.tree(repo,new)
                    version["changed_paths"] = sorted(
                        path for path, info in after.items()
                        if path not in before or
                        info["blob_sha"] != before[path]["blob_sha"])
                    version["changed_lines"] = {}
                    version["diff_source"] = "git_trees"
                else:
                    version["changed_paths"] = [f["filename"] for f in files
                        if isinstance(f,dict) and f.get("status") in
                        ("added","modified","renamed","copied") and
                        isinstance(f.get("filename"),str)]
                    version["changed_lines"] = {
                        f["filename"]:_changed_lines(f.get("patch",""))
                        for f in files
                        if isinstance(f,dict) and f.get("status") == "modified"
                        and isinstance(f.get("filename"),str)}
            versions.sort(key=lambda x:(x["number"],x["first_exclusive_at"],x["name"].casefold()))
            self.store.save_auto_repository(
                repo,role,private,"ready" if versions else "no_versions",versions)
            self.log(f"GitHub automático: {len(versions)} versão(ões) congelada(s) em {repo}.")
            return versions
        except GithubRateLimitError as exc:
            self.store.save_auto_repository(repo,role,private,"paused",message=json.dumps(
                {"retry_at":exc.retry_at, "error":str(exc)},ensure_ascii=False))
            self.pending.append(str(exc))
            self.log("Descoberta GitHub pausada por cota; TXT preservados.")
            return None
        except (MappingError,RuntimeError,OSError,ValueError) as exc:
            self.store.save_auto_repository(repo,role,private,"pending",message=str(exc)[:300])
            self.pending.append(f"GitHub {repo}: {str(exc)[:160]}")
            self.log("Descoberta GitHub pendente; importação de TXT continua.")
            return None

    def _delta(self, repo, version, previous):
        payload = self.index._snapshot(repo,version["sha"],version.get("folder",""),
                                        self.reader._privacy[repo])
        changed = version.get("changed_paths")
        # No diff for the initial version: everything is a candidate addition.
        if changed is None:
            changed = [f["path"] for f in payload.get("files",[])]
        permitted = set(changed)
        modified = version.get("changed_lines",{})
        def altered(item):
            path = item.get("path")
            return (path in permitted and
                    (path not in modified or item.get("line") in modified[path]))
        symbols = [item for item in payload.get("symbols",[]) if altered(item)]
        evidence = [item for item in payload.get("evidence",[]) if altered(item)]
        return {"symbols":symbols,"evidence":evidence,
                "files":[p for p in permitted if isinstance(p,str)]}

    @staticmethod
    def _score(text, diff, number):
        # Only evidence from *added/modified* code counts; identical files in
        # successive versions cannot spuriously make later versions win.
        code = 0.0
        symbols = {str(item.get("name","")) for item in diff["symbols"]}
        concepts = {str(item.get("concept","")) for item in diff["evidence"]}
        for term in symbols:
            if _literal(text,term):
                code += 4
            else:
                components = _words(term)
                if len(components) > 1 and all(_literal(text,c) for c in components):
                    code += 2
        for term in concepts:
            if _literal(text,term):
                code += 3
        for path in diff["files"]:
            name = Path(path).stem
            if _literal(text,name):
                code += 2.5
        code = min(code,18)
        spoken = project_version_mentions(text)
        speech = 6 if number is not None and number in spoken else 0
        # Do not penalize a conflicting version that has positive code
        # evidence; otherwise 2.5*3 - 2 would fall below speech alone (6).
        # Even the weakest code evidence (one changed filename: 2.5) outweighs
        # speech alone (6); speech remains a useful tie-breaker when code agrees.
        return code * 3 + speech, code, speech

    def _texts(self):
        grouped = defaultdict(list)
        self._review_titles = {}
        for src in self.store.sources("transcript"):
            lesson = src["lesson"]
            if lesson_order(lesson) == 999999:
                continue
            raw = self.store.vault / (src["stored_path"] or "")
            try:
                target = raw.resolve()
                if (raw.is_symlink() or not target.is_relative_to(self.store.vault)
                        or not target.is_file() or target.stat().st_size > 20_000_000):
                    continue
                from .content import file_hash
                if file_hash(target) != src["digest"]:
                    continue
                text = target.read_text(encoding="utf-8-sig",errors="replace")[:60000]
                grouped[lesson].append(text)
                self._review_titles[lesson] = (
                    self._review_titles.get(lesson,False) or
                    _early_review(text,src["label"] or ""))
            except (OSError,ValueError,UnicodeError):
                continue
        return {key:"\n".join(value)[:120000] for key,value in grouped.items()}

    @staticmethod
    def _optimize(lessons, versions, scores, anchored, decisions):
        # Viterbi DP. State = last version number, including -1 for no code yet.
        # A no-code lesson leaves the state unchanged and never forces a version.
        states = {-1:(0.0,[])}
        for lesson in lessons:
            known = anchored.get(lesson)
            previous_decision = decisions.get(lesson)
            options = []
            if known is not None:
                options = [known]
            elif previous_decision is not None:
                options = [None] if previous_decision["decision"] == "none" else [
                    next((i for i,v in enumerate(versions)
                          if v["sha"] == previous_decision["version_sha"]),None)]
            else:
                text_scores = scores[lesson]
                if not text_scores or max(text_scores) < 2.5:
                    options = [None]
                else:
                    options = [None] + [i for i,score in enumerate(text_scores)
                                        if score >= 2.5]
            next_states = {}
            for last,(total,route) in states.items():
                for choice in options:
                    if choice is not None and choice < last:
                        continue
                    # Prefer a strongly evidenced assignment over no-code,
                    # with a tiny tie preference for earlier versions.
                    reward = (scores[lesson][choice] if choice is not None else 0.0)
                    now = choice if choice is not None else last
                    candidate = (total + reward - (0.001 * max(now,0)),route+[choice])
                    if now not in next_states or candidate[0] > next_states[now][0]:
                        next_states[now] = candidate
            if not next_states:
                # Conflicting manual anchors should never be overwritten.
                return None
            states = next_states
        return max(states.values(),key=lambda item:item[0])[1]

    def assign(self, recalculate=False):
        texts = self._texts()
        if not texts:
            return {"mapped":0,"pending":self.pending}
        manual = read_config(self.store.vault)
        changed = 0
        for record in self.store.auto_repositories():
            repo = record["repo_url"]
            if record["status"] == "index_paused":
                try:
                    retry_at = json.loads(record["message"]).get("retry_at")
                except (ValueError,TypeError):
                    retry_at = None
                if isinstance(retry_at,(int,float)) and time.time() < retry_at:
                    self.pending.append("Indexação GitHub pausada; aguarde a cota REST.")
                    continue
                self.store.save_auto_repository(
                    repo,record["role"],bool(record["private"]),"ready")
                record=next(r for r in self.store.auto_repositories() if r["repo_url"] == repo)
            if record["status"] in ("pending","paused"):
                self.discover(repo)
                record = next(r for r in self.store.auto_repositories() if r["repo_url"] == repo)
            if record["status"] != "ready":
                continue
            versions = json.loads(record["versions_json"])
            if not versions:
                continue
            self.reader._privacy[repo] = bool(record["private"])
            prior_decisions = {} if recalculate else self.store.automatic_decisions(repo)
            anchored = {}
            # Manual registrations always win. Existing auto versions are locked
            # by decisions unless the user explicitly requests recalculation.
            for lesson in texts:
                if manual["fatal"] or lesson in manual.get("invalid",{}) or lesson in manual["aulas"]:
                    locked = [r for r in self.store.conn.execute(
                        "SELECT commit_sha FROM github_lesson_refs WHERE lesson=? AND repo_url=? AND origem!='automatica'",
                        (lesson,repo))]
                    if locked:
                        anchored[lesson] = next((i for i,v in enumerate(versions)
                            if v["sha"] == locked[0]["commit_sha"]),None)
                    else:
                        prior_decisions[lesson] = {"decision":"none","version_sha":""}
            lessons = sorted(texts,key=lesson_order)
            # Avoid refetching all 9 snapshots on repeat processing when every
            # lesson already has a stable auto/manual decision.
            undecided = [lesson for lesson in lessons
                         if lesson not in prior_decisions and lesson not in anchored]
            if not undecided:
                continue
            try:
                diffs = [self._delta(repo,v,versions[i-1] if i else None)
                         for i,v in enumerate(versions)]
            except GithubRateLimitError as exc:
                self.store.save_auto_repository(
                    repo,record["role"],bool(record["private"]),"index_paused",
                    message=json.dumps({"retry_at":exc.retry_at,"error":str(exc)},
                                       ensure_ascii=False))
                self.pending.append(str(exc))
                self.log("Associação pausada por cota; decisões anteriores mantidas.")
                break
            except (MappingError,ValueError,OSError,RuntimeError) as exc:
                self.pending.append(f"GitHub {repo}: {str(exc)[:180]}")
                continue
            scores = {}
            for lesson in lessons:
                text = texts[lesson]
                options = [self._score(
                    text,diff,None if v.get("is_default") else v["number"])
                    for diff,v in zip(diffs,versions)]
                score_list = [result[0] for result in options]
                # Pure revision/quebra-cuca should not acquire code by proximity.
                if self._review_titles.get(lesson,False) and not any(
                        x[1] >= 3 for x in options):
                    score_list = [0.0]*len(versions)
                scores[lesson] = score_list
            plan = self._optimize(lessons, versions, scores, anchored, prior_decisions)
            if plan is None:
                self.pending.append(f"GitHub {repo}: âncoras manuais inconsistentes; nada sobrescrito.")
                continue
            for lesson,choice in zip(lessons,plan):
                if lesson in prior_decisions or lesson in anchored:
                    continue
                ranked = sorted(scores[lesson],reverse=True)
                strength = scores[lesson][choice] if choice is not None else 0
                margin = strength - (ranked[1] if len(ranked)>1 else 0)
                confidence = ("alta" if strength >= 9 and margin >= 3 else
                              "media" if strength >= 4 else "baixa") if choice is not None else ""
                selected = versions[choice] if choice is not None else None
                if self.store.set_auto_decision(repo,lesson,record["role"],
                                                bool(record["private"]),selected,confidence,
                                                recalculate=recalculate):
                    changed += 1
        return {"mapped":changed,"pending":list(dict.fromkeys(self.pending))}
