"""Escrita segura no cofre e páginas ligadas por fonte/conceito/projeto."""
from __future__ import annotations

import hashlib
import json
import unicodedata
import os
import re
from difflib import SequenceMatcher
import shutil
import tempfile
from collections import defaultdict, Counter
from pathlib import Path
from urllib.parse import quote

from .content import MODULES, evidence_excerpt, guess_modules, lesson_identity, slug, concept_slug, concept_file_slug, timed_lines, study_windows, opening_lesson_number_mismatch, suspected_technical_transcription, suspected_concept_name
from .store import Store
from .memory_atlas import make_atlas, render_atlas, lesson_order, norm, note_for, literal_technical_mention
from .code_intel import match_lesson_to_repository, potential_transcript_corrections, is_generic_code_term
from .learning_review import refresh_uncertainties, render_uncertainties, code_evidence_lines
from .frozen_code_resolution import match_frozen_question
from .github_lesson_index import LessonRepositoryIndex


def _escape_md(s: object) -> str:
    return str(s).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _frontmatter(**kwargs) -> str:
    out = ["---"]
    for k,v in kwargs.items():
        out.append(f"{k}: '{str(v).replace(chr(39), chr(39)*2)}'")
    return "\n".join(out + ["---", ""])


def _time_id(timestamp: str) -> str:
    """Obsidian block ID for a verified timestamp from the original TXT."""
    return "min-" + re.sub(r"[^0-9]", "-", timestamp.strip()).strip("-")


def _term_in_source(term: str, source: str) -> bool:
    """Literal, punctuation-aware presence; an IA interpretation isn't proof."""
    return bool(literal_technical_mention(term, source))



def _indexed_source_rows(source_rows: list[tuple[str, str]]):
    """Assign a stable, noncolliding anchor to every timed transcript segment.

    Auto-transcriptions can repeat a timestamp. Only such duplicates gain an
    occurrence suffix; unique old links stay compatible with older notes.
    """
    totals = Counter(stamp for stamp, _ in source_rows if stamp != "sem horário")
    encountered = defaultdict(int)
    for stamp, sentence in source_rows:
        if stamp == "sem horário":
            continue
        encountered[stamp] += 1
        anchor = _time_id(stamp)
        if totals[stamp] > 1:
            anchor += f"-{encountered[stamp]}"
        yield stamp, sentence, anchor


def _transcript_seconds(stamp: str) -> int | None:
    """Use only literal timestamp syntax parsed from the original TXT."""
    parts = stamp.split(":")
    if len(parts) not in (2, 3) or not all(x.isdigit() for x in parts):
        return None
    numbers = [int(x) for x in parts]
    if numbers[-1] >= 60 or (len(numbers) == 3 and numbers[-2] >= 60):
        return None
    return numbers[0] * 60 + numbers[1] if len(numbers) == 2 else (
        numbers[0] * 3600 + numbers[1] * 60 + numbers[2])


def _nearby_transcript_context(
    source_rows: list[tuple[str, str]], anchor: str,
    max_seconds: int = 32, max_rows: int = 7,
    indexed: list[tuple[str, str, str]] | None = None,
    position: int | None = None
) -> list[tuple[str, str]]:
    """Adjacent original transcript fragments, without joining distant topics.

    A timestamped fragment can be only a few words. Nearby rows help review
    what was said, but are never certified as a model explanation. Preindexed
    rows avoid rescanning a long lesson for every term occurrence.
    """
    if indexed is None:
        indexed = list(_indexed_source_rows(source_rows))
    if position is None:
        position = next((i for i, (_, _, ref) in enumerate(indexed)
                         if ref == anchor), None)
    if position is None:
        return []
    original_time = _transcript_seconds(indexed[position][0])
    if original_time is None:
        return [(indexed[position][0], indexed[position][1])]
    selected = [indexed[position]]
    for item in indexed[position + 1:]:
        if len(selected) >= max_rows:
            break
        seconds = _transcript_seconds(item[0])
        if seconds is None or seconds < original_time or seconds - original_time > max_seconds:
            break
        selected.append(item)
    return [(stamp, sentence) for stamp, sentence, _ in selected]


_EXPLANATION_CLUES = re.compile(
    r"\b(?:significa|significam|quer dizer|se chama|é um|é uma|serve para|"
    r"permite|funciona como|tem suporte|suporte de longo|duração|"
    r"anos de suporte|development kit|long.term support|"
    r"o que(?: que)? é|que significa)\b",
    re.I,
)


def _literal_timed_evidence(label: str, source_rows: list[tuple[str, str]],
                            preferred: str = "", limit: int = 2) -> list[tuple[str, str, str, str]]:
    """Prefer reviewable explanatory context over the first literal mentions.

    Heuristics only prioritize *where to read*. They never certify that the
    model's explanation was actually taught, demonstrated or learned.
    """
    matches = []
    indexed = list(_indexed_source_rows(source_rows))
    for position, (stamp, sentence, anchor) in enumerate(indexed):
        if not sentence.strip():
            continue
        term = literal_technical_mention(label, sentence)
        if term:
            context = _nearby_transcript_context(
                source_rows, anchor, max_rows=3, indexed=indexed,
                position=position)
            # A clue near the literal mention is more useful for studying
            # than a passing mention. Never infer an explanation from this.
            explanation_score = (
                2 if _EXPLANATION_CLUES.search(sentence) else
                1 if any(_EXPLANATION_CLUES.search(fragment)
                         for _, fragment in context[1:]) else 0
            )
            matches.append((stamp, sentence, term, anchor, explanation_score))
    # Do not dilute an explanatory passage with an unrelated earlier mention.
    # Explicit verified times are retained even if heuristic wording is weak:
    # the same concept may be explained differently in separate AI chunks.
    best = max((row[4] for row in matches), default=0)
    if best >= 2:
        matches = [row for row in matches
                   if row[4] >= 2 or (preferred and row[0] == preferred)]
    elif best == 1:
        matches = [row for row in matches
                   if row[4] >= 1 or (preferred and row[0] == preferred)]
    matches.sort(key=lambda row: (
        -int(bool(preferred and row[0] == preferred)), -row[4]
    ))
    return [(stamp, sentence, term, anchor)
            for stamp, sentence, term, anchor, _ in matches[:max(0, limit)]]


def _group_timed_evidence(
    source_rows: list[tuple[str, str]],
    matches: list[tuple[str, str, str, str]],
    preferred: str = ""
) -> list[tuple[tuple[str, str, str, str], list[tuple[str, str]]]]:
    """Present nearby verified mentions as one chronological study passage.

    Ranking chooses useful mentions; publication restores transcript order and
    merges overlapping source windows. Nothing is invented or removed from TXT.
    Anchor identity, not timestamp alone, handles duplicated ASR time labels.
    """
    indexed = list(_indexed_source_rows(source_rows))
    positions = {anchor: i for i, (_, _, anchor) in enumerate(indexed)}
    groups = []
    for match in sorted(matches, key=lambda row: positions.get(row[3], len(indexed))):
        start = positions.get(match[3])
        if start is None:
            continue
        context = _nearby_transcript_context(
            source_rows, match[3], indexed=indexed, position=start)
        if not context:
            continue
        end = start + len(context) - 1
        if groups and start <= groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], end)
        else:
            groups.append([start, end, match])
    return [
        (
            next((item for item in matches
                  if item[0] == preferred and start <= positions[item[3]] <= end),
                 first),
            [(stamp, sentence) for stamp, sentence, _ in indexed[start:end + 1]],
        )
        for start, end, first in groups
    ]


