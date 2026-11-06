"""Auditoria longitudinal de dúvidas, somente evidências de fontes originais.

Não é um corretor automático. Fontes futuras e trechos Git são pistas de
revisão: jamais comprovam o que foi dito numa gravação anterior.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .code_intel import CONCEPTS, is_generic_code_term
from .frozen_code_resolution import match_frozen_question
from urllib.parse import quote
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
            if is_generic_code_term(canonical) or is_generic_code_term(alias):
                continue
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


def _index_source_terms(raw: str) -> dict:
    """Locally cache source terminology and original timestamped excerpts.

    These are literal observations, never an AI-generated correction.
    """
    normalized=norm(raw)
    keys=sorted({norm(term) for name,(_pattern,aliases) in CONCEPTS.items()
                 for term in (name,*aliases) if norm(term)})
    terms={term for term in keys
           if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)",normalized)}
    anchors={}
    for stamp,excerpt in timed_lines(raw):
        for term in terms:
            if term not in anchors and _contains_term(excerpt,term):
                anchors[term]=[stamp,excerpt[:200]]
        if len(anchors)>=len(terms):
            break
    return {"terms":sorted(terms),"anchors":anchors}


def _later_evidence(question, candidate, original, later, lesson_index=None, store=None):
    """Only connect a later spoken follow-up to THAT later lesson's frozen SHA."""
    result = []
    terms = ([candidate, *CONCEPTS.get(candidate, (None, []))[1]]
             if candidate else [])
    terms = [term for term in terms
             if not is_generic_code_term(term) and
             (norm(term) == norm(candidate) or not _contains_term(original, term))]
    for source, indexed in later:
        present = set(indexed.get("terms", []))
        observed = [norm(term) for term in terms if norm(term) in present]
        code = None
        if lesson_index is not None:
            frozen = [item for item in lesson_index.for_lesson(source["lesson"])
                      if item[0].get("frozen")]
            code = match_frozen_question(question, frozen)
        # A later SHA being able to answer a question is not evidence that the
        # topic was discussed in that class. Require a literal later mention
        # of the candidate identifier or the original ASR phrase.
        related = bool(observed)
        if not related and code is not None and store is not None:
            later_text = _source_text(store, source)
            related = bool(later_text and (
                _contains_term(later_text, code["candidate"]) or
                _contains_term(later_text, question)))
        if not related:
            continue
        if observed:
            anchors = indexed.get("anchors", {})
            first = next((anchors[t] for t in observed if t in anchors), None)
            result.append({
                "kind":"aula_posterior","source_id":source["id"],
                "lesson":source["lesson"],"label":source["label"],
                "digest":source["digest"],
                "timestamp":first[0] if first else "",
                "excerpt":first[1] if first else "",
            })
        if code is not None:
            result.append({**code, "lesson":source["lesson"],
                           "source_id":source["id"]})
        if len(result) >= 6:
            break
    return result[:8]


def refresh_uncertainties(store, lesson_index=None) -> dict:
    """Idempotent incremental reconciliation; never consumes API calls."""
    sources = sorted(store.sources("transcript"),
                     key=lambda s: (lesson_order(s["lesson"] or ""), s["video"] or "", s["label"]))
    # Reuse verified source-term indexes after the first pass. A new class
    # only requires reading its own transcript for unresolved term matches.
    vocabulary_revision=hashlib.sha256(json.dumps(
        [(name,aliases) for name,(_pattern,aliases) in CONCEPTS.items()],
        ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:12]
    loaded=[]
    for source in sources:
        index_digest=source["digest"]+":"+vocabulary_revision
        index=store.review_source_index(source["id"],index_digest)
        if index is None:
            raw=_source_text(store,source)
            if raw is None:
                continue
            index=_index_source_terms(raw)
            store.save_review_source_index(source["id"],index_digest,index)
        stored=store.vault/(source["stored_path"] or "")
        if stored.is_symlink() or not stored.is_file():
            continue
        loaded.append((source,index))
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
            later = [(s, index) for s, index in loaded
                     if src["lesson"] and s["lesson"] and
                     lesson_order(s["lesson"]) > lesson_order(src["lesson"])]
            evidence = []
            if lesson_index is not None and src["lesson"]:
                # Never use the global/HEAD index here, even for an
                # unregistered lesson. Refuse non-frozen references.
                frozen = [item for item in lesson_index.for_lesson(src["lesson"])
                          if item[0].get("frozen")]
                matched = match_frozen_question(question, frozen)
                if matched is not None:
                    evidence.append({**matched, "lesson":src["lesson"]})
            if evidence:
                state = "EXPLICADA_PELO_CODIGO"
                candidate = evidence[0]["candidate"]
            else:
                evidence = _later_evidence(
                    question, candidate, question, later, lesson_index, store)
                later_code = next((item for item in evidence
                                   if item.get("kind") == "codigo_congelado"), None)
                if later_code:
                    candidate = later_code["candidate"]
                    state = "EXPLICADA_PELO_CODIGO"
                else:
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
        row["status"] in ("NOVA_EVIDENCIA_PARA_REVISAR", "EXPLICADA_PELO_CODIGO")
        for row in store.uncertainties())}


