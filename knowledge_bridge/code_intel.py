"""Evidence-first, read-only indexing and cross-linking of programming repositories.

No builds, package installation, test execution, scripts, or imports from a repository.
A source match is evidence of code *presence*, not of authorship or learning.
"""
from __future__ import annotations

import re
from pathlib import Path

# Canonical technical concepts include common transcription mistakes and aliases.
# The aliases are *search hints*, not authoritative corrections of the recording.
CONCEPTS = {
    "rxjs": (r"\bRxJS\b", ["RxJS"]),
    "interval": (r"\binterval\s*\(", ["interval", "intervalo"]),
    "subscribe": (r"\bsubscribe\s*\(", ["subscribe", "inscrição"]),
    "unsubscribe": (r"\bunsubscribe\s*\(", ["unsubscribe", "desinscrever"]),
    "exhaustMap": (r"\bexhaustMap\b", ["exhaustMap", "exaust map", "exustrix", "exalt map"]),
    "switchMap": (r"\bswitchMap\b", ["switchMap"]),
    "DestroyRef": (r"\bDestroyRef\b", ["DestroyRef", "destroy F", "destroy ref"]),
    "takeUntilDestroyed": (r"\btakeUntilDestroyed\b", ["takeUntilDestroyed", "take anti destroyed", "take until destroyed"]),
    "HttpClient": (r"\bHttpClient\b", ["HttpClient", "HTTP client"]),
    "DbContext": (r"\bDbContext\b", ["DbContext", "Entity Framework"]),
    "Controller": (r"\b(?:Controller|\[ApiController\])\b", ["Controller", "controllers"]),
    "Migration": (r"\b(?:Migration|CreateTable|migrationBuilder)\b", ["Migration", "migrações"]),
    "Test": (r"\b(?:\[Fact\]|\[Test\]|describe\s*\(|it\s*\()", ["Test", "testes unitários"]),
    "interface": (r"\binterface\s+\w+", ["interface"]),
    "class": (r"\bclass\s+\w+", ["class", "classe"]),
    "constructor": (r"\bconstructor\s*\(|\bpublic\s+\w+\s*\(", ["constructor", "construtor"]),
    "signal": (r"\b(?:signal|computed|effect)\s*\(", ["signal", "signals"]),
}

SENSITIVE_NAMES = (
    ".env", "secret", "credential", "private", "password", "token", "appsettings",
    "key.json", "key.pem", "id_rsa", "package-lock", "yarn.lock", "pnpm-lock"
)
SOURCE_EXTS = {".cs", ".ts", ".tsx", ".js", ".jsx", ".py", ".sql", ".html", ".css"}
DOC_EXTS = {".md", ".txt"}
MAX_FILE_BYTES = 100_000
MAX_EVIDENCE = 160
MAX_DOCS = 12


def safe_repo_file(root: Path, rel: str) -> Path | None:
    """Deny secrets, symbolic links, escaped paths and arbitrarily large files."""
    if not rel or "\\" in rel or rel.startswith("-") or any(x in {".", ".."} for x in rel.split("/")):
        return None
    if any(x in rel.casefold() for x in SENSITIVE_NAMES):
        return None
    candidate = root / rel
    if candidate.is_symlink() or not candidate.is_file():
        return None
    real = candidate.resolve()
    if not real.is_relative_to(root.resolve()):
        return None
    if real.stat().st_size > MAX_FILE_BYTES:
        return None
    if real.suffix.lower() not in SOURCE_EXTS | DOC_EXTS | {".json"}:
        return None
    return real


def redact_sensitive(text: str) -> str:
    """Best-effort masking of common credentials in snippets and documentation.

    Applied before storing excerpts or sending them to AI. No pattern-based
    scanner can promise to catch every possible private credential.
    """
    marker = "[SEGREDO-OCULTO]"
    # Suppress credentials and personal identifiers before sending excerpts to
    # an external model. This is best-effort redaction, not a DLP guarantee.
    text = re.sub(
        r"(?is)-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?"
        r"-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", marker, text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b",
                  marker, text)
    text = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
                  "[EMAIL-OCULTO]", text)
    text = re.sub(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)",
                  "[DOCUMENTO-OCULTO]", text)
    text = re.sub(r"""(?i)https?://[^\s<>()"'?]+\?[^\s<>()"']+""",
                  lambda match: match.group(0).split("?", 1)[0] + "?[PARAMETROS-OCULTOS]",
                  text)
    # Recognizable token formats, including credentials embedded inside text.
    # Match long enough tokens to minimize redaction of ordinary code examples.
    for pattern in (
        r"(?i)\b(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-|sk-|AIza)[A-Za-z0-9_\-]{12,}",
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{12,}\b",  # Stripe
        r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b",  # Slack
    ):
        text = re.sub(pattern, marker, text)

    # Bearer headers are secrets regardless of quoted/unquoted syntax.
    text = re.sub(r"(?i)(\bauthorization\s*[:=]\s*['\"]?bearer\s+)[^\s'\"]+",
                  r"\1" + marker, text)

    # Key/value declarations in Python, JavaScript, JSON, YAML, .NET config,
    # and environment-like snippets. Keep variable name and original quotes.
    key_name = (r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
                r"(?:aws[_-]?)?(?:secret[_-]?access[_-]?key|access[_-]?key[_-]?id)|"
                r"client[_-]?secret|password|passwd|secret|private[_-]?key|token)")
    # Handle unquoted and quoted fields separately to avoid newline swallowing.
    quoted = re.compile(rf"(?i)(['\"]?\b{key_name}\b['\"]?\s*[:=]\s*)(['\"])([^'\"\r\n]+)(\2)")
    text = quoted.sub(lambda m: m.group(1) + m.group(2) + marker + m.group(4)
                      if len(m.group(3)) >= 5 else m.group(0), text)
    unquoted = re.compile(rf"(?i)(['\"]?\b{key_name}\b['\"]?\s*[:=]\s*)(?!['\"])([^'\"\s,;#}}]+)")
    text = unquoted.sub(lambda m: m.group(1) + marker
                        if len(m.group(2)) >= 5 and m.group(2) != marker
                        else m.group(0), text)
    return text

