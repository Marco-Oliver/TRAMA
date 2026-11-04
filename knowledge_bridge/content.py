"""Funções puras para entender fontes, nomes e trechos de transcrições."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

MODULES = {
    "Logica-de-Programacao": ["algoritmo", "variável", "variavel", "condicional", "laço", "laco", "foreach", "console"],
    "Programacao-Orientada-a-Objetos": ["classe", "objeto", "herança", "heranca", "polimorfismo", "encapsulamento", "interface", "construtor"],
    "Desenvolvimento-Web": ["html", "css", "http", "mvc", "asp.net", "website"],
    "Banco-de-Dados": ["sql", "banco de dados", "entity framework", "migration", "tabela", "relacional"],
    "Testes": ["teste unitário", "teste unitario", "xunit", "tdd", "assert", "mock"],
    "APIs-e-Backend": ["controller", "api", "endpoint", "swagger", "mensageria", "webapi", "dto"],
    "Frontend": ["angular", "react", "rxjs", "subscribe", "componente", "typescript", "signal"],
    "Desenvolvimento-Agentico": ["agente", "agentic", "mcp", "llm", "prompt"],
    "TCC": ["tcc", "trabalho de conclusão", "projeto integrador"],
}

TIMESTAMP = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")
IN_TEXT_TIME = re.compile(r"\[(\d{1,2}:)?\d{1,2}:\d{2}\]")
AULA_RE = re.compile(r"(?i)(?:\baula[\s._-]*|(?<![a-z])a[\s._-]*)(\d{1,3})(?!\d)")
VIDEO_RE = re.compile(r"(?i)(?<![a-z])v[\s._-]*(\d{1,2})(?!\d)")


def slug(text: str, maxlen: int = 75) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return value[:maxlen].strip("-") or "sem-titulo"


def concept_slug(text: str, maxlen: int = 75) -> str:
    """Preserve programming symbols that ordinary slugification would merge.

    For example C#, C++ and C all used to share one note named `c.md`.
    This does not merge aliases semantically; only makes filenames unique.
    """
    tagged = (text.strip().replace('#', '-sharp-').replace('++', '-plus-plus-')
              .replace('+', '-plus-'))
    return slug(tagged, maxlen)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def lesson_identity(name: str) -> tuple[str | None, str | None]:
    lesson = AULA_RE.search(name)
    video = VIDEO_RE.search(name)
    return (f"Aula-{int(lesson.group(1)):03d}" if lesson else None,
            f"V{int(video.group(1)):02d}" if video else None)


def timed_lines(text: str) -> list[tuple[str, str]]:
    """Aceita 'texto\\n0:04\\ntexto...' do Drive e '[0:04] texto'."""
    items: list[tuple[str, str]] = []
    current_time = "sem horário"
    buffer: list[str] = []
    def flush():
        if buffer:
            joined = " ".join(x.strip() for x in buffer if x.strip()).strip()
            if joined:
                items.append((current_time, joined))
            buffer.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if TIMESTAMP.fullmatch(line):
            flush()
            current_time = line
        else:
            m = re.match(r"^\[((?:\d{1,2}:)?\d{1,2}:\d{2})\]\s*(.*)$", line)
            if m:
                flush()
                current_time = m.group(1)
                buffer.append(m.group(2))
            else:
                buffer.append(line)
    flush()
    return items


def chunks(text: str, max_chars: int = 11500) -> list[str]:
    sections = timed_lines(text)
    if not sections:
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)] or [""]
    output: list[str] = []
    current = ""
    for time, sentence in sections:
        line = f"[{time}] {sentence}\n"
        if len(line) > max_chars:
            if current:
                output.append(current.strip())
                current = ""
            output.extend(line[i:i + max_chars] for i in range(0, len(line), max_chars))
            continue
        if len(current) + len(line) > max_chars and current:
            output.append(current.strip())
            current = ""
        current += line
    if current:
        output.append(current.strip())
    return output or [text]



def opening_lesson_number_mismatch(
    text: str, lesson: str, max_seconds: int = 90
) -> tuple[str, int] | None:
    """Flag conflicting opening lesson labels; never renumber user sources.

    Early speech-to-text can be wrong, and a professor may reference a past
    lesson. This is only a review hint, not a factual correction.
    """
    expected = re.fullmatch(r"Aula-(\d{1,3})", str(lesson))
    if not expected:
        return None
    expected_number = int(expected.group(1))
    for stamp, spoken in timed_lines(text)[:100]:
        parts = stamp.split(":")
        if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
            continue
        sec = (int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2
               else int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
        if sec > max_seconds:
            break
        match = re.search(
            r"\b(?:aula|aulinha)\s*(?:n(?:ú|u)mero\s*)?(\d{1,3})\b",
            spoken, flags=re.IGNORECASE)
        if match:
            spoken_number = int(match.group(1))
            if spoken_number != expected_number:
                return stamp, spoken_number
            return None
    return None


def guess_modules(text: str) -> list[str]:
    haystack = text.lower()
    matches = sorted(((sum(haystack.count(word) for word in words), module)
                      for module, words in MODULES.items()), reverse=True)
    best = matches[0][0] if matches else 0
    threshold = max(2, best * 0.20)
    return [module for score, module in matches if score >= threshold][:3] or ["A-Classificar"]


def evidence_excerpt(text: str, limit: int = 4) -> list[tuple[str, str]]:
    items = timed_lines(text)
    if not items:
        return []
    step = max(1, len(items) // limit)
    return [(t, s[:260]) for t, s in items[::step][:limit]]


def study_windows(text: str, limit: int = 4, span: int = 8) -> list[tuple[str, str]]:
    """Useful chronological windows without pretending to summarize a lesson.

    Each timestamp comes literally from the original transcript. Only the
    neighboring text is joined, and no LLM or factual inference is involved.
    """
    rows = [(time, sentence) for time, sentence in timed_lines(text)
            if time != "sem horário" and sentence.strip()]
    if not rows:
        return []
    count = min(max(1, limit), len(rows))
    stride = max(1, len(rows) // count)
    out = []
    seen = set()
    for index in range(count):
        start = min(index * stride, len(rows) - 1)
        if start in seen:
            continue
        seen.add(start)
        stamp = rows[start][0]
        text_window = " ".join(value.strip() for _, value in rows[start:start + span])
        out.append((stamp, text_window[:440]))
    return out
