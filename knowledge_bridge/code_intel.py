"""Evidence-first, read-only indexing and cross-linking of programming repositories.

No builds, package installation, test execution, scripts, or imports from a repository.
A source match is evidence of code *presence*, not of authorship or learning.
"""
from __future__ import annotations

import re
import unicodedata
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

# Single language keywords are not proof of correspondence or ASR errors.
# Keep concrete symbols such as DeliveryController, HttpClient and DbContext.
GENERIC_LANGUAGE_TERMS = frozenset({
    "class", "classes", "classe", "interface", "interfaces", "public",
    "private", "protected", "static", "namespace", "using", "string", "void",
    "method", "methods", "metodo", "metodos", "controller", "controllers",
})


def is_generic_code_term(value: object) -> bool:
    if not isinstance(value, str):
        return False
    plain = unicodedata.normalize("NFKD", value.strip()).encode(
        "ascii", "ignore").decode("ascii").casefold()
    return plain in GENERIC_LANGUAGE_TERMS


SENSITIVE_NAMES = (
    ".env", "secret", "credential", "private", "password", "token", "appsettings",
    "key.json", "key.pem", "id_rsa", "package-lock", "yarn.lock", "pnpm-lock"
)
SOURCE_EXTS = {".cs", ".ts", ".tsx", ".js", ".jsx", ".py", ".sql", ".html", ".css"}
DOC_EXTS = {".md", ".txt"}
MAX_FILE_BYTES = 100_000
MAX_EVIDENCE = 160
MAX_DOCS = 12
MAX_SYMBOLS = 240
MAX_CODE_IDENTIFIERS = 3000
# Actual C#/TS/Python identifier tokens, not guesses from surrounding prose.
# Values must occur literally on a verified source line at the frozen SHA.
CODE_IDENTIFIER = re.compile(r"\b[A-Z][A-Za-z0-9_]{2,89}\b")
SYMBOL_DECLARATION = re.compile(
    r"\b(?:class|interface|enum|struct|record|function|def)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\b"
)


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


def index_repository(root: Path, paths: list[str], history: list[dict] | None = None, *,
                     read_source=None) -> dict:
    """Deterministically index actual source definitions, code excerpts, docs, history."""
    files: list[dict] = []
    # Keep evidence from different concepts and files, instead of filling
    # the whole budget from repeated generic symbols near the repository root.
    # All candidates remain local and the final output is still bounded.
    evidence_by_concept: dict[str, list[dict]] = {term: [] for term in CONCEPTS}
    docs: list[dict] = []
    symbols_by_file: list[list[dict]] = []
    identifiers_by_file: list[list[dict]] = []
    techs: set[str] = set()
    type_for_ext = {".cs": "C#", ".ts": "TypeScript", ".tsx": "React/TSX", ".js": "JavaScript",
                    ".jsx": "React/JSX", ".py": "Python", ".sql": "SQL", ".html": "HTML", ".css": "CSS"}
    for rel in paths[:1600]:
        if len(files) >= 500:
            break
        if read_source is None:
            path = safe_repo_file(root, rel)
            if path is None:
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            size = path.stat().st_size
            suffix = path.suffix.lower()
        else:
            # The remote reader verifies Git tree blob hashes and permits only
            # UTF-8 files below the same local indexer's size limit.
            if (not isinstance(rel, str) or not rel or "\\" in rel or
                    rel.startswith(("/", "-")) or
                    any(p in (".", "..", "") for p in rel.split("/")) or
                    any(word in rel.casefold() for word in SENSITIVE_NAMES)):
                continue
            suffix = Path(rel).suffix.lower()
            if suffix not in SOURCE_EXTS | DOC_EXTS | {".json"}:
                continue
            source = read_source(rel)
            if source is None:
                continue
            body, size = source
            if (not isinstance(body, str) or type(size) is not int or
                    size < 0 or size > MAX_FILE_BYTES):
                continue
        lines = body.splitlines()
        files.append({"path": rel, "size": size})
        if suffix in type_for_ext:
            techs.add(type_for_ext[suffix])
        if suffix in DOC_EXTS and len(docs) < MAX_DOCS:
            # Documentation is a source, not a command to the model.
            excerpt = "\n".join(x for x in lines if x.strip())[:650]
            if excerpt:
                docs.append({"path": rel, "excerpt": redact_sensitive(excerpt)})
        if suffix not in SOURCE_EXTS:
            continue
        hits_in_file: dict[str, int] = {}
        symbols_in_file: list[dict] = []
        identifiers_in_file: list[dict] = []
        seen_identifiers = set()
        for lineno, line in enumerate(lines, 1):
            # Literal declarations only; no guessed symbol from a comment or
            # an unverified model output. Four per file keeps the index small.
            if len(symbols_in_file)<4 and not line.lstrip().startswith(("//", "#", "*", "/*")):
                match=SYMBOL_DECLARATION.search(line)
                if match:
                    name=match.group(1)
                    if 4<=len(name)<=90 and name.casefold() not in {"class", "function", "interface"}:
                        symbols_in_file.append({
                            "name":name,"concept":name,"path":rel,"line":lineno,
                            "snippet":_snippet(lines,lineno),
                            "line_text":redact_sensitive(line.strip()[:200])
                        })
            if (len(identifiers_in_file) < 90 and
                    not line.lstrip().startswith(("//", "#", "*", "/*"))):
                # Include methods/invocations/type interfaces even when they
                # are not declarations; the stored path/line stays verifiable.
                for found in CODE_IDENTIFIER.finditer(line[:300]):
                    name = found.group()
                    if (is_generic_code_term(name) or name in seen_identifiers
                            or name in {"Guid", "String", "Int32", "Task", "True", "False",
                                        "HttpPost", "AllowAnonymous", "Route", "ApiController"}):
                        continue
                    seen_identifiers.add(name)
                    item = {
                        "name":name,"path":rel,"line":lineno,
                        "line_text":redact_sensitive(line.strip()[:200]),
                        "snippet":_snippet(lines,lineno,before=1,after=1),
                    }
                    identifiers_in_file.append(item)
                    # A class derived from/ending with DbContext is literal
                    # evidence of that specific framework concept, not a
                    # fabricated freestanding declaration of DbContext.
                    if (name.endswith("DbContext") and name != "DbContext"
                            and "DbContext" not in seen_identifiers
                            and re.search(r"\bclass\s+" + re.escape(name) + r"\b", line)):
                        # A canonical DbContext alias needs an actual class
                        # declaration, not an arbitrary parameter reference.
                        seen_identifiers.add("DbContext")
                        identifiers_in_file.append({**item,
                            "name":"DbContext", "observed":name})
                    if len(identifiers_in_file) >= 90:
                        break
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
        if symbols_in_file:
            symbols_by_file.append(symbols_in_file)
        if identifiers_in_file:
            identifiers_by_file.append(identifiers_in_file)
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
    symbols=[]
    for round_number in range(4):
        for batch in symbols_by_file:
            if round_number<len(batch):
                symbols.append(batch[round_number])
                if len(symbols)>=MAX_SYMBOLS:
                    break
        if len(symbols)>=MAX_SYMBOLS:
            break
    identifiers=[]
    # Round robin: one file cannot monopolize snapshot identity evidence.
    for round_number in range(90):
        for batch in identifiers_by_file:
            if round_number < len(batch):
                identifiers.append(batch[round_number])
                if len(identifiers) >= MAX_CODE_IDENTIFIERS:
                    break
        if len(identifiers) >= MAX_CODE_IDENTIFIERS:
            break
    return {"files": files, "total_files": len(files), "technologies": sorted(techs),
            "evidence": evidence, "symbols":symbols, "identifiers": identifiers,
            "documentation": docs, "history": (history or [])[:80],
            "collaboration": len({h.get('author_email','').casefold() for h in (history or []) if h.get('author_email')}) > 1}