def _safe(text: object, limit: int = 350) -> str:
    """Display source text as one quoted line, not executable Markdown/HTML."""
    raw = str(text).replace("\n", " ").replace("\r", " ").strip()[:limit]
    return raw.replace("<", "&lt;").replace(">", "&gt;").replace("[[", "［［").replace("]]", "］］")


def code_evidence_lines(item):
    """Render 3 verified lines and immutable link, clearly as a hypothesis."""
    if (item.get("kind") != "codigo_congelado"
            or not re.fullmatch(r"[0-9a-f]{40}", str(item.get("sha", "")))):
        return []
    url = str(item.get("repo", "")).rstrip("/")
    path = str(item.get("path", ""))
    if not url.startswith("https://github.com/") or not path or ".." in path.split("/"):
        return []
    line = int(item.get("line", 0))
    if line < 1:
        return []
    link = url + "/blob/" + item["sha"] + "/" + quote(path, safe="/") + "#L" + str(line)
    result = [
        "- **Provável no código:** " + chr(96) + _safe(item["candidate"], 90) + chr(96)
        + " — [" + _safe(path, 160) + ":" + str(line) + "](" + link + ")"
        + " — versão " + chr(96) + _safe(item.get("version") or item["sha"][:10], 60) + chr(96)
        + " (**pista, não prova do áudio**).",
        "  - **Trecho de 3 linhas do commit congelado:**",
    ]
    for raw in str(item.get("snippet", "")).splitlines()[:3]:
        # Never interpolate source code as Markdown/HTML from untrusted repos.
        result.append("    - " + chr(96) + _safe(raw.replace(chr(96), "'"), 210) + chr(96))
    return result


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
            elif e["kind"] == "codigo_congelado":
                body.extend(code_evidence_lines(e))
            else:
                body.append(f"- Repositório: `{_safe(e['repo'],180)}`, "
                            f"commit `{_safe(e['sha'][:12])}`, "
                            f"arquivo `{_safe(e['path'],180)}:{e['line']}`.")
        body += ["", "## Histórico da revisão", ""]
        for ev in events:
            past = json.loads(ev["evidence_json"])
            summary = ", ".join(
                (e.get("lesson", "") if e.get("kind") == "aula_posterior"
                 else e.get("path", ""))
                for e in past[:5]) or "nenhuma referência adicional"
            body.append(f"- {ev['created_at']} — **{ev['status']}** "
                        f"(fontes: {_safe(summary, 260)}; "
                        f"registro `{ev['evidence_digest'][:12]}`).")
        body += ["", "## Próxima conferência", "",
                 "Confira a transcrição e, se necessário, o vídeo original. "
                 "O TRAMA não altera a fala do professor nem declara a dúvida resolvida por conta própria."]
        notes.append((rel, "\n".join(body) + "\n"))
        output.append(f"- [[{row['id']}|{_safe(row['question'],100)}]] — "
                      f"`{row['status']}`")
    if not rows:
        output.append("*Nenhuma dúvida identificada nas análises cadastradas.*")
    return "\n".join(output) + "\n", notes
