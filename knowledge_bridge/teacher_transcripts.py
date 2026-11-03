"""Retrieval of registered lesson transcripts for the read-only IA Professor.

Catalog references are untrusted: only verified local TXT files in the
TRAMA-managed attachment directory may be read, and only short excerpts
(with their original timestamps) enter an explicitly authorized prompt.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import unicodedata
from urllib.parse import quote

from .content import timed_lines
from .code_intel import redact_sensitive

MAX_SOURCE_BYTES = 2_000_000
MAX_TRANSCRIPT_CONTEXT = 1550
MAX_TRANSCRIPTS_PER_ANSWER = 2
MAX_TIMED_ROWS = 12_000
LESSON_RE = re.compile(r"^Aula-\d{3,4}$")
STUDY_ROOT = ("99-Anexos", "Transcricoes-Originais")


def _normalize(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return set(re.findall(r"[a-z0-9]{3,}", normalized))


def _lesson(source: dict) -> str:
    """Lessons are taken from generated note metadata or its fixed folder."""
    if source.get("section") != "02-Minhas-Aulas":
        return ""
    stated = source.get("lesson", "")
    if isinstance(stated, str) and LESSON_RE.fullmatch(stated):
        return stated
    parts = source.get("id", "").split("/")
    return parts[1] if len(parts) >= 3 and LESSON_RE.fullmatch(parts[1]) else ""


def _load_verified(vault: Path, stored: str, digest: str) -> str | None:
    """Reject missing, modified, oversized, or symlinked transcripts."""
    if not isinstance(stored, str) or not isinstance(digest, str):
        return None
    parts = stored.split("/")
    if (len(parts) != 3 or tuple(parts[:2]) != STUDY_ROOT
            or not parts[-1].lower().endswith(".txt")
            or any(part in ("", ".", "..") for part in parts)
            or len(stored) > 450
            or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)):
        return None
    root = vault.resolve()
    path = root.joinpath(*parts)
    try:
        if any(root.joinpath(*parts[:depth]).is_symlink()
               for depth in range(1, len(parts) + 1)):
            return None
        if not path.resolve().is_relative_to(root):
            return None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE_BYTES:
                return None
            raw = source.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES or hashlib.sha256(raw).hexdigest() != digest.lower():
            return None
        return raw.decode("utf-8-sig", errors="replace")
    except (OSError, ValueError, UnicodeError):
        return None


def _extract_timed_excerpt(raw: str, question_terms: list[str], question: str):
    """Return a few high-scoring contiguous windows, never an entire recording."""
    if not question_terms:
        return "", []
    rows = timed_lines(raw)[:MAX_TIMED_ROWS]
    terms = set(question_terms)
    if "dotnet" in terms:
        terms.update(("net", "sdk"))
    command_question = bool(re.search(r"(?i)comand|terminal|instal|execut|digita|sdk", question))
    scores = []
    for idx, (_, utterance) in enumerate(rows):
        words = _normalize(utterance)
        overlap = len(words & terms)
        technical = bool(words & {"terminal", "comando", "comandos",
                                   "digitar", "digitando", "executar", "instalar", "sdk"})
        score = overlap * 4 + (3 if command_question and technical and overlap else 0)
        if score:
            scores.append((score, idx))
    scores.sort(key=lambda row: (-row[0], row[1]))
    windows = []
    used = set()
    for _, idx in scores:
        if len(windows) >= 3:
            break
        start, end = max(0, idx - 3), min(len(rows), idx + 7)
        if any(i in used for i in range(start, end)):
            continue
        used.update(range(start, end))
        windows.append((start, end))
    # Keep original chronological order; each quoted line retains a real timestamp.
    chunks = []
    times = []
    for start, end in sorted(windows):
        items = []
        for stamp, sentence in rows[start:end]:
            if stamp == "sem horário":
                continue
            line = f"[{stamp}] {sentence.strip()}"
            if line and sum(len(t) for t in items) + len(line) > 680:
                break
            items.append(line)
            if stamp not in times:
                times.append(stamp)
        if items:
            chunks.append("\n".join(items))
    return "\n\n".join(chunks)[:MAX_TRANSCRIPT_CONTEXT], times[:12]


def attach_transcript_evidence(vault: Path, sources: list[dict],
                               question_terms: list[str], question: str) -> list[dict]:
    """Append read-only, digest-verified transcript evidence to lesson notes.

    The citation stays anchored to its genuine lesson Markdown file. The stored
    transcript path is returned to the UI only for an explicitly clicked Open
    action, never as a title/path in the external model prompt.
    """
    if not sources or not question_terms:
        return sources
    root = vault.resolve()
    db = root / ".base-conhecimento" / "estado.sqlite3"
    if db.is_symlink() or db.parent.is_symlink() or not db.is_file():
        return sources
    try:
        with closing(sqlite3.connect(
            f"file:{quote(db.as_posix())}?mode=ro", uri=True, timeout=1
        )) as connection:
            rows = connection.execute(
                "SELECT id,lesson,stored_path,digest,label FROM sources "
                "WHERE kind='transcript' ORDER BY lesson,label LIMIT 10000"
            ).fetchall()
    except (sqlite3.Error, OSError):
        return sources
    by_lesson = {}
    for source_id, lesson, stored, digest, label in rows:
        if isinstance(lesson, str) and LESSON_RE.fullmatch(lesson):
            by_lesson.setdefault(lesson, []).append((source_id, stored, digest, label))

    enriched = []
    attached = 0
    processed = set()
    for source in sources:
        entry = dict(source)
        lesson = _lesson(entry)
        if (lesson and lesson not in processed and
                attached < MAX_TRANSCRIPTS_PER_ANSWER):
            processed.add(lesson)
            available = by_lesson.get(lesson, [])
            # Precise source notes should favor their own recording, not the
            # adjacent lecture's recording sharing the same lesson number.
            preferred_id = entry.get("source_id")
            available = sorted(available, key=lambda r: r[0] != preferred_id)
            for _, stored, digest, label in available:
                if attached >= MAX_TRANSCRIPTS_PER_ANSWER:
                    break
                transcript = _load_verified(root, stored, digest)
                if transcript is None:
                    continue
                excerpt, stamps = _extract_timed_excerpt(transcript, question_terms, question)
                if not excerpt:
                    continue
                # Reserve space for the original note, while preferring raw
                # evidence if the note is only a placeholder awaiting analysis.
                old_excerpt = entry.get("excerpt", "")
                limit = 1000 if "Pendente:" in old_excerpt or "Aguardando" in old_excerpt else 1250
                # Transcribed instructions targeting the model must not
                # become operating instructions. Commands taught in class stay.
                safe_lines = []
                for line in excerpt.splitlines():
                    if re.search(
                        r"(?i)(?:ignore\s+(?:todas?\s+as\s+|as\s+|previous\s+)?"
                        r"(?:regras|instruções|instrucoes|instructions)|"
                        r"envie\s+(?:as?\s+)?(?:senhas|tokens|chaves)|"
                        r"system\s+prompt|developer\s+message)", line
                    ):
                        safe_lines.append("[INSTRUÇÃO NÃO CONFIÁVEL OMITIDA]")
                    else:
                        safe_lines.append(line)
                excerpt = redact_sensitive("\n".join(safe_lines))
                evidence = f"\n\nTRANSCRIÇÃO ORIGINAL (trechos literais, horários não conferidos no vídeo):\n{excerpt}"
                entry["excerpt"] = old_excerpt[:limit] + evidence[:1800]
                entry["transcript_times"] = stamps[:6]
                entry["transcript_label"] = str(label)[:130]
                entry["transcript_stored"] = stored
                attached += 1
                break
        enriched.append(entry)
    return enriched
