"""Offline ASR hints backed exclusively by identifiers from a frozen Git SHA.

Generic PT-BR/EN spelling and phonetic comparison; no sample-specific phrase
substitutions. A code name is a review clue, never proof of the audio.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .code_intel import is_generic_code_term

MIN_TOKEN_SIMILARITY = 0.70
MIN_SINGLE_TOKEN_SIMILARITY = 0.85
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
WORDS = re.compile(r"[a-z][a-z0-9]*|\d+")
FILLER = frozenset({
    "a", "as", "o", "os", "um", "uma", "de", "do", "da", "dos", "das",
    "e", "ou", "no", "na", "para", "por", "com", "que", "qual", "como",
    "acho", "talvez", "isso", "aquele", "aquela", "falou", "professor",
    "erro", "duvida", "quando", "eu", "ele", "ela", "ser", "esta", "estou",
    "usando", "chama", "chamou", "nome", "seria", "foi", "era", "tipo",
    "code", "codigo", "implementacao", "entao", "veja", "diz",
    "vamos", "fazer", "fez", "usou", "pasta", "sobre",
})
# A stand-alone common term is not a specific technical identifier. In
# particular, "manager de usuário" cannot prove UserManager or RoleManager.
AMBIGUOUS_SINGLETON = frozenset({
    "manager", "controller", "provider", "configuration", "service",
    "context", "class", "interface", "method", "framework", "model",
    "type", "entity", "user", "status", "created", "async",
})


def _ascii(value):
    return unicodedata.normalize("NFKD", str(value)).encode(
        "ascii", "ignore").decode("ascii").casefold()


def phonetic(token):
    """Symmetric, text-independent character rules for speech/code tokens."""
    result = _ascii(token)
    for before, after in (
        ("ph", "f"), ("ck", "k"), ("q", "k"), ("z", "s"),
        ("x", "s"), ("ai", "a"), ("ei", "e"), ("ou", "o"),
        ("oi", "o"), ("ow", "o"),
    ):
        result = result.replace(before, after)
    result = re.sub(r"^h", "", result)
    result = re.sub(r"([a-z])\1+", r"\1", result)
    # Silent final e in many English names (Role); makes 'rói' vs 'role'
    # comparable without any phrase/identifier-specific replacement.
    if len(result) >= 4 and result.endswith("e"):
        result = result[:-1]
    return result


def tokens(value, *, identifier=False):
    raw = WORDS.findall(_ascii(CAMEL.sub(" ", str(value))))
    # Interface prefix in C# naming (IEntityTypeConfiguration) is structural,
    # not a separate spoken word.
    if identifier and len(raw) > 1 and raw[0] == "i" and len(raw[1]) >= 5:
        raw = raw[1:]
    return [(word, phonetic(word)) for word in raw
            if word not in FILLER and len(word) >= 2]


def _similarity(first, second):
    if not first or not second:
        return 0.0
    if min(len(first), len(second)) >= 4 and (
            first.startswith(second) or second.startswith(first)):
        return 0.92
    return SequenceMatcher(None, first, second, autojunk=False).ratio()


def _ratio(spoken, expected):
    """One-to-one token alignments within a short contiguous speech window.

    Two *different* identifier tokens must match, unless a single distinctive
    identifier token >=6 chars scores >=.85. A common suffix alone is never
    enough to explain a whole compound name (e.g. 'manager' vs UserManager).
    """
    if not spoken or not expected:
        return None
    best = None
    window_size = min(9, max(6, len(expected) + 3))
    for offset in range(len(spoken)):
        window = spoken[offset:offset + window_size]
        pairs = sorted((
            (_similarity(candidate[1], heard[1]), i, j)
            for i, candidate in enumerate(expected)
            for j, heard in enumerate(window)
        ), reverse=True)
        matched = []
        expected_used, heard_used = set(), set()
        for similarity, i, j in pairs:
            if similarity < MIN_TOKEN_SIMILARITY:
                break
            if i in expected_used or j in heard_used:
                continue
            matched.append((i, j, similarity))
            expected_used.add(i)
            heard_used.add(j)
        count = len(matched)
        unique_long = (
            count == 1 and len(expected) == 1 and
            len(expected[matched[0][0]][1]) >= 6 and
            matched[0][2] >= MIN_SINGLE_TOKEN_SIMILARITY and
            expected[matched[0][0]][0] not in AMBIGUOUS_SINGLETON
        )
        if count < 2 and not unique_long:
            continue
        score = (count / len(expected), count,
                 sum(row[2] for row in matched) / count)
        if best is None or score > best:
            best = score
    return best


def match_frozen_question(question, repositories):
    """Only an immutable, verified lesson index is admissible evidence.

    Never consult a global/moving HEAD, even if the phrase looks similar.
    """
    if not isinstance(question, str) or not question.strip():
        return None
    spoken = tokens(question)
    status201 = bool(re.search(r"\bstatus\s*2011?\b", _ascii(question)))
    matches = []
    for repo, payload in repositories:
        if (not repo.get("frozen") or
                not re.fullmatch(r"[0-9a-f]{40}", repo.get("sha", ""))):
            continue
        for item in payload.get("identifiers", []):
            if not isinstance(item, dict):
                continue
            name, path, line = (
                item.get("name", ""), item.get("path", ""), item.get("line", 0))
            if (not isinstance(name, str) or is_generic_code_term(name) or
                    not isinstance(path, str) or not path or
                    type(line) is not int or line < 1):
                continue
            if name == "Created":
                if not (status201 and re.search(
                        r"\bCreated\s*\(", str(item.get("line_text", "")))):
                    continue
                score = (1.0, 2, 1.0)
            else:
                score = _ratio(spoken, tokens(name, identifier=True))
                if score is None:
                    continue
            snippet = item.get("snippet", "")
            if not isinstance(snippet, str) or not snippet.strip():
                continue
            matches.append({
                "kind": "codigo_congelado",
                "candidate": name,
                "observed": item.get("observed", name),
                "repo": repo["url"],
                "sha": repo["sha"],
                "version": repo.get("version", ""),
                "path": path,
                "line": line,
                "snippet": snippet[:900],
                "similarity": round(score[2], 3),
                "_line_text": str(item.get("line_text", "")),
                "_rank": score,
            })
    if not matches:
        return None
    # Prefer broad identifier coverage, then count of matched tokens and
    # character similarity. Deterministic path/line tie-breaking.
    matches.sort(key=lambda item: (
        -item["_rank"][0], -item["_rank"][1], -item["_rank"][2],
        # Prefer the actual class declaration of a synthesized DbContext
        # alias over a reference to the same class in a controller parameter.
        0 if (item["candidate"] == "DbContext" and
              re.search(r"\bclass\s+" +
                        re.escape(str(item.get("observed", ""))) + r"\b",
                        str(item.get("_line_text", "")))) else 1,
        item["path"], item["line"], item["candidate"],
    ))
    best = matches[0]
    best.pop("_rank", None)
    best.pop("_line_text", None)
    return best
