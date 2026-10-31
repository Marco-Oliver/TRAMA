"""Auditoria longitudinal de dúvidas, somente evidências de fontes originais.

Não é um corretor automático. Fontes futuras e trechos Git são pistas de
revisão: jamais comprovam o que foi dito numa gravação anterior.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .code_intel import CONCEPTS
from .content import timed_lines
from .memory_atlas import lesson_order, norm


def _contains_term(raw: str, term: str) -> bool:
    key = norm(term)
    return bool(key and re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", norm(raw)))


def _candidate(question: str) -> str:
    """Identify only known technical aliases; no semantic guesses from an LLM."""
    candidates = []
    for canonical, (_pattern, aliases) in CONCEPTS.items():
        for alias in (canonical, *aliases):
            if _contains_term(question, alias):
                candidates.append((len(norm(alias)), canonical))
    return max(candidates)[1] if candidates else ""


def _source_text(store, source) -> str | None:
    path = (store.vault / (source["stored_path"] or "")).resolve()
    if not path.is_relative_to(store.vault) or not path.is_file():
        return None
    # Never trust a changed attachment as evidence for a different digest.
    if path.stat().st_size > 20 * 1024 * 1024:
        return None
    from .content import file_hash
    if file_hash(path) != source["digest"]:
        return None
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _later_evidence(question, candidate, original, later, repositories):
    """Evidence always cites raw future transcript or real repository index."""
    result = []
    if candidate:
        terms = [candidate, *CONCEPTS.get(candidate, (None, []))[1]]
        # Do not use only a doubtful phonetic spelling as independent evidence.
        candidates = [t for t in terms if norm(t) == norm(candidate) or
                      not _contains_term(original, t)]
        for source, raw in later:
            if not any(_contains_term(raw, term) for term in candidates):
                continue
            anchors = [(stamp, excerpt[:200]) for stamp, excerpt in timed_lines(raw)
                       if any(_contains_term(excerpt, t) for t in candidates)]
            result.append({"kind": "aula_posterior", "source_id": source["id"],
                           "lesson": source["lesson"], "label": source["label"],
                           "digest": source["digest"], "timestamp": anchors[0][0] if anchors else "",
                           "excerpt": anchors[0][1] if anchors else ""})
            if len(result) >= 5:
                break
        for repository in repositories:
            payload = repository["payload"]
            for item in payload.get("evidence", []):
                if norm(item.get("concept", "")) == norm(candidate):
                    result.append({"kind": "codigo", "repo": repository["url"],
                                   "sha": repository["sha"], "path": item["path"],
                                   "line": item["line"], "concept": item["concept"]})
                    break
            if len(result) >= 8:
                break
    return result


def refresh_uncertainties(store) -> dict:
    """Idempotent incremental reconciliation; never consumes API calls."""
    sources = sorted(store.sources("transcript"),
                     key=lambda s: (lesson_order(s["lesson"] or ""), s["video"] or "", s["label"]))
    loaded = [(s, raw) for s in sources if (raw := _source_text(store, s)) is not None]
    repositories = []
    for repo in store.repositories():
        try:
            payload = json.loads(repo["payload"])
            repositories.append({"url": repo["url"], "sha": repo["sha"], "payload": payload})
        except (TypeError, ValueError):
            continue

    active = set()
    for src, raw in loaded:
        analysis = store.analysis(src["id"], src["digest"])
        if not analysis:
            continue
        questions = [str(x).strip()[:350] for x in analysis.get("duvidas", [])
                     if isinstance(x, str) and x.strip()]
        for question in dict.fromkeys(questions):
            uid = hashlib.sha256((src["id"] + "\0" + question.casefold()).encode()).hexdigest()[:32]
            active.add(uid)
            candidate = _candidate(question)
            later = [(s, text) for s, text in loaded
                     if src["lesson"] and s["lesson"] and
                     lesson_order(s["lesson"]) > lesson_order(src["lesson"])]
            evidence = _later_evidence(question, candidate, question, later, repositories)
            state = "NOVA_EVIDENCIA_PARA_REVISAR" if evidence else (
                "HIPOTESE_SEM_CONFIRMACAO" if candidate else "PENDENTE")
            store.upsert_uncertainty(uid, src["id"], src["digest"], src["label"],
                                     question, candidate, state, evidence)

    # Stale hypotheses are never erased; a changed analysis marks them obsolete.
    for item in store.uncertainties():
        if item["id"] not in active and item["status"] != "ARQUIVADA_FONTE_ALTERADA":
            store.upsert_uncertainty(
                item["id"], item["source_id"], item["source_digest"], item["label"],
                item["question"], item["candidate"], "ARQUIVADA_FONTE_ALTERADA", [])
    return {"questions": len(active), "with_evidence": sum(
        row["status"] == "NOVA_EVIDENCIA_PARA_REVISAR" for row in store.uncertainties())}


def _safe(text: object, limit: int = 350) -> str:
    """Display source text as one quoted line, not executable Markdown/HTML."""
    raw = str(text).replace("\n", " ").replace("\r", " ").strip()[:limit]
    return raw.replace("<", "&lt;").replace(">", "&gt;").replace("[[", "［［").replace("]]", "］］")


def render_uncertainties(store) -> tuple[str, list[tuple[str, str]]]:
    rows = store.uncertainties()
    output = ["# Dúvidas para revisar", "",
              "> Perguntas extraídas por IA, NÃO são fatos confirmados nem correções automáticas.",
              "> Um termo encontrado em outra aula/código é uma pista; confira a gravação original.",
              "", f"**Dúvidas registradas:** {len(rows)}", ""]
    notes = []
    for row in rows:
        events = store.uncertainty_events(row["id"])
        evidence = json.loads(row["evidence_json"])
        rel = f"01-Meu-Conhecimento/Duvidas/{row['id']}.md"
        from .memory_atlas import note_for
        src = store.get_source(row["source_id"])
        lesson = Path(note_for(src)).with_suffix("").as_posix() if src else ""
        body = [f"# Dúvida — {_safe(row['label'], 80)}", "",
                f"**Questão original sinalizada:** {_safe(row['question'])}", "",
                f"**Estado:** `{row['status']}`", "",
                "**Termo técnico candidato:** " + (f"`{_safe(row['candidate'],90)}`" if row["candidate"] else "*não identificado*"),
                "", f"**Fonte:** [[{lesson}|{_safe(row['label'],100)}]]" if lesson else
                "**Fonte:** indisponível no índice atual", "",
                f"**Digest original:** `{row['source_digest'][:12]}`", "",
                "## Evidências adicionais (não são confirmação)", ""]
        if not evidence:
            body.append("*Nenhuma evidência posterior suficientemente específica encontrada.*")
        for e in evidence:
            if e["kind"] == "aula_posterior":
                stamp = f" ({_safe(e['timestamp'],20)})" if e["timestamp"] else ""
                body.append(f"- Outra aula: **{_safe(e['lesson'],50)}**{stamp}, "
                            f"transcrição `{_safe(e['label'],80)}` — {_safe(e['excerpt'],200)}.")
            else:
                body.append(f"- Repositório: `{_safe(e['repo'],180)}`, "
                            f"commit `{_safe(e['sha'][:12])}`, "
                            f"arquivo `{_safe(e['path'],180)}:{e['line']}`.")
        body += ["", "## Histórico da revisão", ""]
        for ev in events:
            body.append(f"- {ev['created_at']} — **{ev['status']}** "
                        f"(evidências: `{ev['evidence_digest'][:12]}`).")
        body += ["", "## Próxima conferência", "",
                 "Confira a transcrição e, se necessário, o vídeo original. "
                 "O TRAMA não altera a fala do professor nem declara a dúvida resolvida por conta própria."]
        notes.append((rel, "\n".join(body) + "\n"))
        output.append(f"- [[{row['id']}|{_safe(row['question'],100)}]] — "
                      f"`{row['status']}`")
    if not rows:
        output.append("*Nenhuma dúvida identificada nas análises cadastradas.*")
    return "\n".join(output) + "\n", notes
