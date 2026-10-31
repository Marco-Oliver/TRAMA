"""Registros explícitos do Classroom, sem depender de vídeo ou de IA.

O usuário decide o que registrar. Fontes e anotações são mantidas no vault,
com proveniência distinta de conteúdo extraído de transcrições.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

LESSON = re.compile(r"^(?:Aula[\s-]*)?0*(\d{1,4})$", re.I)


def lesson_number(value: str | int) -> str:
    m = LESSON.fullmatch(str(value).strip())
    if not m or not 1 <= int(m.group(1)) <= 9999:
        raise ValueError("Informe o número da aula (por exemplo, 1 ou 168).")
    return f"Aula-{int(m.group(1)):03d}"


def normalize_context(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Contexto da aula inválido.")
    lesson = lesson_number(data.get("aula", ""))
    # Texto é sempre dado não confiável. Nunca é interpretado como comando.
    def field(key: str, limit: int) -> str:
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"Campo {key} inválido ou muito longo.")
        return value.strip().replace("\x00", "")

    raw_links = field("links", 4000)
    links = []
    for row in raw_links.splitlines():
        link = row.strip()
        if not link:
            continue
        parts = urlsplit(link)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.username or parts.password:
            raise ValueError("Use somente links HTTP(S) completos, sem credenciais.")
        links.append(link)
    if len(links) > 30:
        raise ValueError("Máximo de 30 links por registro.")

    # Formato: "Título da gravação | https://..." ou apenas a URL.
    # Vídeos são REFERÊNCIAS. O TRAMA não baixa ou copia o arquivo de vídeo.
    video_rows = field("videos", 10000)
    videos = []
    used = set()
    for row in video_rows.splitlines():
        row = row.strip()
        if not row:
            continue
        if "|" in row:
            title, url = (x.strip() for x in row.rsplit("|", 1))
        else:
            title, url = "Gravação da aula", row
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.netloc or
                parts.username or parts.password or any(c.isspace() for c in url) or
                any(c in url for c in ("<", ">", "\\")) or len(url) > 1700):
            raise ValueError("Link do vídeo inválido; use uma URL HTTP(S) completa.")
        if not title or len(title) > 160 or any(c in title for c in "<>\x00"):
            raise ValueError("Título de vídeo inválido.")
        if url not in used:
            videos.append({"titulo": title, "url": url})
            used.add(url)
    if len(videos) > 30:
        raise ValueError("Máximo de 30 vídeos por aula.")
    day = field("data", 25)
    if day and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", day):
        raise ValueError("Data deve ser DD/MM/AAAA ou vazia.")
    if day:
        datetime.strptime(day, "%d/%m/%Y")
    return {
        "aula": lesson,
        "titulo": field("titulo", 220),
        "data": day,
        "descricao": field("descricao", 20000),
        "pessoas": field("pessoas", 4500),
        "atividades": field("atividades", 6000),
        "links": links,
        "videos": videos,
        "origem": "Informações cadastradas pelo usuário a partir do Classroom; não verificadas automaticamente",
    }


def save_classroom_record(vault: Path, data: dict) -> tuple[str, str, str]:
    """Salva contexto sem apagar o anterior: revisões são arquivadas antes de substituir."""
    payload = normalize_context(data)
    folder = vault / "99-Anexos" / "Contexto-Classroom"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{payload['aula']}.json"
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    if path.exists() and path.read_bytes() != content:
        existing = path.read_bytes()
        old = hashlib.sha256(existing).hexdigest()
        archive = folder / "Historico"
        archive.mkdir(exist_ok=True)
        old_copy = archive / f"{payload['aula']}-{old[:16]}.json"
        if not old_copy.exists():
            old_copy.write_bytes(existing)
    if not path.exists() or path.read_bytes() != content:
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".classroom-")
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(content)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return path.relative_to(vault).as_posix(), digest, payload["aula"]
