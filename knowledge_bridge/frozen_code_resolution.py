"""Offline phonetic matches against identifiers in an immutable lesson Git snapshot.

This is only an ASR/code hypothesis. It never rewrites the transcript or
infers what was actually said. The caller must supply a frozen lesson index.
"""
from __future__ import annotations

import re
import unicodedata

from .code_intel import is_generic_code_term

MIN_TOKEN_RATIO = 0.75
WORDS = re.compile(r"[a-z][a-z0-9]*|\d+")
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
FILLER = frozenset({
    "a", "as", "o", "os", "um", "uma", "de", "do", "da", "dos", "das",
    "e", "ou", "no", "na", "para", "por", "com", "que", "qual", "como",
    "acho", "talvez", "isso", "aquele", "aquela", "falou", "professor",
    "erro", "duvida", "quando", "eu", "ele", "ela", "ser", "esta", "estou",
    "usando", "chama", "chamou", "nome", "seria", "foi", "era", "tipo",
    "code", "codigo", "implementacao", "entao", "veja", "acho", "diz",
})


def _ascii(text):
    return unicodedata.normalize("NFKD", str(text)).encode(
        "ascii", "ignore").decode("ascii").casefold()


def tokens(value, *, identifier=False):
    text = CAMEL.sub(" ", str(value))
    text = _ascii(text)
    if not identifier:
        # Narrow phonetic equivalences supported by typical PT-BR ASR.
        # These only become evidence if a matching identifier is in code.
        for before, after in (
            (r"\bsaind\s+assim\b", "sign in async"),
            (r"\bsign\s+in\s+assim\b", "sign in async"),
            (r"\bsign\s+in\s+assing\b", "sign in async"),
            (r"\bin\s+type\s+configuration\b", "entity type configuration"),
            (r"\bentity\s+type\s+configuration\b", "entity type configuration"),
            (r"\bcontact\b", "context"),
            (r"\btesc\b", "task"),
        ):
            text = re.sub(before, after, text)
    result = WORDS.findall(text)
    if identifier and len(result) >= 3 and result[0] == "i":
        result = result[1:]  # IEntityTypeConfiguration
    return [word for word in result if word not in FILLER and len(word) > 1]


def _ratio(spoken, expected):
    if not expected or len(expected) < 2 or not spoken:
        return 0.0
    # Token evidence must be close together, not spread across an unrelated
    # lecture. Multiple distinct matches are required; stopwords never count.
    best = 0.0
    limit = max(8, len(expected) + 5)
    for offset in range(max(1, len(spoken) - limit + 1)):
        window = set(spoken[offset:offset + limit])
        hits = sum(word in window for word in expected)
        best = max(best, hits / len(expected))
        if best == 1.0:
            break
    return best


def match_frozen_question(question, repositories):
    """Return verifiable identifiers with paths/lines ONLY from frozen SHAs.

    An unregistered lesson's global main/HEAD index is never consulted here.
    """
    if not isinstance(question, str) or not question.strip():
        return None
    phrase = tokens(question)
    status201 = bool(re.search(r"\bstatus\s*2011?\b", _ascii(question)))
    matches = []
    for repo, payload in repositories:
        if not repo.get("frozen") or not re.fullmatch(r"[0-9a-f]{40}", repo.get("sha", "")):
            continue
        for entry in payload.get("identifiers", []):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            path = entry.get("path", "")
            line = entry.get("line", 0)
            if (not isinstance(name, str) or is_generic_code_term(name)
                    or not isinstance(path, str) or not path
                    or type(line) is not int or line < 1):
                continue
            expected = tokens(name, identifier=True)
            ratio = _ratio(phrase, expected)
            # ASP.NET Core Created(...) conventionally produces HTTP 201. This
            # is a narrow API clue; no generic status-code string substitution.
            if (name == "Created" and status201 and
                    re.search(r"\bCreated\s*\(", entry.get("line_text", ""))):
                ratio = 0.96
            elif len(expected) < 2 or ratio < MIN_TOKEN_RATIO:
                continue
            if ratio < MIN_TOKEN_RATIO:
                continue
            snippet = entry.get("snippet", "")
            if not isinstance(snippet, str) or not snippet.strip():
                continue
            matches.append({
                "kind": "codigo_congelado",
                "candidate": name,
                "observed": entry.get("observed", name),
                "repo": repo["url"],
                "sha": repo["sha"],
                "version": repo.get("version", ""),
                "path": path,
                "line": line,
                "snippet": snippet[:900],
                "similarity": round(ratio, 3),
            })
    if not matches:
        return None
    # Strong evidence and shorter exact technical identifiers win; prefer
    # first line when a single symbol is repeated across a file.
    matches.sort(key=lambda row: (
        -row["similarity"],
        0 if row["candidate"].casefold() in _ascii(question).replace(" ", "") else 1,
        len(row["candidate"]),
        row["path"], row["line"],
    ))
    return matches[0]