def concept_from_text(text: str) -> set[str]:
    text = text.casefold()
    found = set()
    for concept, (_, aliases) in CONCEPTS.items():
        if is_generic_code_term(concept):
            continue
        if any(re.search(r"(?<!\w)" + re.escape(a.casefold()) + r"(?!\w)", text, re.I) for a in aliases):
            found.add(concept)
    return found


def match_lesson_to_repository(transcript: str, analysis: dict | None, repo: dict, cap: int = 8) -> list[dict]:
    """Return conservative links. Code presence + lesson mention only; no authorship inference."""
    # The transcript, not a model-generated concept list, is the source of
    # truth for candidate links. Historic caches and manually imported
    # analyses can contain ungrounded terms. Appending them here allowed a
    # hallucinated concept to link to real but unrelated code.
    text = transcript[:160_000]
    concepts = concept_from_text(text)
    found = []
    seen=set()
    for e in repo.get('evidence',[]):
        if (not isinstance(e, dict) or is_generic_code_term(e.get('concept'))):
            continue
        if e['concept'] in concepts and e['concept'] not in seen:
            found.append(e)
            seen.add(e['concept'])
            if len(found)>=cap:
                return found
    # Additional links to actual declared C#/TS/Python names seen literally
    # in the lesson or extracted concepts. No fuzzy name guesses or authorship.
    for e in repo.get('symbols',[]):
        if not isinstance(e,dict):
            continue
        name=e.get('name','')
        if (not isinstance(name,str) or len(name)<4 or
                is_generic_code_term(name) or
                not re.search(r"(?<![A-Za-z0-9_])"+re.escape(name)+r"(?![A-Za-z0-9_])",
                              text,re.I) or name.casefold() in seen):
            continue
        found.append(e)
        seen.add(name.casefold())
        if len(found)>=cap:
            break
    return found


def find_code_line(repo: dict, path: str, line: int) -> dict | None:
    # A declared name is more specific than the generic 'class' signal
    # when both refer to the same source line.
    for e in [*repo.get('symbols',[]),*repo.get('evidence',[])]:
        if e.get('path') == path and e.get('line') == line:
            return e
    return None


def potential_transcript_corrections(transcript: str, repo: dict, cap=5) -> list[dict]:
    """Only probable terminology hints with *both* actual code and ambiguous speech.

    No edits to original transcript and no assertion that the professor said the term.
    """
    result = []
    low = transcript.casefold()
    observed = {e['concept']:e for e in repo.get('evidence',[])
                if isinstance(e, dict) and not is_generic_code_term(e.get('concept'))}
    for concept, (_, aliases) in CONCEPTS.items():
        if is_generic_code_term(concept) or concept not in observed:
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
