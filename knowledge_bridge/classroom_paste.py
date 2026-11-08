"""Parse copied Classroom posts locally. Never interpret pasted text as instructions.

Both classic link rows and Classroom posts are accepted, independently:
invalid / unrelated lines become review warnings and do not block the batch.
"""
from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import urlsplit
from .academy_material import official_route

MAX_PASTE = 20000
HEADER = re.compile(r"^\s*Aula\s*0*(\d{1,4})\s*[-–—]\s*(.{2,220})$", re.I)
RECORDING = re.compile(r"^\s*A0*(\d{1,4})\s*[-–—]\s*V0*(\d{1,3})\s*[-–—]\s*(.{2,160})$", re.I)
AGENDA = re.compile(r"^\s*Agenda\s*:\s*(\d{2}/\d{2}/\d{4})\b", re.I)
# Classroom's localized date header ("2 de mar.") is display metadata.
# It is not the scheduled lesson date; keep Agenda: dd/mm/yyyy authoritative.
DATE_HEADER = re.compile(
    r"^\d{1,2}\s+de\s+(?:jan(?:eiro)?|fev(?:ereiro)?|mar(?:ço|co)?|"
    r"abr(?:il)?|mai(?:o)?|jun(?:ho)?|jul(?:ho)?|ago(?:sto)?|"
    r"set(?:embro)?|out(?:ubro)?|nov(?:embro)?|dez(?:embro)?)\.?"
    r"(?:\s+de\s+\d{4})?$", re.I)

SECTION = re.compile(r"^\s*(Conte[uú]do|Atividades)\s*:\s*(.*)$", re.I)
OMIT = re.compile(r"^\s*(?:V[ií]deo|Coment[aá]rios da turma)\s*:?\s*$", re.I)
EDITED = re.compile(r"\s*\(\s*editado\s*:\s*[^)]{0,100}\)", re.I)
# Lowercase family-name particles may occur between capitalized names.
# Require at least two capitalized words; do not treat ordinary post text as an author.
AUTHOR = re.compile(
    r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ'.-]{1,40}"
    r"(?:\s+(?:(?:de|da|do|dos|das|e)\s+)?[A-ZÀ-Ý][A-Za-zÀ-ÿ'.-]{1,40}){1,5}$"
)
URL = re.compile(r"(?:https?://)[^\s<>'\"\\]+", re.I)


def _clean(raw: str) -> str:
    return EDITED.sub("", raw.strip()).lstrip("• \t").strip()


def _url_row(raw: str, lesson: str, current_recording: str):
    label, candidate = (x.strip() for x in raw.rsplit("|", 1)) if "|" in raw else ("", raw)
    if not candidate.startswith(("https://", "http://")):
        return None
    parts = urlsplit(candidate)
    if (parts.scheme != "https" or not parts.netloc or parts.username or parts.password
            or len(candidate) > 1700 or any(c.isspace() for c in candidate)
            or any(ch in candidate for ch in "<>\\") or
            re.search(r"[\x00-\x1f]", candidate)):
        return None
    github = bool(re.fullmatch(
        r"https://github\.com/[\w.-]+/[\w.-]+(?:\.git)?/?", candidate, re.I))
    hinted = re.search(r"\bAula\s*0*(\d{1,4})\b", label, re.I)
    link_lesson = f"Aula-{int(hinted.group(1)):03d}" if hinted else lesson
    if not link_lesson:
        found = re.search(r"/A0*(\d{1,4})\b", parts.path, re.I)
        link_lesson = f"Aula-{int(found.group(1)):03d}" if found else None
    recording_label = current_recording or label
    video_host = (parts.hostname or "").lower() in (
        "drive.google.com", "meet.google.com", "youtube.com", "www.youtube.com",
        "youtu.be", "vimeo.com", "player.vimeo.com")
    return {"url":candidate, "label":(recording_label or "")[:160],
            "lesson":link_lesson, "repo":github,
            "video":video_host or bool(current_recording)}


