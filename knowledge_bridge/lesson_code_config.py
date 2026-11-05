"""Cadastro explícito GitHub por aula. Não guarda credenciais nem resolve refs."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import urlsplit

CONFIG_REL = Path(".base-conhecimento") / "aulas-github.json"
MAX_CONFIG_BYTES = 2_000_000
LESSON_RE = re.compile(r"^Aula-(?:\d{3}|\d{4})$")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,59}$")
REPO_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?$")
REF_RE = re.compile(r"^[A-Za-z0-9_./-]{1,180}$")
ALLOWED_REF = {"branch", "tag", "commit"}
REPO_FIELDS = {"id", "rotulo", "repo", "ref_tipo", "ref", "pasta", "anterior", "professor_id"}
REF_FIELDS = {"ref_tipo", "ref", "pasta"}


def _safe_repo(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 300 or not REPO_RE.fullmatch(value):
        return False
    parts = urlsplit(value).path.strip("/").split("/")
    return len(parts) == 2 and all(x not in (".", "..") for x in parts)


def _safe_path(value: object) -> bool:
    return (isinstance(value, str) and len(value) <= 300 and
            (value == '' or all(x not in ('', '.', '..') for x in value.split('/'))) and
            not value.startswith("/") and not "\\" in value and
            not any(ord(x) < 32 or ord(x) == 127 for x in value))


def _ref_errors(item: dict, prefix: str) -> list[str]:
    errors = []
    kind = item.get("ref_tipo")
    ref = item.get("ref")
    if kind not in ALLOWED_REF:
        errors.append(f"{prefix}.ref_tipo: escolha branch, tag ou commit")
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref) or ".." in ref or ref.startswith(("-", "/")):
        errors.append(f"{prefix}.ref: referência inválida ou ausente")
    elif kind == "commit" and not re.fullmatch(r"[a-fA-F0-9]{40}", ref):
        errors.append(f"{prefix}.ref: commit deve ser um SHA completo de 40 caracteres")
    if not _safe_path(item.get("pasta", "")):
        errors.append(f"{prefix}.pasta: use caminho relativo seguro, como V3 ou src")
    return errors


def validate_lesson(lesson: str, data: object) -> list[str]:
    errors = []
    if not isinstance(lesson, str) or not LESSON_RE.fullmatch(lesson) or not 1 <= int(lesson[5:]) <= 9999:
        return [f"{lesson!s}: identificador de aula inválido (ex.: Aula-131)"]
    if not isinstance(data, dict):
        return [f"{lesson}: registro deve ser um objeto"]
    if set(data) - {"professor", "dupla"}:
        errors.append(f"{lesson}: campos desconhecidos: {', '.join(sorted(set(data) - {'professor', 'dupla'}))}")
    ids = set()
    teachers = set()
    for role in ("professor", "dupla"):
        rows = data.get(role, [])
        if not isinstance(rows, list) or len(rows) > 12:
            errors.append(f"{lesson}.{role}: informe lista com no máximo 12 repositórios")
            continue
        for n, item in enumerate(rows):
            prefix = f"{lesson}.{role}[{n}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix}: repositório deve ser um objeto")
                continue
            if set(item) - REPO_FIELDS:
                errors.append(f"{prefix}: campos desconhecidos: {', '.join(sorted(set(item) - REPO_FIELDS))}")
            ident = item.get("id")
            if not isinstance(ident, str) or not ID_RE.fullmatch(ident):
                errors.append(f"{prefix}.id: use letras minúsculas, números e hífens")
            elif (role, ident) in ids:
                errors.append(f"{prefix}.id: identificador duplicado")
            else:
                ids.add((role, ident))
                if role == "professor":
                    teachers.add(ident)
            if not isinstance(item.get("rotulo"), str) or not 1 <= len(item["rotulo"].strip()) <= 100:
                errors.append(f"{prefix}.rotulo: obrigatório (até 100 caracteres)")
            if not _safe_repo(item.get("repo")):
                errors.append(f"{prefix}.repo: URL HTTPS de repositório github.com inválida (sem credenciais)")
            errors.extend(_ref_errors(item, prefix))
            if role == "professor":
                if "professor_id" in item:
                    errors.append(f"{prefix}.professor_id: campo permitido apenas na dupla")
                if "anterior" in item:
                    prev = item["anterior"]
                    if not isinstance(prev, dict) or set(prev) - REF_FIELDS:
                        errors.append(f"{prefix}.anterior: esperado objeto com ref_tipo, ref e pasta")
                    else:
                        errors.extend(_ref_errors(prev, prefix + ".anterior"))
            else:
                if "anterior" in item:
                    errors.append(f"{prefix}.anterior: campo reservado ao professor")
                if not isinstance(item.get("professor_id"), str):
                    errors.append(f"{prefix}.professor_id: obrigatório")
    for n, row in enumerate(data.get("dupla", []) if isinstance(data.get("dupla", []), list) else []):
        if isinstance(row, dict) and isinstance(row.get("professor_id"), str) and row["professor_id"] not in teachers:
            errors.append(f"{lesson}.dupla[{n}].professor_id: professor não encontrado: {row['professor_id']}")
    return errors


def _config_path(vault: Path) -> Path:
    vault = Path(vault).expanduser().resolve()
    return vault / CONFIG_REL


def read_config(vault: Path) -> dict:
    """Erros de uma aula não impedem carregar as outras; documento cru é preservado."""
    path = _config_path(vault)
    empty = {"schema": 1, "aulas": {}}
    if not path.exists():
        return {"document": empty, "aulas": {}, "erros": [], "fatal": False}
    try:
        if path.is_symlink() or path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError("arquivo simbólico ou acima de 2 MB")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema") != 1 or not isinstance(raw.get("aulas"), dict):
            raise ValueError("esperado objeto com schema=1 e aulas={}")
        if len(raw["aulas"]) > 9999:
            raise ValueError("quantidade de aulas excedida")
        if set(raw) - {"schema", "aulas"}:
            raise ValueError("campos desconhecidos na raiz")
    except (OSError, ValueError, UnicodeError) as exc:
        return {"document": None, "aulas": {}, "erros": [f"aulas-github.json: {exc}"],
                "fatal": True}
    good = {}
    errors = []
    for lesson, data in raw["aulas"].items():
        issues = validate_lesson(lesson, data)
        if issues:
            errors.extend(issues[:40])
        else:
            good[lesson] = data
    return {"document": raw, "aulas": good, "erros": errors[:500], "fatal": False}


def save_lessons(vault: Path, updates: dict) -> dict:
    """Mescla edições validadas sem apagar aulas inválidas ou não relacionadas."""
    if not isinstance(updates, dict) or not updates or len(updates) > 500:
        raise ValueError("Selecione de 1 a 500 aulas para salvar")
    issues = []
    for name, payload in updates.items():
        issues.extend(validate_lesson(name, payload))
    if issues:
        raise ValueError("; ".join(issues[:10]))
    current = read_config(vault)
    if current["fatal"]:
        raise ValueError("Corrija o aulas-github.json antes de salvar: " + "; ".join(current["erros"]))
    doc = current["document"]
    doc["aulas"].update(updates)
    content = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(content) > MAX_CONFIG_BYTES:
        raise ValueError("O cadastro excederia 2 MB")
    path = _config_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ValueError("Arquivo de configuração simbólico não permitido")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".aulas-github-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"ok": True, "saved": sorted(updates), "erros": current["erros"]}


def lesson_dates(vault: Path) -> list[dict]:
    """Dados explícitos do Classroom são indícios; NÃO comprovam data da gravação."""
    vault = Path(vault).resolve()
    names = set()
    db = vault / ".base-conhecimento" / "estado.sqlite3"
    if db.is_file():
        try:
            with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as conn:
                names.update(row[0] for row in conn.execute(
                    "SELECT DISTINCT lesson FROM sources WHERE lesson IS NOT NULL"))
        except sqlite3.Error:
            pass
    classdir = vault / "99-Anexos" / "Contexto-Classroom"
    result = []
    for lesson in sorted(n for n in names if isinstance(n, str) and LESSON_RE.fullmatch(n)):
        date = ""
        if not classdir.is_symlink():
            file = classdir / (lesson + ".json")
            try:
                if file.is_file() and not file.is_symlink() and file.stat().st_size < 100_000:
                    raw = json.loads(file.read_text(encoding="utf-8"))
                    date_br = raw.get("data", "")
                    date = datetime.strptime(date_br, "%d/%m/%Y").date().isoformat() if date_br else ""
            except (ValueError, OSError, UnicodeError, TypeError, AttributeError):
                pass
        result.append({"aula": lesson, "data": date,
                       "origem_data": "contexto_classroom" if date else "nao_informada"})
    return result