def _snippet(lines: list[str], lineno: int, before=2, after=3) -> str:
    first = max(1, lineno - before)
    last = min(len(lines), lineno + after)
    return "\n".join(f"{i}: {redact_sensitive(lines[i - 1].rstrip()[:180])}" for i in range(first, last + 1))[:1250]


def index_repository(root: Path, paths: list[str], history: list[dict] | None = None) -> dict:
    """Deterministically index actual source definitions, code excerpts, docs, history."""
    files: list[dict] = []
    # Keep evidence from different concepts and files, instead of filling
    # the whole budget from repeated generic symbols near the repository root.
    # All candidates remain local and the final output is still bounded.
    evidence_by_concept: dict[str, list[dict]] = {term: [] for term in CONCEPTS}
    docs: list[dict] = []
    techs: set[str] = set()
    type_for_ext = {".cs": "C#", ".ts": "TypeScript", ".tsx": "React/TSX", ".js": "JavaScript",
                    ".jsx": "React/JSX", ".py": "Python", ".sql": "SQL", ".html": "HTML", ".css": "CSS"}
    for rel in paths[:1600]:
        path = safe_repo_file(root, rel)
        if path is None:
            continue
        if len(files) >= 500:
            break
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        files.append({"path": rel, "size": path.stat().st_size})
        if path.suffix in type_for_ext:
            techs.add(type_for_ext[path.suffix])
        if path.suffix.lower() in DOC_EXTS and len(docs) < MAX_DOCS:
            # Documentation is a source, not a command to the model.
            excerpt = "\n".join(x for x in lines if x.strip())[:650]
            if excerpt:
                docs.append({"path": rel, "excerpt": redact_sensitive(excerpt)})
        if path.suffix.lower() not in SOURCE_EXTS:
            continue
        hits_in_file: dict[str, int] = {}
        for lineno, line in enumerate(lines, 1):
            for concept, (pattern, _) in CONCEPTS.items():
                bucket=evidence_by_concept[concept]
                if (len(bucket)>=MAX_EVIDENCE or
                        hits_in_file.get(concept,0)>=2):
                    continue
                if re.search(pattern,line,flags=re.I):
                    bucket.append({"concept":concept,"path":rel,"line":lineno,
                                   "snippet":_snippet(lines,lineno),
                                   "line_text":redact_sensitive(line.strip()[:200])})
                    hits_in_file[concept]=hits_in_file.get(concept,0)+1
    evidence=[]
    for round_number in range(MAX_EVIDENCE):
        added=False
        for concept in CONCEPTS:
            bucket=evidence_by_concept[concept]
            if round_number<len(bucket):
                evidence.append(bucket[round_number])
                added=True
                if len(evidence)>=MAX_EVIDENCE:
                    break
        if not added or len(evidence)>=MAX_EVIDENCE:
            break
    return {"files": files, "total_files": len(files), "technologies": sorted(techs),
            "evidence": evidence, "documentation": docs, "history": (history or [])[:80],
            "collaboration": len({h.get('author_email','').casefold() for h in (history or []) if h.get('author_email')}) > 1}


def concept_from_text(text: str) -> set[str]:
    text = text.casefold()
    found = set()
    for concept, (_, aliases) in CONCEPTS.items():
        if any(re.search(r"(?<!\w)" + re.escape(a.casefold()) + r"(?!\w)", text, re.I) for a in aliases):
            found.add(concept)
    return found


def match_lesson_to_repository(transcript: str, analysis: dict | None, repo: dict, cap: int = 8) -> list[dict]:
    """Return conservative links. Code presence + lesson mention only; no authorship inference."""
    text = transcript[:160_000]
    if analysis:
        text += "\n" + "\n".join(str(c.get('nome','')) for c in analysis.get('conceitos',[]) if isinstance(c,dict))
    concepts = concept_from_text(text)
    found = []
    for e in repo.get('evidence',[]):
        if e['concept'] in concepts:
            if e['concept'] in {x['concept'] for x in found}:
                continue
            found.append(e)
            if len(found) >= cap:
                break
    return found


def find_code_line(repo: dict, path: str, line: int) -> dict | None:
    for e in repo.get('evidence',[]):
        if e['path'] == path and e['line'] == line:
            return e
    return None


def potential_transcript_corrections(transcript: str, repo: dict, cap=5) -> list[dict]:
    """Only probable terminology hints with *both* actual code and ambiguous speech.

    No edits to original transcript and no assertion that the professor said the term.
    """
    result = []
    low = transcript.casefold()
    observed = {e['concept']:e for e in repo.get('evidence',[])}
    for concept, (_, aliases) in CONCEPTS.items():
        if concept not in observed:
            continue
        for alias in aliases[1:]:
            if alias.casefold() in low and alias.casefold() != concept.casefold():
                evidence = observed[concept]
                result.append({"heard":alias, "candidate":concept, "status":"HIPÓTESE — revisar vídeo",
                               "path":evidence['path'],"line":evidence['line']})
                break
        if len(result) >= cap:
            break
    return result
