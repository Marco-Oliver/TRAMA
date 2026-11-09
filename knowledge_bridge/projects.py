"""Aba Projetos: repositórios por dono, pares, versões e navegação de arquivos.

Somente leitura via REST do GitHub (sem clone, sem embutir github.com):
* versões = branches + tags + versão entregue de cada atividade (1 chamada cada,
  guardadas em ``project_repo_meta`` por 30 min);
* árvore = 1 chamada por SHA (guardada no GithubCache quando o repo é público);
* arquivo = raw.githubusercontent.com no SHA exato (não consome a cota da API).
Pastas V0/V1/V2 dentro do repositório também viram opções de versão.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import PurePosixPath

from .activities import (Activities, OWNER_LABELS, OWNER_CLASSES, repo_key, repo_parts,
                         github_tree_url, _norm, _text)

META_TTL = 30 * 60
VERSION_DIR = re.compile(r"^(?:v|vers[aã]o)[ ._-]*(\d{1,3})(?:[ ._-].*)?$", re.I)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def repo_note_path(repo_url: str) -> str:
    owner, name = repo_parts(repo_url)
    clean = lambda v: re.sub(r"[^A-Za-z0-9_.-]+", "-", v).strip("-") or "repo"  # noqa: E731
    return f"03-Meus-Projetos/Repositorios/{clean(owner)}--{clean(name)}.md"


def _pair_key(name: str) -> str:
    text = _norm(name)
    text = re.sub(r"\b(academia|professor|nosso|nossa|dupla|final|projeto|trabalho)\b", " ", text)
    return re.sub(r"[^a-z0-9]", "", text)


def detect_stack(paths: list[str]) -> dict:
    """Stack, entry files and run command from file names only."""
    names = {PurePosixPath(p).name.casefold(): p for p in paths}
    suffixes = {PurePosixPath(p).suffix.casefold() for p in paths}
    stack, entries, run = [], [], []
    csproj = [p for p in paths if p.casefold().endswith(".csproj")]
    if csproj or ".cs" in suffixes:
        stack.append("C# / .NET")
        if any(p.endswith((".cshtml", ".razor")) for p in paths):
            stack.append("ASP.NET MVC / Razor")
        if any("/migrations/" in "/" + p.casefold() for p in paths):
            stack.append("Entity Framework Core")
        if any(re.search(r"(^|/)[^/]*tests?[^/]*\.csproj$", p, re.I) for p in csproj):
            stack.append("Testes (.NET)")
        for key in ("program.cs", "startup.cs"):
            if key in names:
                entries.append(names[key])
        entries += [p for p in paths if p.casefold().endswith(".sln")][:1]
        if csproj:
            main = sorted(csproj, key=lambda p: ("test" in p.casefold(), p.count("/"), p))[0]
            folder = str(PurePosixPath(main).parent)
            run.append("dotnet run" + ("" if folder == "." else f" --project {folder}"))
    if "angular.json" in names:
        stack.append("Angular / TypeScript")
        run.append("npm install && npx ng serve")
    elif "package.json" in names:
        stack.append("Node.js" + (" / TypeScript" if ".ts" in suffixes else ""))
        run.append("npm install && npm start")
    if "main.ts" in names:
        entries.append(names["main.ts"])
    if not stack and (".html" in suffixes):
        stack.append("HTML / CSS / JavaScript")
        if "index.html" in names:
            entries.append(names["index.html"])
            run.append("abrir index.html no navegador")
    if ".py" in suffixes:
        stack.append("Python")
    for key in ("readme.md",):
        if key in names:
            entries.insert(0, names[key])
    return {"stack": stack, "entries": list(dict.fromkeys(entries))[:6], "run": run[:2]}


def outline(paths: list[str], depth: int = 2, limit: int = 60) -> list[str]:
    """Folder structure as indented text lines (folders first, then files)."""
    tree: dict = {}
    for path in paths:
        parts = path.split("/")
        if any(p in ("bin", "obj", "node_modules", ".vs", ".git", "dist") for p in parts[:-1]):
            continue
        node = tree
        for part in parts[:depth]:
            node = node.setdefault(part, {})
    lines: list[str] = []

    def walk(node, level):
        for name in sorted(node, key=lambda n: (not node[n], n.casefold())):
            if len(lines) >= limit:
                return
            lines.append("  " * level + (name + "/" if node[name] else name))
            walk(node[name], level + 1)
    walk(tree, 0)
    return lines


class Projects:
    def __init__(self, study, acts: Activities | None = None):
        self.study = study
        self.store = study.store
        self.conn = study.conn
        self.acts = acts or study.activities

    # ------------------------------------------------------------ registry
    def register(self, url: str) -> str:
        key = repo_key(url)
        if not key:
            raise ValueError("Use um link https://github.com/dono/repositorio.")
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO project_repos(repo_url) VALUES(?)", (key,))
        self._set_hidden(self.hidden() - {key})
        return key

    def hidden(self) -> set[str]:
        row = self.conn.execute("SELECT value FROM study_meta WHERE key='hidden_repos'").fetchone()
        try:
            return {x for x in json.loads(row["value"]) if isinstance(x, str)} if row else set()
        except ValueError:
            return set()

    def _set_hidden(self, values: set[str]) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO study_meta(key,value) VALUES('hidden_repos',?)",
                              (json.dumps(sorted(values)[:500]),))

    def remove(self, url: str) -> None:
        """Hide from Projetos (lesson/activity data stays untouched)."""
        key = repo_key(url)
        if not key:
            raise ValueError("Repositório inválido.")
        with self.conn:
            self.conn.execute("DELETE FROM project_repos WHERE repo_url=?", (key,))
        self._set_hidden(self.hidden() | {key})

    def repo_urls(self) -> list[str]:
        urls = set()
        queries = ("SELECT repo_url AS u FROM project_repos",
                   "SELECT repo_url AS u FROM study_activity_repos",
                   "SELECT url AS u FROM repositories",
                   "SELECT repo_url AS u FROM github_auto_repositories",
                   "SELECT DISTINCT repo_url AS u FROM github_lesson_refs")
        for query in queries:
            try:
                for row in self.conn.execute(query):
                    key = repo_key(row["u"])
                    if key:
                        urls.add(key)
            except Exception:  # noqa: BLE001 - optional legacy tables
                continue
        return sorted(urls - self.hidden(), key=str.casefold)

    def lesson_refs(self, url: str) -> list[str]:
        lessons = set()
        try:
            for row in self.conn.execute("SELECT lesson, repo_url FROM github_lesson_refs"):
                if repo_key(row["repo_url"]) == url:
                    lessons.add(row["lesson"])
        except Exception:  # noqa: BLE001
            pass
        for activity in self.repo_activities(url):
            linked = self.acts.activity_lessons(activity["id"])
            lessons.update(linked["desenvolvimento"] + linked["relacionadas"])
        return sorted(lessons, key=lambda x: int(x.split("-")[1]) if "-" in x else 0)

    def repo_activities(self, url: str) -> list[dict]:
        return [a for a in self.acts.activities() if any(r["repo_url"] == url for r in a["repos"])]

    def pairs(self, urls: list[str]) -> dict:
        """url -> list of partner urls (same activity first, then same name)."""
        out = {u: [] for u in urls}
        for activity in self.acts.activities():
            members = [r["repo_url"] for r in activity["repos"] if r["repo_url"] in out]
            for a in members:
                for b in members:
                    if a != b and b not in out[a]:
                        out[a].append(b)
        keys = {u: _pair_key(repo_parts(u)[1]) for u in urls}
        for a in urls:
            for b in urls:
                if a == b or b in out[a] or self.acts.owner_class(a) == self.acts.owner_class(b):
                    continue
                ka, kb = keys[a], keys[b]
                if ka and kb and (ka == kb or (min(len(ka), len(kb)) >= 6 and (ka in kb or kb in ka))):
                    out[a].append(b)
        return out

    def overview(self) -> dict:
        urls = self.repo_urls()
        pairs = self.pairs(urls)
        groups = {k: [] for k in OWNER_CLASSES}
        for url in urls:
            owner, name = repo_parts(url)
            meta = self.meta(url)
            klass = self.acts.owner_class(url)
            groups[klass].append({
                "url": url, "owner": owner, "name": name, "owner_class": klass,
                "owner_label": self.acts.owner_label(url),
                "pairs": [{"url": p, "owner": repo_parts(p)[0], "name": repo_parts(p)[1],
                           "owner_class": self.acts.owner_class(p)} for p in pairs[url]],
                "activities": len(self.repo_activities(url)),
                "description": (meta or {}).get("description", "")})
        return {"groups": [{"klass": k, "label": OWNER_LABELS[k], "repos": groups[k]}
                           for k in OWNER_CLASSES if groups[k]],
                "owners": self.acts.owners(), "total": len(urls)}

    # ------------------------------------------------------------ versions
    def meta(self, url: str) -> dict | None:
        row = self.conn.execute("SELECT payload, fetched_at FROM project_repo_meta WHERE repo_url=?",
                                (url,)).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["payload"])
        except ValueError:
            return None
        data["_fetched_at"] = row["fetched_at"]
        return data

    def _save_meta(self, url: str, data: dict) -> None:
        clean = {k: v for k, v in data.items() if not k.startswith("_")}
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO project_repo_meta(repo_url,payload,fetched_at) "
                              "VALUES(?,?,?)", (url, json.dumps(clean, ensure_ascii=False), time.time()))

    def refresh_meta(self, url: str, client, force: bool = False) -> dict:
        current = self.meta(url)
        if current and not force and time.time() - current["_fetched_at"] < META_TTL:
            return current
        info = client._get(url, "")
        if not isinstance(info, dict):
            raise ValueError("GitHub não respondeu com os dados do repositório.")
        refs = {}
        for kind, resource in (("branch", "branches"), ("tag", "tags")):
            rows = client._get(url, f"{resource}?per_page=100")
            items = []
            for row in rows if isinstance(rows, list) else []:
                name = row.get("name") if isinstance(row, dict) else None
                sha = ((row.get("commit") or {}).get("sha") or "").lower() if isinstance(row, dict) else ""
                if isinstance(name, str) and len(name) <= 180 and SHA_RE.fullmatch(sha):
                    items.append({"name": name, "sha": sha})
            refs[kind] = items
        data = {**(current or {}), "default_branch": info.get("default_branch") or "main",
                "private": bool(info.get("private")),
                "description": _text(info.get("description") or "", 300),
                "branches": refs["branch"], "tags": refs["tag"]}
        self._save_meta(url, data)
        return self.meta(url)

    def versions(self, url: str, meta: dict | None) -> list[dict]:
        out = []
        for activity in self.repo_activities(url):
            for repo in activity["repos"]:
                if repo["repo_url"] == url and repo["sha"]:
                    out.append({"id": "sha:" + repo["sha"], "label": f"Versão entregue — {activity['title']}",
                                "kind": "entregue", "sha": repo["sha"], "activity": activity["id"]})
        if meta:
            default = meta.get("default_branch") or "main"
            branches = meta.get("branches", [])
            head = next((b for b in branches if b["name"] == default), None)
            if head:
                out.append({"id": "sha:" + head["sha"], "label": f"{default} (atual)", "kind": "main",
                            "sha": head["sha"]})
            for b in sorted(branches, key=lambda x: x["name"].casefold()):
                if b["name"] != default:
                    out.append({"id": "sha:" + b["sha"], "label": f"branch {b['name']}", "kind": "branch",
                                "sha": b["sha"]})
            for t in sorted(meta.get("tags", []), key=lambda x: x["name"].casefold()):
                out.append({"id": "sha:" + t["sha"], "label": f"tag {t['name']}", "kind": "tag",
                            "sha": t["sha"]})
        return out

    # ------------------------------------------------------------ tree
    @staticmethod
    def version_folders(paths: list[str]) -> list[str]:
        """Folders like V0/, V1/, versao-2/ (root or one level down)."""
        found = set()
        for path in paths:
            parts = path.split("/")
            for i, part in enumerate(parts[:2]):
                if i < len(parts) - 1 and VERSION_DIR.fullmatch(part):
                    found.add("/".join(parts[:i + 1]))
        def key(folder):
            match = VERSION_DIR.fullmatch(folder.split("/")[-1])
            return (folder.count("/"), int(match.group(1)) if match else 0, folder)
        return sorted(found, key=key)[:30]

    def tree(self, url: str, sha: str, reader, cache=None) -> dict:
        if not SHA_RE.fullmatch(sha or ""):
            raise ValueError("Versão inválida.")
        meta = self.meta(url) or {}
        private = bool(meta.get("private"))
        key = ("project-tree-v1", url, sha)
        files = None
        if cache is not None and not private:
            raw = cache.get(key, private=False)
            if raw:
                try:
                    files = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeError):
                    files = None
        if isinstance(files, dict):
            reader._trees[(url, sha)] = files
        else:
            files = reader.tree(url, sha)
            if cache is not None and not private:
                cache.put(key, json.dumps(files).encode("utf-8"), private=False)
        paths = sorted(files)
        # The Obsidian note keeps one text outline: the main branch wins,
        # otherwise the first version opened.
        if not meta.get("outline") or (meta.get("outline_sha") != sha and self._is_main(meta, sha)):
            meta.update({"outline": outline(paths), "outline_sha": sha, "stack_info": detect_stack(paths)})
            if "_fetched_at" not in meta:
                meta["_fetched_at"] = 0
            fetched = meta["_fetched_at"]
            self._save_meta(url, meta)
            with self.conn:  # keep the original fetch time for the TTL
                self.conn.execute("UPDATE project_repo_meta SET fetched_at=? WHERE repo_url=?", (fetched, url))
        return {"sha": sha, "files": [{"path": p, "size": files[p]["size"]} for p in paths[:5000]],
                "truncated": len(paths) > 5000, "version_folders": self.version_folders(paths),
                "stack": detect_stack(paths)}

    @staticmethod
    def _is_main(meta: dict, sha: str) -> bool:
        default = meta.get("default_branch")
        return any(b["sha"] == sha and b["name"] == default for b in meta.get("branches", []))

    def repo_view(self, url: str) -> dict:
        from .study_notes import local_time  # noqa: F401
        meta = self.meta(url)
        owner, name = repo_parts(url)
        activities = [{"id": a["id"], "title": a["title"], "kind": a["kind"],
                       "sha": next((r["sha"] for r in a["repos"] if r["repo_url"] == url), "")}
                      for a in self.repo_activities(url)]
        lessons = [{"lesson": l, "title": self.study.lesson_title(l)} for l in self.lesson_refs(url)]
        pairs = self.pairs(self.repo_urls()).get(url, [])
        return {"url": url, "owner": owner, "name": name, "owner_class": self.acts.owner_class(url),
                "owner_label": self.acts.owner_label(url), "meta_loaded": bool(meta),
                "description": (meta or {}).get("description", ""),
                "default_branch": (meta or {}).get("default_branch", ""),
                "versions": self.versions(url, meta), "activities": activities, "lessons": lessons,
                "pairs": [{"url": p, "owner": repo_parts(p)[0], "name": repo_parts(p)[1],
                           "owner_class": self.acts.owner_class(p)} for p in pairs],
                "note": repo_note_path(url)}


# ---------------------------------------------------------------- markdown

def _md(value) -> str:
    return (str(value).replace("\r", " ").replace("\n", " ").replace("[[", "[ [")
            .replace("]]", "] ]").replace("|", "\\|").replace("<", "‹").replace(">", "›"))


def render_repo(projects: Projects, url: str) -> str:
    from .activities import activity_note_path, lesson_link, KIND_LABELS
    view = projects.repo_view(url)
    meta = projects.meta(url) or {}
    label = OWNER_LABELS.get(view["owner_class"], "Outros")
    lines = ["---", "tipo: 'repositorio'", f"dono: '{view['owner_class']}'",
             f"repositorio: '{url}'", "---", "",
             f"# {view['owner']}/{view['name']}", "",
             f"**Dono:** {label} ({_md(view['owner_label'])}) · [repositório atual]({url})"]
    if view["description"]:
        lines += ["", f"> {_md(view['description'])}"]
    lines.append("")
    if view["pairs"]:
        lines += ["## Par", ""]
        for p in view["pairs"]:
            lines.append(f"- {OWNER_LABELS.get(p['owner_class'], 'Outros')}: "
                         f"[[{repo_note_path(p['url'])[:-3]}|{_md(p['owner'])}/{_md(p['name'])}]]")
        lines.append("")
    lines += ["## Versões", ""]
    delivered = [v for v in view["versions"] if v["kind"] == "entregue"]
    for v in delivered:
        lines.append(f"- **{_md(v['label'])}** — [`{v['sha'][:7]}`]({github_tree_url(url, v['sha'])})")
    lines.append(f"- **Repositório atual** — [{_md(view['default_branch'] or 'main')}]({url})")
    for v in view["versions"]:
        if v["kind"] in ("branch", "tag"):
            lines.append(f"- {_md(v['label'])} — [`{v['sha'][:7]}`]({github_tree_url(url, v['sha'])})")
    if not meta:
        lines.append("- *Branches e tags aparecem depois de abrir o repositório em TRAMA → Projetos.*")
    lines.append("")
    if view["activities"]:
        lines += ["## Atividades", ""]
        for a in view["activities"]:
            lines.append(f"- {KIND_LABELS.get(a['kind'], 'Atividade')}: "
                         f"[[{activity_note_path(a['id'])[:-3]}|{_md(a['title'])}]]")
        lines.append("")
    if view["lessons"]:
        lines += ["## Aulas ligadas", ""]
        lines += [f"- {lesson_link(projects.study, l['lesson'])}" + (f" — {_md(l['title'])}" if l["title"] else "")
                  for l in view["lessons"]]
        lines.append("")
    structure = meta.get("outline") or []
    lines += ["## Estrutura de pastas", ""]
    if structure:
        lines += ["```text"] + [s.replace("`", "´") for s in structure] + ["```"]
        if meta.get("outline_sha"):
            lines.append(f"*Estrutura do commit `{meta['outline_sha'][:7]}`.*")
    else:
        lines.append("*Abra o repositório em TRAMA → Projetos para registrar a estrutura.*")
    lines.append("")
    stack = meta.get("stack_info") or {}
    falta = []
    for a in view["activities"]:
        summary = projects.acts.summary(a["id"])
        if summary:
            falta += summary["payload"].get("falta", [])[:4]
    lines += ["## Contexto para IA", "",
              f"- Repositório: {url} (dono: {label}).",
              f"- Stack: {', '.join(stack.get('stack', [])) or 'ver arquivos do repositório'}.",
              f"- Arquivos de entrada: {', '.join('`' + e + '`' for e in stack.get('entries', [])) or 'não identificados'}.",
              f"- Como rodar: {', '.join('`' + r + '`' for r in stack.get('run', [])) or 'ver README'}."]
    for v in delivered:
        lines.append(f"- {_md(v['label'])}: commit `{v['sha']}` — {github_tree_url(url, v['sha'])}")
    if falta:
        lines.append("- O que falta (resumo da entrega): " + "; ".join(_md(f) for f in falta[:6]) + ".")
    lines += ["- O código não é copiado para o cofre: leia pelo link do GitHub (versão entregue ou atual).", ""]
    return "\n".join(lines)