def _source_quote(value: object, limit: int = 260, term: str = "") -> str:
    """Inert Markdown excerpt centered around a literally found term.

    Omitted material is marked with ellipses, never silently substituted. The
    unmodified entire TXT remains available in the Obsidian attachments.
    """
    raw = str(value).replace("\r", " ").replace("\n", " ")
    start, end = 0, min(limit, len(raw))
    if term and len(raw) > limit:
        found = re.search(re.escape(term), raw, flags=re.I)
        if found:
            start = max(0, min(found.start() - limit // 3, len(raw) - limit))
            end = min(len(raw), start + limit)
    excerpt = ("…" if start else "") + raw[start:end] + ("…" if end < len(raw) else "")
    return (_escape_md(excerpt).replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;")
            .replace("[[", "［［").replace("]]", "］］"))


def _project_ref(repo) -> str:
    """Stable Obsidian note target for an immutable SHA/folder snapshot."""
    name = f"{slug(repo['name'])}-{repo['sha'][:7]}"
    if repo.get("frozen"):
        identity = (str(repo["url"]) + "\n" + str(repo["sha"]) + "\n"
                    + str(repo.get("folder", ""))).encode("utf-8")
        return name + "-f" + hashlib.sha256(identity).hexdigest()[:8]
    return name


def _code_ref(repo, path: str, line: int) -> str:
    """Link to the immutable GitHub revision; local repos retain path:line."""
    location = f"{_escape_md(path)}:{line}"
    url = str(repo["url"]).removesuffix(".git").rstrip("/")
    sha = str(repo["sha"])
    if re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url) and re.fullmatch(r"[0-9a-f]{40}", sha, re.I):
        target = f"{url}/blob/{sha}/{quote(path, safe='/')}#L{line}"
        return f"[`{location}`]({target})"
    return f"`{location}`"


class Publisher:
    def __init__(self, store: Store):
        self.db, self.vault = store, store.vault
        self._concept_targets = {}
        self.lesson_repo_index = LessonRepositoryIndex(store)
        self._lesson_repo_memo = {}
        self._frozen_question_memo = {}
        self._concept_aliases = {}
        for folder in ["00-Inicio", "01-Meu-Conhecimento", "02-Minhas-Aulas", "03-Meus-Projetos",
                       "05-Anotacoes-Pessoais", "90-Sistema", "99-Anexos/Videos", "99-Anexos/Transcricoes-Originais",
                       "99-Anexos/Materiais-Originais", "99-Anexos/Contexto-Classroom"]:
            (self.vault / folder).mkdir(parents=True, exist_ok=True)

    def _lesson_repos(self, lesson: str):
        """Resolve each lesson only once during this publication."""
        if lesson not in self._lesson_repo_memo:
            self._lesson_repo_memo[lesson] = self.lesson_repo_index.for_lesson(lesson)
        return self._lesson_repo_memo[lesson]

    def _keep_previous_code(self, lines, rel, lesson, start_heading, end_heading):
        """If a frozen index is unreachable, preserve prior SHA-matched code text.

        Never recover stale code after explicit unfreeze or a changed SHA.
        Only replace the generated section; other lesson content still updates.
        """
        if lesson not in self.lesson_repo_index.failed_lessons:
            return lines
        warning = self.lesson_repo_index.warning(lesson)
        start = next((i for i, line in enumerate(lines) if line == start_heading), None)
        if start is None:
            return lines
        previous = []
        path = self.vault / rel
        try:
            if (path.is_file() and not path.is_symlink() and
                    path.resolve().is_relative_to(self.vault) and
                    path.stat().st_size <= 2_000_000):
                old = path.read_text(encoding="utf-8")
                left = old.find(start_heading + "\n")
                right = old.find("\n" + end_heading, left + len(start_heading)) if left >= 0 else -1
                if left >= 0 and right > left:
                    previous = old[left + len(start_heading) + 1:right].splitlines()
                    previous = [line for line in previous
                                if not line.startswith("> **TRAMA (offline):**")]
                    # A previous note might belong to an old, explicitly
                    # unfrozen SHA. Do not silently reuse mismatched evidence.
                    commits = set(re.findall(r"/blob/([0-9a-f]{40})/", "\n".join(previous), re.I))
                    _, current, _ = self.lesson_repo_index._status.get(lesson, (0, [], []))
                    pinned = {row["commit_sha"] for row in current}
                    if not commits or not commits.issubset(pinned):
                        previous = []
        except (OSError, UnicodeError, ValueError):
            previous = []
        # Do not claim "no code" on a transient 403/429/network outage.
        restored = previous if previous else ["", "*Relações não atualizadas: índice congelado indisponível.*"]
        return lines[:start + 1] + restored + [
            "", "> **TRAMA (offline):** " + warning,
        ]

    def _code_guess(self, lesson: str, question: str):
        """Local, SHA-only evidence, never HEAD or another lesson's version."""
        key = (lesson, question.casefold().strip())
        if key not in self._frozen_question_memo:
            selected = [row for row in self._lesson_repos(lesson)
                        if row[0].get("frozen")]
            self._frozen_question_memo[key] = match_frozen_question(question, selected)
        return self._frozen_question_memo[key]

    @staticmethod
    def _marked_distortion(concept: dict, raw: str) -> bool:
        """Concepts are not doubts. Only explicitly flagged ASR names may be
        compared to code, and even those are ignored when the original name
        is already present literally in the TXT or is ordinary Portuguese.
        """
        if not isinstance(concept, dict):
            return False
        name = str(concept.get("nome", "")).strip()
        if not name:
            return False
        # A known whole-label ASR hint can be present literally in the TXT:
        # the literal is the transcription error, not necessarily correct.
        known_asr = suspected_concept_name(name)
        flagged = bool(str(concept.get("suspeita_transcricao") or "").strip())
        if not flagged and not known_asr:
            return False
        # Ordinary Portuguese nouns are not ASR errors simply because an
        # English symbol happens to be orthographically similar.
        if re.search(r"\b\w+(?:ção|ções|mento|mentos|dade|dades)\b",
                     name.casefold(), re.UNICODE):
            return False
        if literal_technical_mention(name, raw) and not known_asr:
            return False
        return True

    def _corrected_concept(self, src, name: str, concept: dict | None = None, raw: str = ""):
        """Use a *marked* and nonliteral ASR concept label only as a hint."""
        if not self._marked_distortion(concept or {}, raw):
            return name
        match = self._code_guess(src["lesson"] or "", name)
        if not match or match["candidate"].casefold() == name.casefold():
            return name
        canonical = match["candidate"]
        known_asr = suspected_concept_name(name)
        if known_asr and canonical.casefold() != known_asr.casefold():
            return name  # reject unrelated code names even with ASR warning
        if concept_slug(canonical) in self._concept_targets:
            self._concept_aliases[(src["id"], name.casefold())] = canonical
            return canonical
        return name

    def _concept_target(self, name: str, source_id: str = "") -> str:
        """Keep the spoken label in text; optionally link its verified alias."""
        corrected = self._concept_aliases.get((source_id, name.casefold()), name)
        return self._concept_targets.get(concept_slug(corrected), concept_file_slug(corrected))

    @staticmethod
    def _asr_concept_warning(concept: dict) -> str:
        warning = str(concept.get("suspeita_transcricao") or "").strip()
        suggestion = suspected_concept_name(concept.get("nome", ""))
        if not warning and suggestion:
            warning = ("Nome possivelmente distorcido pela transcrição; sugestão: "
                       + suggestion + ". Conferir no áudio; não corrigido automaticamente.")
        return warning

    def _prepare_concept_targets(self):
        """Retain legacy files on existing vaults; clean vaults use readable slugs.

        The normalized comparison key (e.g. validacao-dado) groups variants.
        Legacy paths and manually edited pages are not renamed or duplicated.
        """
        candidates = {}
        for src in self.db.sources("transcript"):
            analysis = self.db.analysis(src["id"], src["digest"]) or {}
            if analysis.get("tipo_aula") in ("apresentacao","organizacional","atividade"):
                continue  # nontechnical concept names never get a page
            for concept in analysis.get("conceitos", []):
                if not isinstance(concept, dict):
                    continue
                name = str(concept.get("nome", "")).strip()
                if name:
                    names = candidates.setdefault(concept_slug(name), [])
                    if name not in names:
                        names.append(name)
        folder = self.vault / "01-Meu-Conhecimento" / "Conceitos"
        self._concept_targets = {}
        for key, names in candidates.items():
            options = list(dict.fromkeys(
                [concept_file_slug(name) for name in names] + [key]))
            existing = next((option for option in options
                             if (folder / (option + ".md")).is_file()
                             and not (folder / (option + ".md")).is_symlink()), "")
            self._concept_targets[key] = existing or options[0]

    def write(self, rel: str, content: str) -> str:
        """Só sobrescreve algo que ainda corresponde ao hash da última gravação nossa."""
        rel = rel.replace("\\", "/")
        path = self.vault / rel
        if not path.resolve().is_relative_to(self.vault):
            raise ValueError("Saída fora do cofre")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            previous = self.db.last_write_hash(rel)
            current = hashlib.sha256(path.read_bytes()).hexdigest()
            if current == hashlib.sha256(content.encode("utf-8")).hexdigest():
                return "unchanged"
            if current != previous:
                # Avoid duplicate proposals when earlier suggestions were
                # edited; keep every human-edited proposal intact.
                proposals = sorted(path.parent.glob(path.stem + ".PROPOSTA*.md"))
                if any(p.is_file() and p.read_text(encoding="utf-8") == content for p in proposals):
                    return "manual-protected"
                conflict = path.with_name(path.stem + ".PROPOSTA.md")
                n = 1
                while conflict.exists():
                    conflict = path.with_name(f"{path.stem}.PROPOSTA-{n}.md")
                    n += 1
                conflict.write_text(content, encoding="utf-8")
                return "manual-protected"
        data = content.encode("utf-8")
        fd, tmp = tempfile.mkstemp(prefix=".nota-", dir=str(path.parent))
        try:
            with os.fdopen(fd,"wb") as out:
                out.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        self.db.register_write(rel, hashlib.sha256(data).hexdigest())
        return "written"

    def _published_anchor_target(self, note: str, anchor: str) -> tuple[str, bool]:
        """Link only to an actual anchored note, including protected proposals.

        A manually edited note may lack generated anchors. In that case the
        safe publisher writes a .PROPOSTA.md rather than replacing it. Point
        to that proposed Markdown (clearly labeled), never a broken link.
        """
        path = self.vault / note
        marker = re.compile(r"\^" + re.escape(anchor) + r"(?=\s|$)")
        def has_anchor(candidate: Path) -> bool:
            if (candidate.is_symlink() or not candidate.is_file() or
                    candidate.stat().st_size > 2 * 1024 * 1024):
                return False
            return bool(marker.search(candidate.read_text(
                encoding="utf-8", errors="replace")))

        if has_anchor(path):
            current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if current_hash == self.db.last_write_hash(note):
                return Path(note).with_suffix("").as_posix(), False
        for proposal in sorted(path.parent.glob(path.stem + ".PROPOSTA*.md")):
            if has_anchor(proposal):
                return proposal.relative_to(self.vault).with_suffix("").as_posix(), True
        return "", False

    def attachment(self, original: Path, kind: str) -> str:
        if kind == "video":
            raise ValueError("Vídeos não são copiados. Registre o link no contexto do Classroom.")
        from .content import file_hash
        digest = file_hash(original)
        subfolder = {"video": "Videos", "transcript": "Transcricoes-Originais",
                     "material": "Materiais-Originais"}.get(kind)
        if not subfolder:
            raise ValueError("Tipo de anexo inválido")
        # Conteúdo idêntico é armazenado uma vez, mesmo quando pertence
        # a aulas ou gravações distintas. O catálogo preserva cada fonte.
        target_dir=self.vault/'99-Anexos'/subfolder
        for candidate in target_dir.glob(digest[:14]+'-*'+original.suffix.lower()):
            if candidate.is_file() and file_hash(candidate)==digest:
                return candidate.relative_to(self.vault).as_posix()
        rel = f"99-Anexos/{subfolder}/{digest[:14]}-{slug(original.stem,45)}{original.suffix.lower()}"
        output = self.vault / rel
        if output.exists():
            # Uma cópia incompleta nunca pode ser tratada como importação concluída.
            if output.stat().st_size != original.stat().st_size or file_hash(output) != digest:
                raise ValueError("Cópia parcial/inconsistente detectada em anexos. Revise o arquivo antes de continuar.")
            return rel
        # Copia para arquivo temporário primeiro: se o programa fechar ou faltar
        # espaço, o destino final não aparece como se estivesse completo.
        fd, tmp = tempfile.mkstemp(prefix=".anexo-parcial-",dir=str(output.parent))
        try:
            os.close(fd)
            shutil.copy2(original,tmp)
            # The input might change while being copied. Never publish a copy
            # that differs from the digest stored in the source catalog.
            if file_hash(Path(tmp)) != digest:
                raise ValueError("O arquivo de origem mudou durante a cópia. Importe novamente.")
            os.replace(tmp,output)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return rel

    def _lesson_extras(self, lesson: str):
        """Sources for a lesson may exist without any programming content."""
        return [src for src in self.db.sources() if src["lesson"] == lesson and src["kind"] != "transcript"]

    def _context_rows(self, lesson: str):
        out = []
        for source in self._lesson_extras(lesson):
            if source["kind"] != "classroom":
                continue
            try:
                obj = json.loads((self.vault / source["stored_path"]).read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    out.append((source, obj))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
        return out

    def _append_context(self, body: list[str], lesson: str) -> None:
        body.extend(["", "## Contexto e materiais do Classroom", "",
                     "> Contexto de múltiplas fontes. Extrações automáticas são sugestões; confira o arquivo original."])
        rows = self._context_rows(lesson)
        if not rows:
            body.append("*Descrição do Classroom ainda não cadastrada.*")
        for src, item in rows:
            body.extend(["", f"### {_escape_md(item.get('titulo') or lesson)}", "",
                         f"- Origem: {_escape_md(item.get('origem') or 'registro de contexto')}",
                         f"- Data informada: {_escape_md(item.get('data') or 'não informada')}",
                         f"- Fonte preservada: `{_escape_md(src['stored_path'])}`"])
            if item.get('arquivo_fonte'):
                body.append(f"- Arquivo usado na extração: `{_escape_md(item['arquivo_fonte'])}`")
            if item.get('incertezas'):
                body.append(f"- **Revisar:** {_escape_md(item['incertezas'])}")
            for field, heading in (("descricao", "Descrição e agenda"), ("pessoas", "Pessoas e funções informadas"),
                                   ("atividades", "Atividades e decisões informadas")):
                value = item.get(field, "")
                if isinstance(value, str) and value.strip():
                    body.extend(["", f"**{heading}:**"])
                    body.extend(f"> {_escape_md(line)}" for line in value.splitlines() if line.strip())
            if item.get("gravacoes"):
                body.extend(["", "**Gravações mencionadas no post (sem URL):**"])
                body.extend(f"- {_escape_md(str(title))}"
                            for title in item["gravacoes"][:30] if isinstance(title,str))
            recordings = item.get("videos", [])
            if recordings:
                body.extend(["", "**Gravações (somente links, sem cópia do vídeo):**"])
                for entry in recordings[:30]:
                    if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                        title = _escape_md(entry.get("titulo", "Gravação"))
                        url = entry["url"]
                        if url.startswith(("https://", "http://")):
                            body.append(f"- **{title}**: <{url}>")
            for link in item.get("links", [])[:30]:
                if isinstance(link, str) and link.startswith(("https://", "http://")):
                    body.append(f"- Material/link do Classroom: <{link}>")
        body.extend(["", "## Arquivos e materiais preservados", ""])
        extras = [src for src in self._lesson_extras(lesson) if src["kind"] in ("video", "material")]
        if not extras:
            body.append("*Nenhum arquivo local anexado. Gravações podem estar registradas apenas por link acima.*")
        for src in extras:
            name = Path(src["stored_path"]).name
            body.append(f"- **{_escape_md(src['kind'])}:** [[{_escape_md(name)}|{_escape_md(src['label'])}]]")
        body.extend(["", "> Prints e PDFs são preservados como fontes. Somente arquivos com contexto automático "
                     "identificado acima foram analisados visualmente; hipóteses não são fatos confirmados."])

    def _other_lesson_note(self, lesson: str, sources: list) -> str:
        """A lesson with only video, screenshots or Classroom is still a lesson."""
        rel = f"02-Minhas-Aulas/{lesson}/00-contexto-{slug(lesson)}.md"
        title = lesson
        for _, record in self._context_rows(lesson):
            if record.get("titulo"):
                title = f"{lesson} — {record['titulo']}"
                break
        body = [_frontmatter(tipo="aula", aula=lesson, estado="sem_transcricao",
                             fonte="classroom_ou_materiais"), f"# {_escape_md(title)}", "",
                "## Situação da aula", "",
                "Aula cadastrada mesmo sem transcrição. Não presumir que houve conteúdo técnico.", "",
                "## Transcrição", "", "*Ainda não fornecida. Não gerar resumo de vídeo só pelo nome do arquivo.*"]
        self._append_context(body, lesson)
        self.write(rel, "\n".join(body) + "\n")
        return rel

    def lesson_overview(self, lesson: str, recordings: list[tuple]) -> str:
        """Human-readable landing page; source transcripts are never rewritten here.

        A lesson can span many V01/V02 recordings. All links are references
        to real files already published in the same vault.
        """
        contexts = [item for _, item in self._context_rows(lesson)]
        title = next((str(item.get('titulo', '')).strip() for item in contexts
                      if item.get('titulo')), '')
        heading = f"{lesson} — {title}" if title else lesson
        safe_name = _escape_md(heading)
        rel = f"02-Minhas-Aulas/{lesson}/00-Visao-geral.md"
        rows = [_frontmatter(tipo='visao_geral', aula=lesson, estado='fontes_organizadas'),
                f"# {safe_name}", '',
                '> **Como ler esta página:** ela reúne o que consta nos materiais. '
                'Plano de aula não é prova de execução; citação de conteúdo não comprova domínio pessoal.',
                '', '## Em poucas palavras', '']
        summaries = []
        for src, note in recordings:
            analysis = self.db.analysis(src['id'], src['digest'])
            if analysis and analysis.get('resumo'):
                summaries.append((src, note, analysis))
        if summaries:
            rows.append(f"Esta aula reúne **{len(recordings)} {'gravação' if len(recordings)==1 else 'gravações'} com transcrição**. "
                        'Consulte cada parte abaixo para a explicação detalhada.')
            for src, note, analysis in summaries:
                label = _escape_md(src['label'].removesuffix('.txt').removesuffix('.md'))
                text = str(analysis['resumo']).replace('**Parte 1:**', '').strip()
                # A 1250-character cut used to hide the end of otherwise valid
                # summaries, including examples and open questions. Keep a
                # readable overview excerpt and explicitly link the full note.
                preview=text if len(text)<=4500 else text[:4500].rsplit(' ',1)[0]
                if len(preview)<len(text):
                    preview += "\n\n*Resumo abreviado nesta visão geral; a explicação completa está na nota vinculada acima.*"
                rows.extend(['', f"### [[{Path(note).stem}|{label}]]", '',
                         "> **Síntese assistida por IA; conferir no TXT original.**", '', preview])
            if analysis.get("qualidade_pendente"):
                rows.append(
                    "> **Fidelidade a conferir:** há alertas de qualidade na nota "
                    "desta gravação. Abra a nota vinculada antes de tratar a "
                    "síntese como conteúdo confirmado.")
        else:
            rows.append('**Pendente:** a IA ainda não gerou o resumo desta aula. Os materiais abaixo permanecem disponíveis.')
        rows += ['', '## Gravações e transcrições', '']
        if recordings:
            for src, note in sorted(recordings, key=lambda p:(p[0]['video'] or 'zz',p[0]['label'])):
                label = _escape_md(Path(src['label']).stem)
                status = 'resumida com IA' if self.db.analysis(src['id'], src['digest']) else 'aguardando análise'
                rows.append(f"- [[{Path(note).stem}|{label}]] — {status}; "
                            f"transcrição original: `{_escape_md(src['label'])}` (consulte a aba Transcrição)")
                source_text=(self.vault/src["stored_path"]).read_text(
                    encoding="utf-8-sig", errors="replace")
                mismatch=opening_lesson_number_mismatch(source_text, lesson)
                if mismatch:
                    stamp, spoken_number = mismatch
                    rows.append(
                        f"  - **Numeração a conferir:** o arquivo é "
                        f"**{_escape_md(lesson)}**, mas no TXT em "
                        f"**{_escape_md(stamp)}** aparece **aula {spoken_number}**. "
                        "A identificação original foi preservada.")
        else:
            rows.append('*Nenhuma gravação transcrita importada ainda.*')
        links=[]
        for item in contexts:
            for record in item.get('videos', []) if isinstance(item.get('videos'), list) else []:
                if isinstance(record,dict) and str(record.get('url','')).startswith(('https://','http://')):
                    pair=(str(record.get('titulo') or 'Gravação')[:200], record['url'])
                    if pair not in links:links.append(pair)
        if links:
            rows += ['', '**Assistir aos vídeos originais (sem download):**']
            for name,url in links[:45]:
                rows.append(f"- {_escape_md(name)}: <{url}>")
        rows += ['', '## Classroom — contexto e atividades', '']
        if contexts:
            for item in contexts:
                if item.get('data'):rows.append(f"- Data informada: {_escape_md(item['data'])}")
                if item.get('descricao'):
                    rows.extend(['', '**Descrição/agenda publicada:**', ''])
                    for line in str(item['descricao']).splitlines()[:100]:
                        if line.strip():rows.append(f"> {_escape_md(line)}")
                if item.get('gravacoes'):
                    rows.extend(['', '**Gravações citadas no Classroom (sem URL confirmada):**', ''])
                    rows.extend(f"- {_escape_md(str(name))}" for name in item['gravacoes'][:30])
                if item.get('atividades'):
                    rows.extend(['', '**Atividades registradas na publicação (não necessariamente realizadas):**',''])
                    for line in str(item['atividades']).splitlines()[:40]:
                        if line.strip():rows.append(f"- {_escape_md(line)}")
                for link in item.get('links', []) if isinstance(item.get('links'),list) else []:
                    if isinstance(link,str) and link.startswith(('https://','http://')):
                        rows.append(f"- Material publicado: <{link}>")
        else:
            rows.append('*Nenhuma publicação do Classroom relacionada a esta aula foi cadastrada.*')
        rows += ['', '## Pessoas citadas', '']
        person_links=[]; concept_links=[]
        for item in contexts:
            for line in str(item.get('pessoas','')).splitlines():
                name = re.split(r"\s+[—–-]\s+|\s*:\s*",line.strip(),maxsplit=1)[0].strip()
                if 3<=len(name)<=80:
                    link=f"[[{slug(name)}|{_escape_md(name)}]]"
                    if link not in person_links:person_links.append(link)
        for src, note in recordings:
            a=self.db.analysis(src['id'],src['digest']) or {}
            raw=(self.vault/src['stored_path']).read_text(encoding='utf-8-sig',errors='replace')
            normalized=self._person_key(raw)
            for person in a.get('pessoas',[]):
                if not isinstance(person,dict):
                    continue
                name=str(person.get('nome','')).strip()
                if len(name)<3 or self._person_key(name) not in normalized:
                    continue
                name,warning=self._reviewable_person_name(name,lesson)
                if warning:
                    continue  # transcription alias gets review, not a person page
                link=f"[[{slug(name)}|{_escape_md(name)}]]"
                if link not in person_links:person_links.append(link)
            presenter=self._grounded_presenter(src,raw)
            if presenter:
                link=f"[[{slug(presenter)}|{_escape_md(presenter)}]]"
                if link not in person_links:person_links.append(link)
            if a.get("tipo_aula") not in ("apresentacao","organizacional","atividade"):
                for c in a.get('conceitos',[]):
                    if not isinstance(c,dict):
                        continue
                    name=str(c.get('nome','')).strip()
                    if not name:continue
                    link=f"[[{self._concept_target(name)}|{_escape_md(name)}]]"
                    if link not in concept_links:concept_links.append(link)
        rows.extend([f'- {link} — confira o contexto na fonte' for link in person_links]
                    if person_links else ['*Ainda sem pessoas associadas com evidência.*'])
        variant_warnings=[]
        for src, _note in recordings:
            analysis=self.db.analysis(src['id'],src['digest']) or {}
            for person in analysis.get('pessoas',[]):
                _canonical,possible=self._reviewable_person_name(person.get('nome',''),lesson)
                if possible and possible not in variant_warnings:variant_warnings.append(possible)
        if variant_warnings:
            rows.extend(['', '**Grafias de nomes a conferir:**', ''])
            rows.extend('- '+_escape_md(w) for w in variant_warnings)
        rows.extend(['', '## Conhecimentos técnicos citados', '',
                     '> Classificação assistida por IA: confira a explicação na fonte.', ''] +
                    ([f'- {link}' for link in concept_links] if concept_links else
                     ['*Ainda não há conceitos técnicos classificados com evidência suficiente pela análise.*']))
        # Legacy cached notes can still contain abbreviated technical labels
        # that are present in the TXT but were rejected by strict whole-label
        # matching. Surface them in the overview as observations, not as
        # generated explanatory concept pages.
        observed_terms=[]
        for src,_note in recordings:
            analysis=self.db.analysis(src['id'],src['digest']) or {}
            if not analysis.get('conceitos_a_conferir'):
                continue
            original=self.vault/src['stored_path']
            if not original.is_file() or original.is_symlink():
                continue
            raw=original.read_text(encoding='utf-8-sig',errors='replace')
            for candidate in analysis.get('conceitos_a_conferir',[])[:12]:
                if not isinstance(candidate,dict):
                    continue
                label=str(candidate.get('nome','')).strip()
                if is_generic_code_term(label):
                    continue
                match=literal_technical_mention(label,raw)
                pair=(label,match)
                if match and pair not in observed_terms:
                    observed_terms.append(pair)
        if observed_terms:
            rows.extend(['', '**Termos técnicos presentes no TXT, ainda sem explicação validada:**', '',
                         '> Este levantamento é local e não consome IA. '
                         'Uma menção não comprova que o conceito foi ensinado por completo.', ''])
            rows.extend('- `'+_escape_md(label)+'` (menção: `'+_escape_md(match)+'`)'
                        for label,match in observed_terms[:24])
        rows += ['', '## Evolução e relações com aulas anteriores', '',
                 '> As conexões abaixo vêm de conceitos identificados pela IA em fontes cadastradas. '
                 'São **candidatas**, não comprovação de aprendizado, domínio ou autoria.',
                 '']
        atlas = getattr(self, '_atlas', {'concepts':[],'repos':[]})
        evolution=[]
        for concept in atlas.get('concepts',[]):
            mentions=concept.get('mentions',[])
            current=[m for m in mentions if m['lesson']==lesson]
            earlier=[m for m in mentions if lesson_order(m['lesson']) < lesson_order(lesson)]
            if not current:continue
            if earlier:
                prior=earlier[0]
                first=f"[[{Path(prior['note']).stem}|{prior['lesson']}]]"
                recent=earlier[-1]
                newest=f"[[{Path(recent['note']).stem}|{recent['lesson']}]]"
                evolution.append(f"- **[[{concept['slug']}|{_escape_md(concept['name'])}]]:** "
                    f"primeira menção cadastrada em {first}; retomado nesta aula "
                    f"(referência anterior mais recente: {newest}). "
                    f"Evidência atual: {current[0]['timestamp'] or 'horário não confirmado'} — "
                    f"{current[0]['confidence']}.")
            else:
                evolution.append(f"- **[[{concept['slug']}|{_escape_md(concept['name'])}]]:** "
                    'primeira menção entre as aulas já analisadas; ' 
                    f"horário: {current[0]['timestamp'] or 'não confirmado'}. Não presumir domínio.")
        if evolution:
            rows.extend(evolution[:35])
            rows.extend(['', '- [[Mapa-da-Evolucao|Abrir mapa completo da evolução]]'])
        else:
            rows.append('*Nenhum conceito com relação temporal validável nesta aula. '
                        'Isso é normal em apresentações ou encontros sem conteúdo técnico.*')
        rows += ['', '## Projetos relacionados', '']
        found_code=False
        for repo, payload in self._lesson_repos(lesson):
            try:
                matches=[]
                for src, _note in recordings:
                    raw=(self.vault/src['stored_path']).read_text(encoding='utf-8-sig',errors='replace')
                    a=self.db.analysis(src['id'],src['digest'])
                    matches.extend(match_lesson_to_repository(raw,a,payload,cap=2))
                if matches:
                    found_code=True
                    ref=f"{_project_ref(repo)}"
                    rows.append(f"- [[{ref}|{_escape_md(repo['name'])}]] — código relacionado por conceito; "
                                f"ex.: {_code_ref(repo, matches[0]['path'], matches[0]['line'])}. "
                                '**Possível relação; não comprova autoria nem momento da implementação.**')
            except (ValueError, KeyError, TypeError):
                continue
        warning = self.lesson_repo_index.warning(lesson)
        if warning:
            rows.append("> " + warning)
        if not found_code:
            rows.append("*Associação temporariamente pendente; não significa ausência de código.*"
                        if "pendente por limite" in warning else
                        "*Ainda não há código com relação verificável para esta aula.*")
        rows = self._keep_previous_code(rows, rel, lesson,
                                        "## Projetos relacionados", "## Fontes e materiais")
        rows += ['', '## Fontes e materiais', '']
        for src in self._lesson_extras(lesson):
            if src['kind']=='classroom':
                rows.append(f"- Contexto registrado: `{_escape_md(src['stored_path'])}`")
            elif src['kind']=='material':
                rows.append(f"- Material preservado: `{_escape_md(src['label'])}` (arquivo no cofre: `{_escape_md(src['stored_path'])}`)")
        if not recordings and not contexts:
            rows.append('*Ainda não há fontes suficientes.*')
        rows += ['', '## O que ainda precisa ser conferido', '',
                 '- Confira nomes e termos suspeitos na gravação original; IA não é prova de correção da transcrição.',
                 '- A presença de um conceito numa transcrição não significa que você o praticou ou domina.',
                 '- Relações com projetos só são confirmadas quando há referência real a código, arquivo e linha.']
        self.write(rel, '\n'.join(rows).strip()+'\n')
        return rel

    @staticmethod
    def _person_key(value: str) -> str:
        return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold().strip()

    @staticmethod
    def _title_person(value: str) -> str:
        """An explicit presenter-like title is a clue, not proof of identity."""
        matched = re.search(
            r"\bApresenta(?:ção|cao|ção\s+de)\s+"
            r"([A-ZÀ-Ý][A-Za-zÀ-ÿ'-]{2,35}"
            r"(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'-]{2,35}){1,3})\b",
            str(value))
        return matched.group(1).strip() if matched else ""

    @staticmethod
    def _possible_spelling_variant(name: str, authoritative: str) -> bool:
        """Flag plausible ASR aliases, never merge two human identities.

        Includes surname-only cues, e.g. Rash/Rech; no assertion that two
        individuals are the same person or that the audio confirms an alias.
        """
        def terms(value):
            plain = unicodedata.normalize("NFKD", value).encode(
                "ascii", "ignore").decode().casefold()
            return re.findall(r"[a-z]{3,35}", plain)
        def phoneme(value):
            for before,after in (("sch","x"),("sh","x"),("ch","x"),
                                 ("ph","f"),("ck","k"),("ss","s"),
                                 ("z","s")):
                value=value.replace(before,after)
            return value
        a,b=terms(name),terms(authoritative)
        if not a or not b or a==b:
            return False
        # A surname may be said alone. Require a matching initial AND an
        # unusually similar consonant signature before calling it ambiguous.
        for spoken in a:
            for known in b:
                if spoken==known or spoken[0]!=known[0]:
                    continue
                x,y=phoneme(spoken),phoneme(known)
                skeleton_x=re.sub(r"[aeiou]", "", x)
                skeleton_y=re.sub(r"[aeiou]", "", y)
                if (max(len(spoken),len(known))<=4 and
                        len(skeleton_x)>=2 and skeleton_x==skeleton_y and
                        SequenceMatcher(None,x,y).ratio()>=0.60):
                    return True
                if (min(len(spoken),len(known))>=4 and
                        SequenceMatcher(None,x,y).ratio()>=0.81):
                    return True
        return False

    def _classroom_person_names(self, lesson: str) -> list[str]:
        names=[]
        def add(name):
            name=str(name).strip()
            if (3<=len(name)<=80 and name not in names and
                    not re.search(r"[<>\\]",name)):
                names.append(name)
        for _, item in self._context_rows(lesson):
            add(item.get("autor",""))
            add(self._title_person(item.get("titulo","")))
            for line in str(item.get('pessoas','')).splitlines()[:25]:
                add(re.split(r"\s+[—–-]\s+|\s*:\s*", line.strip().lstrip('-• '),
                             maxsplit=1)[0])
        for src in self.db.sources("transcript"):
            if src["lesson"]==lesson:
                add(self._title_person(Path(src["label"]).stem))
        # Read only the heading of existing local person notes as secondary
        # clues; never turn an arbitrary path or external name into identity.
        people_dir=self.vault/"01-Meu-Conhecimento"/"Pessoas"
        if people_dir.is_dir():
            for path in sorted(people_dir.glob("*.md"))[:200]:
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    for line in path.read_text(encoding="utf-8").splitlines()[:16]:
                        if line.startswith("# "):
                            add(line[2:])
                            break
                except (OSError,UnicodeError):
                    continue
        return names

    @staticmethod
    def _nonperson_name(value: str) -> bool:
        """Recognize institution/organization-shaped tokens conservatively.

        A mixed-capitals abbreviation (FCVest, NDD) is not a person's name.
        Unknown terms stay reviewable, not automatically resolved.
        """
        name=str(value).strip()
        if re.match(r"^(?:universidade|faculdade|instituto|col[eé]gio|escola|fundação)\b",
                    name, re.I):
            return True
        return bool(re.fullmatch(r"[A-Z]{2,}[A-Za-z]{1,24}|[A-Z]{3,12}",name))

    @classmethod
    def _same_full_name_spelling(cls, spoken: str, known: str) -> bool:
        """Equivalent surname plus near-identical first name: no alias warning.

        This compares spelling only, and never asserts two human identities
        are the same person.
        """
        a=cls._person_key(spoken).split()
        b=cls._person_key(known).split()
        return bool(len(a)>=2 and len(a)==len(b) and a[1:]==b[1:]
                    and a[0][0]==b[0][0]
                    and SequenceMatcher(None,a[0],b[0]).ratio()>=0.85)

    def _reviewable_person_name(self, name: str, lesson: str) -> tuple[str,str]:
        for candidate in self._classroom_person_names(lesson):
            if self._person_key(candidate)==self._person_key(name):
                return candidate,''
            if self._same_full_name_spelling(name,candidate):
                # "Thiago Santini" versus "Tiago Santini" is an orthographic
                # uncertainty, not "Thiago (possibly Santini)".
                return name,''
            if self._possible_spelling_variant(name,candidate):
                surname=candidate.split()[-1]
                return candidate,(f'{name} (possivelmente {surname}) — '
                                   'grafia/identidade a conferir na gravação; '
                                   'nenhuma pessoa nova foi criada.')
        return name,''

    def _presenter_evidence(self, src, raw: str) -> tuple[str,str]:
        """Require more than a filename to suggest the presenter.

        A full name in the TXT/Classroom is stronger evidence. A self-intro
        using only a matching first name is reported as tentative, preserving
        the title's spelling and explicitly flagging the unverified surname.
        """
        candidate=self._title_person(Path(src["label"]).stem)
        if not candidate:
            return "", ""
        context="\n".join(
            str(item.get(field,"")) for _,item in self._context_rows(src["lesson"] or "")
            for field in ("autor","pessoas","descricao","atividades"))
        key=self._person_key(candidate)
        source_text=self._person_key(raw)
        if key and (key in source_text or key in self._person_key(context)):
            return candidate,"nome completo encontrado no TXT ou Classroom"
        tokens=key.split()
        if len(tokens)<2:
            return "", ""
        surname=re.escape(tokens[-1])
        for match in re.finditer(r"\b([a-z]{3,35})\s+"+surname+r"\b",source_text):
            first=match.group(1)
            if (first[0]==tokens[0][0] and
                    SequenceMatcher(None,first,tokens[0]).ratio()>=0.85):
                return candidate,"nome com pequena divergência de grafia no TXT; conferir"
        for match in re.finditer(
                r"\b(?:eu\s+sou(?:\s+o)?|me\s+chamo|meu\s+nome\s+e)"
                r"\s+([a-z]{3,35})\b",source_text):
            first=match.group(1)
            if (first[0]==tokens[0][0] and
                    SequenceMatcher(None,first,tokens[0]).ratio()>=0.85):
                return candidate,"apenas primeiro nome na apresentação; confirmar sobrenome"
        return "", ""

    def _grounded_presenter(self, src, raw: str) -> str:
        return self._presenter_evidence(src,raw)[0]

    def _person_warnings(self, src, analysis, raw: str) -> list[str]:
        warnings=[]
        for item in analysis.get("pessoas",[]):
            if not isinstance(item,dict):
                continue
            name=str(item.get("nome","")).strip()
            if (name and not self._nonperson_name(name) and
                    self._person_key(name) in self._person_key(raw)):
                _,warning=self._reviewable_person_name(name,src["lesson"] or "")
                if warning and warning not in warnings:
                    warnings.append(warning)
        for value in analysis.get("nomes_a_conferir",[]):
            if (not isinstance(value,str) or not value.strip() or
                    self._nonperson_name(value) or
                    self._person_key(value) not in self._person_key(raw)):
                continue
            _,warning=self._reviewable_person_name(value,src["lesson"] or "")
            chosen=warning or value
            if chosen not in warnings:
                warnings.append(chosen)
        return warnings

    def _uncertain_nonperson_terms(self, analysis, raw: str) -> list[str]:
        """Keep organization-like references outside human name lists."""
        names=[str(item.get("nome","")).strip()
               for item in analysis.get("pessoas",[]) if isinstance(item,dict)]
        names += [name for name in analysis.get("nomes_a_conferir",[])
                  if isinstance(name,str)]
        result=[]
        for name in names:
            if (self._nonperson_name(name) and
                    self._person_key(name) in self._person_key(raw) and
                    name not in result):
                result.append(name)
        return result[:10]

    def transcript_note(self, src, analysis: dict | None):
        lesson = src["lesson"] or "Aulas-Sem-Numero"
        video = src["video"] or "Sem-V"
        fname = f"{slug(Path(src['label']).stem, 52)}-{src['id'][:7]}.md"
        rel = f"02-Minhas-Aulas/{lesson}/{fname}"
        concepts = analysis.get("conceitos",[]) if analysis else []
        lesson_kind=analysis.get("tipo_aula","indefinida") if analysis else "indefinida"
        nontechnical = lesson_kind in ("apresentacao","organizacional","atividade")
        raw = self.vault / src["stored_path"]
        text = raw.read_text(encoding="utf-8-sig",errors="replace")
        concept_links_by_target = {}
        for c in concepts:
            if not isinstance(c, dict):
                continue
            name = str(c.get("nome", "")).strip()
            if name:
                if nontechnical:
                    # Keep the concept in the lesson as ordinary text.
                    concept_links_by_target[concept_slug(name)] = _escape_md(name)
                    continue
                canonical = self._corrected_concept(src, name, c, text)
                target = self._concept_target(name, src["id"])
                concept_links_by_target[target] = (
                    f"[[{target}|{_escape_md(canonical)}]]")
        concept_links = list(concept_links_by_target.values())
        modules = [] if nontechnical else [
            m for m in guess_modules(text[:24000] + ' ' + ' '.join(c.get('nome','') for c in concepts))
            if m != 'A-Classificar']
        times = evidence_excerpt(text)
        head = _frontmatter(tipo="aula", fonte_id=src["id"], aula=lesson,
                            gravacao=video, estado="resumida_com_ia" if analysis else "aguardando_ia")
        body = [head, f"# {Path(src['label']).stem}", ""]
        mismatch = opening_lesson_number_mismatch(text, lesson)
        if mismatch:
            stamp, spoken_number = mismatch
            body += [
                "## Numeração da aula — conferir", "",
                f"> O arquivo foi identificado como **{_escape_md(lesson)}**, mas a "
                f"abertura da transcrição em **{_escape_md(stamp)}** cita "
                f"**aula {spoken_number}**. Pode ser erro de transcrição ou referência "
                "a outra aula. A numeração do arquivo não foi alterada.", "",
            ]
        body.append("## Resumo da aula")
        if analysis:
            body.append(
                "> **Síntese assistida por IA — conferir na transcrição original.** "
                "Termos técnicos, exemplos e afirmações de implementação podem exigir "
                "revisão; a síntese não prova que algo foi demonstrado nem aprendido.")
            body.append(analysis.get("resumo") or "*Resumo da aula ainda incompleto; confira a transcrição original.*")
            warnings=[w for w in analysis.get("qualidade_pendente",[])
                      if isinstance(w,str) and w.strip()][:8]
            if warnings:
                body += ["", "## Qualidade da síntese — revisar", "",
                         "> A fonte original foi preservada. Estes avisos são verificações locais "
                         "e não exigem outra chamada à IA."]
                body += [f"- {_escape_md(w)}" for w in warnings]
            if concepts:
                body += ["", "## Conceitos identificados pela IA (conferir na fonte)", "",
                         "> Os nomes e explicações abaixo são interpretações da transcrição. "
                         "Um termo mencionado não significa que foi ensinado ou dominado."]
                for c in concepts:
                    name = c.get("nome","")
                    if not name:
                        continue
                    tempo = f" ({c['tempo']})" if c.get("tempo") else ""
                    body.append(f"- **{_escape_md(name)}**{tempo}: {_escape_md(c.get('explicacao',''))}")
                    warning = self._asr_concept_warning(c)
                    if warning:
                        body.append("  - **Nome possivelmente distorcido pela transcrição:** "
                                    + _escape_md(warning))
                    matched = (self._code_guess(lesson, name)
                               if self._marked_distortion(c, text) else None)
                    if matched and matched["candidate"].casefold() != name.casefold():
                        body.append("  - **Nome provável no código:** "
                                    + chr(96) + _escape_md(matched["candidate"]) + chr(96)
                                    + " (nome original mantido; consulte Dúvidas técnicas abaixo).")
            # Reconcile legacy cached analyses locally, without another API
            # call: a spoken abbreviation can back a mention even when the
            # whole expanded model label was not said. Do NOT auto-create a
            # concept note: no explanation has been checked for this label.
            suggested=[c for c in analysis.get("conceitos_a_conferir",[])
                       if isinstance(c,dict) and c.get("nome")
                       and not is_generic_code_term(c.get("nome"))]
            observed=[]
            unsupported=[]
            for candidate in suggested[:12]:
                mentioned=literal_technical_mention(candidate["nome"],text)
                if mentioned:
                    observed.append((candidate["nome"],mentioned))
                else:
                    unsupported.append(candidate)
            if observed:
                body += ["", "## Termos técnicos mencionados — explicação a conferir", "",
                         "> Os nomes abaixo aparecem no TXT de forma abreviada ou normalizada. "
                         "Isso não valida as explicações da IA nem comprova domínio."]
                for label,found in observed:
                    body.append("- `"+_escape_md(label)+"` — forma observada: `"+
                                _escape_md(found)+"`; conferir o contexto na transcrição.")
                    # This is a verified literal mention, not an ASR error:
                    # never submit an unmarked concept to the matcher.
            if unsupported:
                body += ["", "## Termos sugeridos pela IA para conferir", "",
                         "> Não foi encontrada menção literal nem abreviação verificável "
                         "para estes rótulos na transcrição. Não são conhecimentos confirmados."]
                for candidate in unsupported:
                    label=str(candidate.get("nome",""))
                    body.append("- `"+_escape_md(label)+
                                "` — hipótese da IA, conferir com transcrição e materiais.")
                    quote=str(candidate.get("evidencia_literal",""))[:260]
                    if quote:
                        stamp=str(candidate.get("tempo","")).strip()
                        body.append("  - **Citação literal conferida no TXT**" +
                                    (f" ({_escape_md(stamp)})" if stamp else "") +
                                    ": “"+_escape_md(quote)+"”.")
                        hypothesis=str(candidate.get("explicacao_sugerida",""))[:500]
                        if hypothesis:
                            body.append("  - **Interpretação da IA, não confirmada:** "+
                                        _escape_md(hypothesis))
            if analysis.get("exemplos"):
                body += ["", "## Exemplos mencionados"] + [
                    f"- {_escape_md(x)}" for x in analysis.get("exemplos",[])]
            if analysis.get("exemplos_reconstruidos_a_conferir"):
                body += ["", "## Exemplos reconstruídos pela IA, conferir", "",
                         "> Estes exemplos NÃO foram encontrados literalmente no TXT. "
                         "Não trate como código executado ou demonstrado."] + [
                             f"- {_escape_md(x)}"
                             for x in analysis.get("exemplos_reconstruidos_a_conferir", [])[:10]]
            # Only the analysis' explicit doubts become stateful doubts.
            # Never merge concepts or automatically suspected terms into this
            # list; a Portuguese concept is not a transcription error.
            questions = [q for q in analysis.get("duvidas",[])
                         if isinstance(q,str) and q.strip()]
            seen_questions = set()
            question_entries = []
            for q in questions:
                key = q.casefold().strip()
                if key in seen_questions:
                    continue
                seen_questions.add(key)
                question_entries.append((q, self._code_guess(lesson, q)))
            if question_entries:
                frozen = any(repo.get("frozen") for repo,_ in self._lesson_repos(lesson))
                note_text = ("Hipóteses encontradas no SHA congelado; "
                             "o áudio não foi conferido e o TXT original foi preservado."
                             if frozen else
                             "Dúvidas levantadas pela IA; conferir na gravação. "
                             "O TXT original foi preservado.")
                body += ["", "## Dúvidas técnicas e passagens inaudíveis", "",
                         "> "+note_text]
                current = {row["question"].casefold():row for row in
                           self.db.uncertainties_for_source(src["id"])
                           if row["source_digest"]==src["digest"]}
                for question, match in question_entries:
                    row = current.get(str(question).strip().casefold())
                    status = row["status"] if row is not None else (
                        "EXPLICADA_PELO_CODIGO" if match else "PENDENTE")
                    body.append(f"- {_escape_md(question)} — **Estado:** `{status}`")
                    if status == "EXPLICADA_PELO_CODIGO":
                        # A later follow-up may have a DIFFERENT frozen SHA.
                        evidences = json.loads(row["evidence_json"]) if row else [match]
                        for evidence in evidences:
                            if evidence and evidence.get("kind") == "codigo_congelado":
                                body.extend(code_evidence_lines(evidence))
            person_warnings=self._person_warnings(src,analysis,text)
            if person_warnings:
                body += ["", "## Nomes e apelidos para conferir", "",
                         "> Grafias semelhantes são pistas para revisão, não confirmação de identidade."] + [
                             f"- {_escape_md(x)}" for x in person_warnings]
        else:
            body += ["*Pendente: resumo ainda não gerado por IA. Se você configurou uma API gratuita em Ajustes, clique em Gerar Resumos para processar as transcrições pendentes. Os trechos abaixo não são síntese.*", "",
                     "## Trechos da transcrição para consulta (não são síntese)"]
            body += [f"- **{t}** — {_escape_md(s)}" for t,s in study_windows(text)]
        if analysis:
            body += ["", "## Tipo e contexto do encontro", "",
                     f"- Classificação sugerida pela IA: **{_escape_md(analysis.get('tipo_aula', 'indefinida'))}**.",
                     "- Uma apresentação não comprova aprendizado de programação."]
            people_entries=[]
            for person in analysis.get("pessoas",[]):
                if not isinstance(person,dict):
                    continue
                name=str(person.get("nome","")).strip()
                if not name:
                    continue
                _,variant=self._reviewable_person_name(name,lesson)
                if variant:
                    continue  # variants appear only under Nomes a conferir
                people_entries.append(person)
            presenter=self._grounded_presenter(src,text)
            if presenter and not any(self._person_key(p.get("nome","")) ==
                                     self._person_key(presenter) for p in people_entries):
                people_entries.append({
                    "nome":presenter,
                    "papel":"possível apresentador; confirmar função",
                    "informacao":"Pista do título e nome encontrado no TXT ou no contexto do Classroom",
                    "tempo":""})
            for key, heading in (("pessoas", "Pessoas citadas e papéis"),
                                 ("atividades", "Atividades mencionadas"),
                                 ("ferramentas", "Ferramentas e recursos citados"),
                                 ("marcos", "Metodologia, decisões e contexto")):
                entries=[]
                for entry in (people_entries if key == "pessoas"
                              else analysis.get(key, []))[:16]:
                    if not isinstance(entry, dict):
                        continue
                    parts = [entry.get(name, "") for name in ("nome", "papel", "informacao", "descricao", "contexto") if entry.get(name)]
                    if parts:
                        entries.append(f"- {_escape_md(' — '.join(parts))} " +
                                    (f"(**{_escape_md(entry.get('tempo', ''))}**)" if entry.get('tempo') else "(sem horário confirmado)"))
                if entries:
                    body.extend(["", f"## {heading}", "",
                                 "> Extração assistida por IA; confirme na fonte original antes de tratar como fato.",
                                 *entries])
        # Only the original lesson receives targeted follow-up evidence. New
        # lessons do not overwrite the former explanation or the source TXT.
        # A local match is a lead to review, never automatic proof of learning.
        if analysis:
            pending = self.db.uncertainties_for_source(src["id"])
            if pending:
                body += ["", "## Dúvidas da aula e retomadas posteriores", "",
                         "> Esta seção acompanha somente questões levantadas nesta fonte. "
                         "Novas aulas e códigos são pistas; não comprovam que a dúvida foi resolvida.",
                         ""]
                for row in pending[:30]:
                    question = _escape_md(row["question"])[:340]
                    status = row["status"]
                    body.append(f"### {question}")
                    body.append(f"- Estado: `{status}`.")
                    body.append(f"- [[{row['id']}|Abrir registro e histórico desta dúvida]]")
                    if status not in ("NOVA_EVIDENCIA_PARA_REVISAR", "EXPLICADA_PELO_CODIGO"):
                        body.append("- Nenhuma explicação posterior identificada nas fontes cadastradas.")
                        body.append("")
                        continue
                    try:
                        items = json.loads(row["evidence_json"])
                    except (ValueError, TypeError):
                        items = []
                    if not isinstance(items, list):
                        items = []
                    for evidence in items[:8]:
                        if not isinstance(evidence, dict):
                            continue
                        if evidence.get("kind") == "aula_posterior":
                            later = self.db.get_source(evidence.get("source_id", ""))
                            if later is None:
                                continue
                            link = Path(note_for(later)).with_suffix("").as_posix()
                            stamp = _escape_md(evidence.get("timestamp") or "sem horário confirmado")
                            excerpt = _escape_md(evidence.get("excerpt") or "")[:230]
                            body.append(
                                f"- **Aula posterior:** [[{link}|{_escape_md(later['lesson'] or later['label'])}]] "
                                f"({stamp}) — trecho observado: “{excerpt}”.")
                        elif evidence.get("kind") == "codigo_congelado":
                            body.append("- **Código da versão congelada:** "
                                        "ver dúvida técnica acima (pista, não prova do áudio).")
                        elif evidence.get("kind") == "codigo":
                            ref = _code_ref({"url":evidence.get("repo", ""),
                                             "sha":evidence.get("sha", "")},
                                            str(evidence.get("path", "")),
                                            evidence.get("line", 0))
                            body.append("- **Código relacionado:** " + ref +
                                        " (relação candidata, sem comprovar autoria ou aprendizagem).")
                    body.append("")
        self._append_context(body, lesson)
        # Source-grounded anchors make timestamps navigable without
        # modifying the preserved transcript in 99-Anexos.
        # Only publish anchored excerpts that help review the notes.
        # The complete, unmodified transcript remains in 99-Anexos;
        # copying every timed line here makes large vaults unwieldy.
        referenced_times = {str(c.get("tempo", "")).strip()
                            for c in concepts if isinstance(c, dict)}
        if analysis:
            for category in ("pessoas", "atividades", "ferramentas", "marcos"):
                referenced_times.update(str(item.get("tempo", "")).strip()
                    for item in analysis.get(category, [])
                    if isinstance(item, dict))
        referenced_times.update(t for t, _sentence in evidence_excerpt(text))
        source_rows = timed_lines(text)
        # A missing/invalid model timestamp is not an absence of timestamp
        # in the preserved TXT. Anchor literal mentions locally, without IA.
        for concept in concepts:
            if isinstance(concept, dict):
                referenced_times.update(
                    stamp for stamp, _sentence, _term, _anchor in
                    _literal_timed_evidence(str(concept.get("nome", "")), source_rows)
                )
        indexed = [(stamp, sentence, anchor)
                   for stamp, sentence, anchor in _indexed_source_rows(source_rows)
                   if stamp in referenced_times and sentence.strip()]
        if indexed:
            body += ["", "## Trechos da transcrição com horários verificáveis", "",
                     "> Trechos extraídos do TXT, sem comprovação do áudio do vídeo. "
                     "Em horários repetidos, o sufixo da âncora identifica cada fala."]
            for stamp, sentence, anchor in indexed:
                # Keep a contextual mention for the same concept cited by a
                # concept page, including very long timestamped paragraphs.
                matching = next((literal_technical_mention(str(c.get("nome", "")), sentence)
                                 for c in concepts if isinstance(c, dict)
                                 and literal_technical_mention(str(c.get("nome", "")), sentence)), "")
                body.append(f"- **{stamp}** — {_source_quote(sentence, 420, matching)} ^{anchor}")
        body += ["", "## Fontes originais", f"- Transcrição: [[{Path(src['stored_path']).stem}]]",
                 f"- Arquivo original: `{_escape_md(src['label'])}`", "", "## Conhecimentos relacionados",
                 ", ".join(concept_links) if concept_links else "*Serão vinculados após análise com IA.*",
                 "", "## Acesso às gravações"]
        registered_videos=[]
        for _, record in self._context_rows(lesson):
            registered_videos.extend(record.get('videos', []))
        for entry in registered_videos:
            if isinstance(entry, dict) and entry.get('url', '').startswith(('https://','http://')):
                body.append(f"- **{_escape_md(entry.get('titulo','Gravação'))}**: <{entry['url']}>")
        # Arquivos importados no passado continuam disponíveis; não fazemos novas cópias.
        for video_src in self.db.sources("video"):
            if src["lesson"] and src["lesson"] == video_src["lesson"] and (src["video"] == video_src["video"] or not src["video"] or not video_src["video"]):
                body.append(f"- Legado local: ![[{Path(video_src['stored_path']).name}]]")
        if not registered_videos and not any(s['lesson'] == lesson for s in self.db.sources('video')):
            body.append("*Link da gravação ainda não informado. Cadastre em Aulas → Contexto +.*")
        body += ["", "> Os códigos e nomes técnicos devem ser conferidos com o repositório antes de serem considerados verificados."]
        body += ["", "## Relações com códigos e projetos", ""]
        project_matches = []
        for repo, payload in self._lesson_repos(lesson):
            if repo.get("origin") == "automatica":
                body.append(f"- **Versão GitHub automática:** `{_escape_md(repo.get('version',''))}` "
                            f"— confiança **{_escape_md(repo.get('confidence','baixa'))}** "
                            f"— commit `{repo['sha'][:10]}`.")
                if repo.get("confidence") == "baixa":
                    body.append("> versão estimada; confira")
            matched = match_lesson_to_repository(text, analysis, payload, cap=5)
            if not matched:
                continue
            project_ref = f"{_project_ref(repo)}"
            body.append(f"### [[{project_ref}|{_escape_md(repo['name'])}]]")
            body.append("*Conexão sugerida por conceito mencionado + código encontrado; não prova autoria nem que foi programado nesta aula.*")
            for e in matched:
                body.append(f"- `{e['concept']}` — {_code_ref(repo, e['path'], e['line'])} no commit `{repo['sha'][:10]}`")
                snippet = str(e.get("snippet", "")).strip()
                if snippet:
                    ext = Path(e["path"]).suffix.lower()
                    language = {".cs": "csharp", ".ts": "typescript", ".tsx": "tsx",
                                ".js": "javascript", ".jsx": "jsx", ".py": "python",
                                ".sql": "sql"}.get(ext, "text")
                    body.extend(["", f"```{language}", snippet.replace("```", "` ` `"), "```", ""])
            project_matches.append((repo, payload))
        warning = self.lesson_repo_index.warning(lesson)
        if warning:
            body.append("> " + warning)
        if not project_matches:
            verified = any(row["status"] == "EXPLICADA_PELO_CODIGO"
                           and row["source_digest"] == src["digest"]
                           for row in self.db.uncertainties_for_source(src["id"]))
            if verified:
                body.append("*Dúvidas relacionadas a identificadores concretos da versão congelada "
                            "estão documentadas acima. Não houve outra relação literal "
                            "de conceito identificada nesta seção.*")
            else:
                body.append("*Associação temporariamente pendente; não significa ausência de código.*"
                            if "pendente por limite" in warning else
                            "*Nenhum vínculo com código encontrado ainda. Pode ser incluído quando os repositórios chegarem.*")
        total, frozen, _ = self.lesson_repo_index._status.get(lesson, (0, [], []))
        if total<0 or total>len(frozen):
            body.append("**Código GitHub pendente:** congele a versão desta aula antes de relacionar código às notas.")
        body += ["", "## Comparação revisada por IA (com referências)"]
        validated_any=False
        for repo, payload in project_matches:
            result=self.db.connection(src['id'],src['digest'],repo['url'],repo['sha'])
            if not result:continue
            validated_any=True
            body += [f"### {repo['name']} — commit `{repo['sha'][:10]}`", "",
                     "> Interpretação assistida por IA, não confirmação de autoria, domínio nem data exata da implementação."]
            for item in result.get('relacoes',[]):
                body.append(f"- **{_escape_md(item['conceito'])}** ({item['tempo'] or 'sem minuto'}): "
                            f"{_escape_md(item['evolucao'])} — {_code_ref(repo, item['path'], item['line'])} "
                            f"**[{item['status']}]**")
            for item in result.get('novidades',[]):
                body.append(f"- **Possível novidade — {_escape_md(item['conceito'])}:** "
                            f"{_escape_md(item['explicacao'])} ({item['tempo'] or 'sem minuto'})")
            for item in result.get('correcoes',[]):
                body.append(f"- **Possível erro de transcrição:** `{_escape_md(item['ouvido'])}` → "
                            f"`{_escape_md(item['sugestao'])}` — {_code_ref(repo, item['path'], item['line'])} "
                            f"**[{item['status']}]**")
        if not validated_any:
            body.append('*Ainda sem comparação pela IA; relações acima são pistas verificadas de texto e código.*')
        body = self._keep_previous_code(body, rel, lesson,
                                        "## Relações com códigos e projetos",
                                        "## Termos suspeitos da transcrição")
        # Preserve offline ASR-only review hints separately from verified
        # frozen-code matches; old lessons remain reviewable without code.
        if not any(repo.get("frozen") for repo, _ in self._lesson_repos(lesson)):
            raw_hints = suspected_technical_transcription(text)
            if raw_hints:
                body += ["", "## Hipóteses da transcrição sem conferência de código", "",
                         "> O áudio não foi conferido. Estas são apenas grafias "
                         "suspeitas do TXT; nenhum identificador específico "
                         "de código foi verificado nesta aula.", ""]
                for stamp, heard, suggestion in raw_hints:
                    if is_generic_code_term(heard) or is_generic_code_term(suggestion):
                        continue
                    body.append("- **" + _escape_md(stamp) + "** — transcrito: "
                                + chr(96) + _escape_md(heard) + chr(96)
                                + "; hipótese a revisar: "
                                + chr(96) + _escape_md(suggestion) + chr(96) + ".")
        body += ["", "## Termos suspeitos da transcrição", ""]
        # Do not duplicate the clue or propose broad conceptual rewordings.
        # Every grounded correction lives in Dúvidas técnicas above.
        if any(matched for _question, matched in
               (question_entries if analysis else [])):
            body.append("*Possíveis erros de grafia com identificador específico "
                        "no código: ver Dúvidas técnicas e passagens inaudíveis acima.*")
        else:
            body.append("*Nenhuma correção específica fundamentada no código "
                        "congelado desta aula.*")
        self.write(rel, "\n".join(body).strip() + "\n")
        return rel, concepts, modules

    def rebuild(self):
        """Deriva notas e revisão incremental das fontes originais cadastradas."""
        self._lesson_repo_memo.clear()
        self._frozen_question_memo.clear()
        self._concept_aliases.clear()
        self.lesson_repo_index.begin_run()
        # Fail closed before *any* Markdown write if a cached transcript no
        # longer agrees with the SQLite catalog. User notes stay untouched.
        from .content import file_hash
        for source in self.db.sources("transcript"):
            stored = self.vault / (source["stored_path"] or "")
            path = stored.resolve()
            if (stored.is_symlink() or not path.is_relative_to(self.vault) or
                    not path.is_file() or file_hash(path) != source["digest"]):
                self.db.update_status(source["id"], "NEEDS_REVIEW")
                raise ValueError("Fonte do cofre alterada ou ausente: " +
                                 source["label"] + ". Reimporte o original.")
        refresh_uncertainties(self.db, self.lesson_repo_index)
        self._prepare_concept_targets()
        self._atlas = make_atlas(self.db, concept_targets=self._concept_targets)
        concept_map = defaultdict(list)
        module_map = defaultdict(list)
        lesson_links = []
        person_map = defaultdict(list)
        transcripts_by_lesson = set()
        for src in self.db.sources("transcript"):
            analysis = self.db.analysis(src["id"],src["digest"])
            note, concepts, modules = self.transcript_note(src, analysis)
            lesson_links.append((src, note))
            if src["lesson"]:
                transcripts_by_lesson.add(src["lesson"])
            if analysis:
                original = (self.vault / src["stored_path"]).read_text(encoding="utf-8-sig", errors="replace")
                normalized = self._person_key(original)
                names_seen=set()
                for person in analysis.get("pessoas", []):
                    if not isinstance(person,dict):
                        continue
                    name = str(person.get("nome", "")).strip()
                    # Must be literal in the TXT; do not promote spelling
                    # variants to a new person or claim identity with a known name.
                    if not 3 <= len(name) <= 130 or self._person_key(name) not in normalized:
                        continue
                    canonical,warning=self._reviewable_person_name(name,src['lesson'] or '')
                    if warning:
                        continue  # only Nomes e apelidos para conferir
                    person_map[slug(canonical)].append(
                        (canonical, src, note, person, 'transcrição (extração IA, revisar)'))
                    names_seen.add(self._person_key(canonical))
                presenter=self._grounded_presenter(src,original)
                if presenter and self._person_key(presenter) not in names_seen:
                    person_map[slug(presenter)].append(
                        (presenter, src, note, {
                            'informacao':'Nome corroborado no TXT ou contexto; possível apresentador pelo título'},
                         'título da gravação + TXT/contexto (função a confirmar)'))
            for m in modules:
                module_map[m].append((src,note,analysis))
            if not analysis:
                continue
            if analysis.get("tipo_aula") not in ("apresentacao","organizacional","atividade"):
                for concept in concepts:
                    if not isinstance(concept,dict):
                        continue
                    name = str(concept.get("nome", "")).strip()
                    if name:
                        canonical = self._corrected_concept(src, name, concept, original)
                        stored_concept = ({**concept, "nome_original":name}
                                          if canonical != name else concept)
                        concept_map[concept_slug(canonical)].append(
                            (canonical,src,note,stored_concept))
        # Classroom can contain names as explicitly user-provided text, even if there is
        # no transcript or code. It is a separate kind of evidence and must be labeled.
        lesson_to_note = {s['lesson']: n for s, n in lesson_links if s['lesson']}
        for src in self.db.sources("classroom"):
            for _, item in self._context_rows(src["lesson"]):
                for row in item.get("pessoas", "").splitlines()[:25]:
                    line = row.strip().lstrip("-• ")
                    if not line:
                        continue
                    name = re.split(r"\s+[—–-]\s+|\s*:\s*", line, maxsplit=1)[0].strip()
                    if not 3 <= len(name) <= 80:
                        continue
                    person_map[slug(name)].append((name, src, lesson_to_note.get(src["lesson"], f"02-Minhas-Aulas/{src['lesson']}/00-contexto-{slug(src['lesson'])}.md"),
                                                   {"informacao": line}, "Classroom (registrado pelo usuário)"))
        for cslug, records in person_map.items():
            name = records[0][0]
            body = [_frontmatter(tipo="pessoa", estado="referencias_a_revisar", fontes=len(records)),
                    f"# {_escape_md(name)}", "", "> Identificador baseado no nome; pessoas homônimas podem existir.",
                    "> Informações extraídas da fonte ou cadastradas manualmente; não presumir identidade, cargo ou fatos não citados.",
                    "", "## Menções nas aulas", ""]
            for _, src, note, person, origin in records:
                body.append(f"- [[{Path(note).stem}|{_escape_md(src['lesson'] or src['label'])}]]: "
                            f"{_escape_md(person.get('informacao') or person.get('papel') or 'Mencionado')} "
                            f"({origin}; {person.get('tempo') or 'sem horário confirmado'}).")
            self.write(f"01-Meu-Conhecimento/Pessoas/{cslug}.md", "\n".join(body) + "\n")

        # Página inicial para leitura humana: uma aula = várias gravações e fontes.
        lesson_group = defaultdict(list)
        for src, note in lesson_links:
            if src['lesson']:lesson_group[src['lesson']].append((src,note))
        all_lessons = sorted({s['lesson'] for s in self.db.sources() if s['lesson']})
        overview_links = {}
        for lesson in all_lessons:
            overview_links[lesson] = self.lesson_overview(lesson, lesson_group.get(lesson, []))

        # Index every lesson, even a lesson with only a Classroom description or video.
        for lesson in sorted({s['lesson'] for s in self.db.sources() if s['lesson']} - transcripts_by_lesson):
            self._other_lesson_note(lesson, [s for s in self.db.sources() if s['lesson'] == lesson])

        repo_info = [(dict(repo), json.loads(repo["payload"]))
                     for repo in self.db.repositories()]
        known_projects = {_project_ref(repo) for repo, _ in repo_info}
        for lesson in all_lessons:
            for repo, payload in self._lesson_repos(lesson):
                if repo["frozen"] and _project_ref(repo) not in known_projects:
                    known_projects.add(_project_ref(repo))
                    repo_info.append((repo, payload))
        for repo, payload in repo_info:
            rel = f"03-Meus-Projetos/{_project_ref(repo)}.md"
            body = [_frontmatter(tipo="projeto", sha=repo["sha"], estado=repo["status"]),
                    f"# Projeto — {repo['name']}", "", f"- Repositório: {repo['url']}",
                    f"- Commit analisado: `{repo['sha']}`", "",
                    "## Contexto e colaboração", "",
                    "- Pode ser trabalho individual, em dupla ou em equipe: **não inferir autoria individual de um arquivo**.",
                    "- Autores de commits ajudam a investigar a contribuição, mas não comprovam quem escreveu cada linha.",
                    f"- Múltiplos autores de commits identificados: {'sim' if payload.get('collaboration') else 'não detectado / histórico incompleto'}.",
                    "", "### Histórico recente disponível"]
            for h in payload.get("history",[])[:25]:
                if not isinstance(h, dict):continue
                body.append(f"- `{_escape_md(h.get('sha','desconhecido'))}` ({_escape_md(h.get('date','sem data'))}) — {_escape_md(h.get('subject','sem assunto'))} "
                            f"— autor registrado: {_escape_md(h.get('author','desconhecido'))}")
            if not payload.get("history"):
                body.append("*Histórico não disponível ou repositório sem commits registrados.*")
            body += ["", "## Tecnologias observadas", ", ".join(payload.get("technologies",[])) or "*Não detectadas*",
                     "", "## Documentação do próprio repositório"]
            for doc in payload.get("documentation",[])[:10]:
                body.append(f"- `{_escape_md(doc['path'])}`: {_escape_md(doc['excerpt'][:250])}")
            if not payload.get("documentation"):
                body.append("*Nenhum documento Markdown encontrado no conjunto seguro analisado.*")
            body += ["", "## Código real — trechos com arquivo e linha", "",
                     "> Evidências do commit acima, somente leitura. Uma correspondência textual não comprova que o aluno domina o conceito."]
            for e in payload.get("evidence",[])[:30]:
                ext = Path(e["path"]).suffix.lower()
                lang = {".cs":"csharp", ".ts":"typescript", ".tsx":"tsx", ".js":"javascript",
                        ".jsx":"jsx", ".py":"python", ".sql":"sql"}.get(ext,"text")
                body += [f"### `{e['concept']}` — {_code_ref(repo, e['path'], e['line'])}", "",
                         f"```{lang}", e["snippet"].replace("```","` ` `"), "```", ""]
            if not payload.get("evidence"):
                body.append("*Nenhum conceito da lista rastreada encontrado.*")
            # Names declared in source code (including course-specific service
            # classes and interfaces) make the repository useful for studying,
            # even when no predefined terminology pattern matches it.
            symbols=payload.get("symbols",[])
            if isinstance(symbols,list) and symbols:
                body += ["", "## Classes, interfaces e funções presentes no código", "",
                         "> Nomes e linhas obtidos dos arquivos do commit; não significam "
                         "que o professor explicou estas declarações ou que o aluno as escreveu."]
                seen_symbols=set()
                for item in symbols:
                    if not isinstance(item,dict):
                        continue
                    name=item.get("name","")
                    path=item.get("path","")
                    line=item.get("line",0)
                    if not name or not path or (path,line) in seen_symbols:
                        continue
                    seen_symbols.add((path,line))
                    body.append(f"- **`{_escape_md(name)}`** — {_code_ref(repo,path,line)}")
                    if len(seen_symbols)>=35:
                        body.append("*Outras declarações permanecem no índice local; "
                                    "veja o repositório para o código completo.*")
                        break
            body += ["", "## Conexões com aulas", ""]
            linked = False
            for src, note in lesson_links:
                if not any(_project_ref(candidate) == _project_ref(repo)
                           for candidate, _ in self._lesson_repos(src["lesson"] or "")):
                    continue
                raw=(self.vault/src["stored_path"]).read_text(encoding="utf-8-sig",errors="replace")
                analysis=self.db.analysis(src["id"],src["digest"])
                links=match_lesson_to_repository(raw,analysis,payload,cap=4)
                if links:
                    linked=True
                    body.append(f"- [[{Path(note).stem}|{_escape_md(src['label'])}]] — " + ", ".join(
                        f"`{link['concept']}` ({_escape_md(link['path'])}:{link['line']})" for link in links))
            if not linked:
                body.append("*Aguardando aulas com evidências compatíveis.*")
            body += ["", "## Próximos conhecimentos e pendências",
                     "- Compare o código com as aulas vinculadas. Se houver divergência, consulte a transcrição e o vídeo.",
                     "- Para atribuir prática pessoal ou domínio, adicione confirmação ou evidência de atividade individual."]
            self.write(rel,"\n".join(body)+"\n")
        # Concept pages never certify that an AI interpretation was taught.
        # They retain all distinct explanations across chunks and show
        # whether the literal technical term appears in the preserved source.
        for cslug, entries in concept_map.items():
            name = entries[0][0]
            observed = []
            for _, src, note, concept in entries:
                original = (self.vault / src["stored_path"]).read_text(
                    encoding="utf-8-sig", errors="replace")
                observed.append(_term_in_source(name, original))
            state = "termo_encontrado_na_fonte" if any(observed) else "interpretacao_ia_sem_termo_literal"
            body = [_frontmatter(tipo="conceito", fontes=len(entries), estado=state),
                    f"# {_escape_md(name)}", "",
                    "> Conceito identificado por IA. Um termo literal na transcrição "
                    "não confirma sozinho que houve explicação, prática ou domínio.",
                    "", "## Explicações e referências das aulas", ""]
            for (_, src, note, concept), literal in zip(entries, observed):
                raw = (self.vault / src["stored_path"]).read_text(
                    encoding="utf-8-sig", errors="replace")
                recorded = str(concept.get("tempo", "")).strip()
                source_rows = timed_lines(raw)
                matches = _literal_timed_evidence(
                    name, source_rows, preferred=recorded)
                groups = _group_timed_evidence(source_rows, matches, preferred=recorded)
                where = f"[[{Path(note).with_suffix('').as_posix()}|{_escape_md(src['label'])}]]"
                explanation = _escape_md(concept.get("explicacao", ""))
                body.extend(["", f"### {_escape_md(src['label'])}", "",
                             "- **Explicação sugerida pela IA (conferir):** " +
                             (explanation or "*Não fornecida pela análise.*"),
                             f"- **Fonte:** {where}."])
                warning = self._asr_concept_warning(concept)
                if warning:
                    body.append("- **Nome possivelmente distorcido pela transcrição:** "
                                + _escape_md(warning))
                if concept.get("nome_original"):
                    body.append("- **Nome original mantido no TXT:** "
                                + _escape_md(concept["nome_original"])
                                + "; **nome provável no código:** "
                                + chr(96) + _escape_md(name) + chr(96) + ".")
                if groups:
                    for (stamp, sentence, form, anchor), nearby in groups:
                        target_note, is_proposal = self._published_anchor_target(
                            note, anchor)
                        source_time = (
                            f"[[{target_note}#^{anchor}|{stamp}]]"
                            if target_note else f"**{stamp}** (âncora ainda não publicada)"
                        )
                        body.append(
                            f"- **Menção literal na transcrição:** "
                            f"{source_time} — forma observada: "
                            f"{chr(96)}{_escape_md(form)}{chr(96)}.")
                        if is_proposal:
                            body.append(
                                "  > A referência abre uma **proposta de atualização**; "
                                "sua nota editada manualmente não foi substituída.")
                        body.extend([
                            "",
                            "  > **Contexto próximo do TXT (para conferência):** "
                            "trechos originais em sequência; isso não valida automaticamente a explicação da IA.",
                            "  >",
                        ])
                        for context_stamp, context_sentence in nearby:
                            body.append(
                                f"  > - {context_stamp} — {_source_quote(context_sentence, 300, form)}")
                        body.append("")
                    if not recorded or recorded not in {r[0] for r in matches}:
                        body.append(
                            "- **Horário da análise da IA:** ausente ou não associado "
                            "à menção; horários acima recuperados diretamente do TXT.")
                elif literal:
                    body.append(
                        "- **Menção no TXT:** termo encontrado literalmente, "
                        "mas sem trecho com horário verificável nesta fonte.")
                else:
                    body.append(
                        "- **Sem evidência literal:** o termo não foi localizado "
                        "na transcrição; confira a interpretação da IA na fonte.")
            body += ["", "## Evidências e aprendizagem", "",
                     "- **Mencionado:** confira a fala original antes de considerar o conceito confirmado.",
                     "- **Ensinado:** requer explicação verificável na fonte; termo citado não basta.",
                     "- **Praticado:** requer exercício/atividade com evidência.",
                     "- **Domínio do aluno:** não é deduzido automaticamente.",
                     "", "## Projetos relacionados", ""]
            for repo, payload in repo_info:
                matches = [e for e in payload.get("evidence",[])
                           if norm(e["concept"]) == norm(name)]
                if matches:
                    first = matches[0]
                    body.append(f"- [[{_project_ref(repo)}|{_escape_md(repo['name'])}]]: "
                                f"{_code_ref(repo, first['path'], first['line'])} — "
                                "código existente, sem atribuição automática de autoria.")
            if body[-1] == "## Projetos relacionados":
                body.append("*Nenhum vínculo de código encontrado no índice.*")
            self.write(f"01-Meu-Conhecimento/Conceitos/{self._concept_target(name)}.md",
                       "\n".join(body) + "\n")

        # A module page is a readable review guide, not a 260-character index.
        # All source summaries are retained; interpretation remains attributed.
        for module, entries in module_map.items():
            by_lesson = defaultdict(list)
            for src, note, analysis in entries:
                by_lesson[src["lesson"] or "Aulas-Sem-Numero"].append((src, note, analysis))
            body = [_frontmatter(tipo="modulo", fontes=len(entries),
                                 estado="sintese_de_fontes_nao_revisada"),
                    f"# {module.replace('-', ' ')}", "",
                    "> Guia de revisão gerado a partir das fontes analisadas. "
                    "A classificação do módulo é automática por palavras-chave; "
                    "confira se cada aula realmente pertence a ele. "
                    "As explicações abaixo vêm de análises por IA e precisam de conferência com o professor.",
                    "", "## Percurso das aulas", ""]
            for lesson in sorted(by_lesson, key=lesson_order):
                recordings = sorted(by_lesson[lesson],
                                    key=lambda item: (item[0]["video"] or "", item[0]["label"]))
                if lesson != "Aulas-Sem-Numero":
                    body.append(f"### [[02-Minhas-Aulas/{lesson}/00-Visao-geral|{lesson}]]")
                else:
                    body.append("### Aulas ainda sem número identificado")
                body.append("")
                for src, note, analysis in recordings:
                    link = Path(note).with_suffix("").as_posix()
                    body.append(f"#### [[{link}|{_escape_md(src['label'])}]]")
                    if not analysis:
                        body.extend(["", "*Transcrição importada; resumo pendente de IA.*", ""])
                        continue
                    summary = str(analysis.get("resumo", "")).strip()
                    body.extend(["", summary if summary else "*Resumo pendente.*", ""])
                    examples = analysis.get("exemplos", [])
                    if examples:
                        body.extend(["**Exemplos relatados na aula:**", ""])
                        for example in examples:
                            body.append(f"- {_escape_md(example)}")
                    doubts = analysis.get("duvidas", [])
                    if doubts:
                        body.extend(["", "**Passagens a conferir:**", ""])
                        for doubt in doubts:
                            body.append(f"- {_escape_md(doubt)}")
                    body.append("")
            body += ["", "## Conceitos e explicações encontrados nas fontes", "",
                     "> Termos e explicações extraídos pela IA, não certificação de que foram ensinados.", ""]
            seen = set()
            for src, note, analysis in entries:
                if not analysis:
                    continue
                raw = (self.vault / src["stored_path"]).read_text(
                    encoding="utf-8-sig", errors="replace")
                valid_times = {t for t, _ in timed_lines(raw) if t != "sem horário"}
                for concept in analysis.get("conceitos", []):
                    name = str(concept.get("nome", "")).strip()
                    if not name:
                        continue
                    explanation = str(concept.get("explicacao", "")).strip()
                    stamp = str(concept.get("tempo", "")).strip()
                    key = (src["id"], concept_slug(name), stamp, explanation.casefold())
                    if key in seen:
                        continue
                    seen.add(key)
                    note_path = Path(note).with_suffix("").as_posix()
                    where = (f"[[{note_path}#^{_time_id(stamp)}|{src['lesson']} · {stamp}]]"
                             if stamp in valid_times else
                             f"[[{note_path}|{src['lesson'] or src['label']}]]")
                    literal = "termo literal presente" if _term_in_source(name, raw) else "termo inferido pela IA"
                    body.append(f"- **[[{self._concept_target(name)}|{_escape_md(name)}]]**: "
                                f"{_escape_md(explanation)} — {where} ({literal}).")
            if not seen:
                body.append("*Nenhum conceito extraído ainda; o resumo por gravação permanece disponível.*")
            body += ["", "## Projetos e documentação relacionados", ""]
            project_found = False
            for repo, payload in repo_info:
                docs = [d for d in payload.get("documentation", [])
                        if module in guess_modules(d["path"] + " " + d["excerpt"])]
                if not docs:
                    continue
                project_found = True
                body.append(f"- [[{_project_ref(repo)}|{_escape_md(repo['name'])}]] — "
                            + ", ".join(f"`{_escape_md(d['path'])}`" for d in docs[:4])
                            + "; documentação existente no repositório, não necessariamente conteúdo da aula")
            if not project_found:
                body.append("*Nenhuma documentação de repositório associada a este módulo.*")
            body += ["", "## Como revisar", "",
                     "1. Leia o resumo de cada gravação e abra a nota para ver as fontes.",
                     "2. Compare conceitos e exemplos com os trechos de transcrição e o código.",
                     "3. Registre dúvidas em suas notas pessoais; este índice não altera fontes originais."]
            self.write(f"01-Meu-Conhecimento/Modulos/{module}.md",
                       "\n".join(body) + "\n")
        # Uma linha do tempo única e auditável, produzida a partir das mesmas
        # fontes do Obsidian; não consome requisições nem deduz domínio.
        atlas = self._atlas
        self.write("01-Meu-Conhecimento/Mapa-da-Evolucao.md", render_atlas(atlas))
        doubts_index, doubts_notes = render_uncertainties(self.db)
        for relative, note_text in doubts_notes:
            self.write(relative, note_text)
        self.write("01-Meu-Conhecimento/Indice-de-Duvidas.md", doubts_index)
        context = ["# MEU_CONTEXTO — Guia para IA", "",
                   "> Este documento resume **o que foi abordado nos materiais**, não comprova domínio pessoal.",
                   "> Use as notas vinculadas como evidência antes de recomendar recursos de programação.", "",
                   "## Módulos vistos nos materiais", "", "- [[Mapa-da-Evolucao|Mapa de evolução com horários e código]]"]
        context += [f"- [[{m}|{m.replace('-', ' ')}]]: {len(entries)} fonte(s)" for m,entries in module_map.items()]
        context += ["", "## Dúvidas e interpretações pendentes",
                    "- [[Indice-de-Duvidas|Índice rastreável de dúvidas e evidências posteriores]]",
                    "> Evidências posteriores são pistas, nunca correções confirmadas automaticamente.",
                    "", "## Conceitos encontrados"]
        context += [f"- [[{self._concept_target(v[0][0])}|{_escape_md(v[0][0])}]] — identificado pela IA; confirmar na fonte" for k,v in sorted(concept_map.items())]
        context += ["", "## Evolução: antes na aula, agora no código"]
        for repo,payload in repo_info:
            matches=[]
            for src,note in lesson_links:
                if not any(_project_ref(candidate) == _project_ref(repo)
                           for candidate, _ in self._lesson_repos(src["lesson"] or "")):
                    continue
                raw=(self.vault/src["stored_path"]).read_text(encoding="utf-8-sig",errors="replace")
                analysis=self.db.analysis(src["id"],src["digest"])
                ev=match_lesson_to_repository(raw,analysis,payload,cap=3)
                if ev:
                    matches.append((src,note,ev))
            if matches:
                context.append(f"- **{repo['name']}:** " + "; ".join(
                    f"[[{Path(n).stem}|{src['lesson'] or src['label']}]] aborda "
                    + ", ".join(f"`{e['concept']}`" for e in ev) for src,n,ev in matches[:5])
                    + f"; trechos observados em [[{_project_ref(repo)}|{repo['name']}]]. "
                    + "*Associação candidata, não prova de quem implementou ou quando.*")
        context += ["", "## Pessoas mencionadas nas fontes", ""]
        context += [f"- [[{k}|{_escape_md(v[0][0])}]] — {len(v)} fonte(s); contexto/identidade a conferir" for k,v in sorted(person_map.items())]
        context += ["", "## Aulas sem transcrição ou código", ""]
        context += [f"- [[00-contexto-{slug(lesson)}|{lesson}]] — contexto registrado" for lesson in sorted({s['lesson'] for s in self.db.sources() if s['lesson']} - transcripts_by_lesson)]
        context += ["", "## Projetos analisados"]
        context += [f"- {r['name']} — `{r['sha'][:10]}` (código observado; autoria e domínio não presumidos)" for r,_ in repo_info]
        context += ["", "## Orientações para a IA", "- Antes de explicar, consulte os conceitos, aulas e projetos relevantes.",
                    "- Priorize técnicas comprovadamente vistas nas fontes; pergunte antes de usar algo novo.",
                    "- Diferencie o que foi ensinado, o que consta no GitHub e o que eu demonstrei dominar.",
                    "- Se não houver evidência, diga que não encontrou; não invente domínio.",
                    "- Para quebra-cucas, oriente em pequenas etapas e evite solução completa sem pedido."]
        self.write("00-Inicio/MEU_CONTEXTO.md", "\n".join(context)+"\n")
        index = ["# Minha Biblioteca", "", "## Comece aqui", "- [[MEU_CONTEXTO]] — contexto para IAs", "",
                 "## Conhecimentos", "- [[Mapa-da-Evolucao|Mapa de evolução do aprendizado]]",
                 "- [[Indice-de-Duvidas|Dúvidas e referências para revisão]]"]
        index += [f"- [[{module}|{module.replace('-', ' ')}]]" for module in module_map]
        index += ["", "## Aulas — abra a visão geral para reunir V01, V02 e demais materiais"]
        index += [f"- [[02-Minhas-Aulas/{lesson}/00-Visao-geral|{lesson} — visão geral]]" for lesson in all_lessons]
        for lesson in sorted({s['lesson'] for s in self.db.sources() if s['lesson']} - transcripts_by_lesson):
            index.append(f"- [[00-contexto-{slug(lesson)}|{lesson}]] — contexto sem transcrição")
        index += [f"- [[{Path(note).stem}|{src['label']}]] — gravação e transcrição" for src,note in lesson_links]
        index += ["", "## Projetos"]
        index += [f"- [[{_project_ref(repo)}|{repo['name']}]] — {repo['url']}" for repo,_ in repo_info]
        index += ["", "> A aplicação não altera conteúdo de `05-Anotacoes-Pessoais`."]
        self.write("00-Inicio/Dashboard.md", "\n".join(index)+"\n")
        states = defaultdict(int)
        for src in self.db.sources():
            states[src["status"]] += 1
        self.write("90-Sistema/Processamento.md", "# Status do processamento\n\n" +
                   "\n".join(f"- **{status}:** {count}" for status,count in sorted(states.items())) + "\n")
        return {"aulas":len({s["lesson"] for s in self.db.sources() if s["lesson"]}), "conceitos":len(concept_map), "pessoas":len(person_map), "projetos":len(repo_info)}
