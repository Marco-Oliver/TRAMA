"""Keep per-lesson GitHub JSON registrations and frozen SQLite SHAs consistent.

SQLite invalidations run *inside* a transaction before replacing JSON. If the
JSON write fails, the frozen references roll back. If SQLite commit fails after
JSON replacement, the old JSON bytes are restored atomically before rollback.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .lesson_code_config import (_config_path, delete_lesson, read_config,
                                 save_lessons, validate_lesson)
from .store import Store


def _invalidations(db, updates: dict, original: dict) -> list[dict]:
    affected = []
    for lesson, values in updates.items():
        rows = db.conn.execute(
            "SELECT lesson,role,repository_id,slot,repo_url,ref_kind,ref_name,folder,commit_sha "
            "FROM github_lesson_refs WHERE lesson=? AND origem!='automatica' ORDER BY role,repository_id,slot",
            (lesson,)).fetchall()
        for row in rows:
            key = (row["role"], row["repository_id"], row["slot"])
            entries = values.get(row["role"], [])
            item = next((entry for entry in entries if entry["id"] == row["repository_id"]), None)
            spec = (item.get("anterior") if row["slot"] == "previous" else item) if item else None
            expected = ((item["repo"], spec["ref_tipo"], spec["ref"],
                         spec.get("pasta", "")) if spec else None)
            current = tuple(row[k] for k in ("repo_url", "ref_kind", "ref_name", "folder"))
            if lesson in original.get("invalid", {}) or expected != current:
                affected.append({"lesson": lesson, "role": key[0], "repository_id": key[1],
                                 "slot": key[2], "sha": row["commit_sha"]})
    return affected


def preview_invalidations(vault: Path, lesson: str, data: dict) -> list[dict]:
    issues = validate_lesson(lesson, data)
    if issues:
        raise ValueError("; ".join(issues[:8]))
    original = read_config(vault)
    if original["fatal"]:
        raise ValueError("Corrija aulas-github.json antes de alterar o cadastro.")
    db = Store(vault)
    try:
        return _invalidations(db, {lesson: data}, original)
    finally:
        db.close()


def _restore_original(path: Path, original: bytes | None):
    """Atomic best-effort rollback of the small local JSON document."""
    if original is None:
        path.unlink(missing_ok=True)
        return
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".aulas-github-restore-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _commit(conn):
    """Separate seam for testing the rare commit-after-JSON failure."""
    conn.commit()


def persist_codes(vault: Path, updates: dict | None = None, *,
                  removal: str | None = None, replacements: dict | None = None,
                  expected_digest: str = "", confirm_unfreeze: bool = False) -> dict:
    if (updates is None) == (removal is None):
        raise ValueError("Escolha salvar aulas ou remover um cadastro, não ambos.")
    original = read_config(vault)
    if original["fatal"]:
        raise ValueError("Corrija aulas-github.json antes de continuar.")
    if removal is not None and removal not in original["document"]["aulas"]:
        return {"ok": False, "message": "Esta aula não possui cadastro GitHub."}
    if updates is not None:
        issues = [problem for lesson, data in updates.items()
                  for problem in validate_lesson(lesson, data)]
        if issues:
            raise ValueError("; ".join(issues[:8]))
    path = _config_path(vault)
    old_bytes = path.read_bytes() if path.exists() else None
    db = Store(vault)
    try:
        db.conn.execute("BEGIN IMMEDIATE")
        if removal is not None:
            # Delete first, *uncommitted*, so JSON failure restores all SHAs.
            db.conn.execute("DELETE FROM github_lesson_refs WHERE lesson=?", (removal,))
            outcome = delete_lesson(vault, removal, expected_digest)
            affected = []
        else:
            affected = _invalidations(db, updates, original)
            if affected and confirm_unfreeze is not True:
                raise ValueError("A alteração remove SHAs congelados. Confirme o descongelamento antes de salvar.")
            for row in affected:
                db.conn.execute(
                    "DELETE FROM github_lesson_refs "
                    "WHERE lesson=? AND role=? AND repository_id=? AND slot=?",
                    (row["lesson"], row["role"], row["repository_id"], row["slot"]))
            # Manual JSON edits always supersede tentative automatic locks,
            # without asking users to confirm deletion of automatic guesses.
            for lesson in updates:
                db.conn.execute("DELETE FROM github_lesson_refs WHERE lesson=? AND origem='automatica'",(lesson,))
                db.conn.execute("DELETE FROM github_auto_decisions WHERE lesson=?",(lesson,))
            outcome = save_lessons(vault, updates, replacements=replacements)
        if not outcome.get("ok"):
            db.conn.rollback()
            return outcome
        _commit(db.conn)
        return {**outcome, "unfrozen": affected}
    except Exception:
        try:
            # Restore only if the JSON was modified. The original is captured
            # before starting the SQLite transaction.
            now = path.read_bytes() if path.exists() else None
            if now != old_bytes:
                _restore_original(path, old_bytes)
        finally:
            db.conn.rollback()
        raise
    finally:
        db.close()