def parse_import_paste(value: str) -> dict:
    """Return {links, posts, warnings}; no AI, networking, or side effects."""
    if not isinstance(value, str) or len(value) > MAX_PASTE:
        raise ValueError("Cole até 20 mil caracteres de links ou posts por lote.")
    posts, links, warnings = [], [], []
    current = None
    section = ""
    recording = ""
    awaiting_author = False
    comments = False

    def flush():
        nonlocal current
        if current is None:
            return
        content = "\n".join(current.pop("_content", []))
        activities = "\n".join(current.pop("_activities", []))[:6000]
        # Keep both Classroom sections in the same narrative description
        # (the Contexto + 20k cap); retain activities as a structured field.
        description = ("Conteúdo:\n" + content if content else "")
        if activities:
            description += ("\n" if description else "") + "Atividades:\n" + activities
        current["descricao"] = description[:20000]
        current["atividades"] = activities
        current["pessoas"] = (
            current["autor"] + " — autor do post do Classroom (não prova apresentação)"
            if current["autor"] else "")
        current["gravacoes"] = list(dict.fromkeys(current["gravacoes"]))[:30]
        posts.append(current)
        current = None

    for number, original in enumerate(value.splitlines(), 1):
        line = _clean(original)
        if not line:
            continue
        header = HEADER.fullmatch(line)
        if header:
            flush()
            lesson_number = int(header.group(1))
            if not 1 <= lesson_number <= 9999:
                warnings.append(f"Linha {number}: aula fora do intervalo permitido.")
                continue
            current = {"aula":f"Aula-{lesson_number:03d}",
                       "titulo":header.group(2).strip()[:220],
                       "autor":"", "data":"", "gravacoes":[],
                       "_content":[], "_activities":[]}
            section, recording, awaiting_author, comments = "", "", True, False
            continue
        if OMIT.fullmatch(line):
            if re.match(r"^Coment", line, re.I):
                comments = True
            continue
        if comments:
            continue
        if DATE_HEADER.fullmatch(line):
            continue  # Display timestamp; do not override Agenda or author.
        if current is not None and awaiting_author and AUTHOR.fullmatch(line):
            current["autor"] = line[:100]
            awaiting_author = False
            continue
        awaiting_author = False
        match = AGENDA.match(line)
        if match and current:
            try:
                datetime.strptime(match.group(1), "%d/%m/%Y")
                current["data"] = match.group(1)
            except ValueError:
                warnings.append(f"Linha {number}: data de agenda inválida.")
            continue
        heading = SECTION.match(line)
        if heading and current:
            section = "activities" if heading.group(1).casefold().startswith("ativ") else "content"
            if heading.group(2):
                current["_" + section].append(heading.group(2)[:1500])
            continue
        match = RECORDING.fullmatch(line)
        if match:
            target = f"Aula-{int(match.group(1)):03d}"
            if current and current["aula"] == target:
                recording = line[:160]
                current["gravacoes"].append(recording)
            elif current and current["aula"] != target:
                warnings.append(f"Linha {number}: gravação da {target} não pertence a {current['aula']}.")
            else:
                warnings.append(f"Linha {number}: gravação sem título de post para identificar contexto.")
            continue

        # Both literal URLs and "Aula 01 | V02 - Tema | URL" work.
        candidate = _url_row(line, current["aula"] if current else None, recording)
        if candidate:
            links.append(candidate)
            recording = ""
            continue
        if "http://" in line or "https://" in line:
            # Post text may embed an official link in a labeled sentence or
            # Markdown link. Extract ONLY our exact trusted docs host here.
            # Keep the surrounding text as Classroom data, never commands.
            found=[]
            for embedded in URL.findall(line)[:12]:
                embedded=embedded.rstrip(").,;]")
                if official_route(embedded) is None:
                    continue
                record=_url_row(embedded,current["aula"] if current else None,recording)
                if record and record["url"] not in [x["url"] for x in found]:
                    found.append(record)
            if found:
                links.extend(found)
                if current and section:
                    current["_"+section].append(line[:1500])
                continue
            warnings.append(f"Linha {number}: URL ou formato inválido; não foi importado.")
            continue
        if current and section:
            current["_" + section].append(line[:1500])
        else:
            warnings.append(f"Linha {number}: texto fora de um post/URL reconhecido: {line[:75]}")
    flush()
    if len(posts) > 50:
        raise ValueError("Máximo de 50 posts do Classroom por lote.")
    if len(links) > 80:
        raise ValueError("Máximo de 80 links por lote.")
    links = list({(row["url"], row["lesson"]):row for row in links}.values())
    return {"links":links, "posts":posts, "warnings":warnings[:100]}
