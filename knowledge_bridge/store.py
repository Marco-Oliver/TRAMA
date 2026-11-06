"""Catálogo SQLite com filas e proveniência. Banco não é a fonte de verdade."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, original_path TEXT NOT NULL, kind TEXT NOT NULL,
 digest TEXT NOT NULL, label TEXT NOT NULL, lesson TEXT, video TEXT,
 stored_path TEXT, status TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(original_path, kind)
);
CREATE TABLE IF NOT EXISTS analyses (
 source_id TEXT PRIMARY KEY, digest TEXT NOT NULL, provider TEXT NOT NULL,
 model TEXT NOT NULL, payload TEXT NOT NULL,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(source_id) REFERENCES sources(id)
);
CREATE TABLE IF NOT EXISTS chunks (
 source_id TEXT NOT NULL, digest TEXT NOT NULL, segment INTEGER NOT NULL,
 provider TEXT NOT NULL, model TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(source_id,digest,segment)
);
CREATE TABLE IF NOT EXISTS connections (
 source_id TEXT NOT NULL, source_digest TEXT NOT NULL,
 repo_url TEXT NOT NULL, repo_sha TEXT NOT NULL,
 provider TEXT NOT NULL, model TEXT NOT NULL, payload TEXT NOT NULL,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(source_id,repo_url)
);
CREATE TABLE IF NOT EXISTS writes (
 relative_path TEXT PRIMARY KEY, digest TEXT NOT NULL,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS repositories (
 url TEXT PRIMARY KEY, name TEXT NOT NULL, sha TEXT NOT NULL,
 payload TEXT NOT NULL, status TEXT NOT NULL,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS uncertainties (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_digest TEXT NOT NULL,
 label TEXT NOT NULL, question TEXT NOT NULL, candidate TEXT NOT NULL,
 status TEXT NOT NULL, evidence_digest TEXT NOT NULL, evidence_json TEXT NOT NULL,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(source_id) REFERENCES sources(id)
);
CREATE TABLE IF NOT EXISTS uncertainty_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, uncertainty_id TEXT NOT NULL,
 status TEXT NOT NULL, evidence_digest TEXT NOT NULL,
 source_digest TEXT NOT NULL, candidate TEXT NOT NULL, evidence_json TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(uncertainty_id) REFERENCES uncertainties(id)
);
-- Deterministic local term evidence for a verified transcript digest.
-- It avoids reparsing earlier lessons when only a new lesson arrives.
CREATE TABLE IF NOT EXISTS review_source_index (
 source_id TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS github_lesson_refs (
 lesson TEXT NOT NULL, role TEXT NOT NULL, repository_id TEXT NOT NULL,
 slot TEXT NOT NULL, repo_url TEXT NOT NULL, ref_kind TEXT NOT NULL,
 ref_name TEXT NOT NULL, folder TEXT NOT NULL, commit_sha TEXT NOT NULL,
 frozen_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(lesson, role, repository_id, slot)
);
CREATE INDEX IF NOT EXISTS idx_uncertainties_source ON uncertainties(source_id);
CREATE INDEX IF NOT EXISTS idx_uncertainty_events_lookup ON uncertainty_events(uncertainty_id, id);
"""

class Store:
    def __init__(self, vault: Path):
        self.vault = vault.resolve()
        self.vault.mkdir(parents=True, exist_ok=True)
        system = self.vault / ".base-conhecimento"
        system.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(system / "estado.sqlite3")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def upsert_source(self, record: dict):
        old = self.get_source(record["id"])
        changed = not old or old["digest"] != record["digest"]
        status = ("READY" if record["kind"] == "transcript" else "STORED") if changed else old["status"]
        self.conn.execute("""INSERT INTO sources (id,original_path,kind,digest,label,lesson,video,stored_path,status)
          VALUES (:id,:original_path,:kind,:digest,:label,:lesson,:video,:stored_path,:status)
          ON CONFLICT(id) DO UPDATE SET digest=excluded.digest,label=excluded.label,
          lesson=excluded.lesson,video=excluded.video,stored_path=excluded.stored_path,
          status=excluded.status,updated_at=CURRENT_TIMESTAMP""", {**record, "status": status})
        self.conn.commit()
        return changed

    def get_source(self, source_id: str):
        return self.conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()

    def matching_digest(self, kind: str, digest: str):
        return self.conn.execute("SELECT * FROM sources WHERE kind=? AND digest=?", (kind,digest)).fetchone()

    def sources(self, kind=None):
        if kind:
            return self.conn.execute("SELECT * FROM sources WHERE kind=? ORDER BY label", (kind,)).fetchall()
        return self.conn.execute("SELECT * FROM sources ORDER BY kind,label").fetchall()

    def update_status(self, source_id: str, status: str):
        self.conn.execute("UPDATE sources SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, source_id))
        self.conn.commit()

    def analysis(self, source_id: str, expected_digest: str | None = None):
        row = self.conn.execute("SELECT * FROM analyses WHERE source_id=?", (source_id,)).fetchone()
        if row and expected_digest and row["digest"] != expected_digest:
            return None
        return json.loads(row["payload"]) if row else None

    def save_analysis(self, source_id: str, digest: str, provider: str, model: str, result: dict):
        self.conn.execute("""INSERT INTO analyses(source_id,digest,provider,model,payload)
        VALUES(?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET digest=excluded.digest,
        provider=excluded.provider,model=excluded.model,payload=excluded.payload,updated_at=CURRENT_TIMESTAMP""",
                          (source_id,digest,provider,model,json.dumps(result,ensure_ascii=False)))
        self.conn.commit()

    def get_chunk(self, source_id: str, digest: str, segment: int):
        row = self.conn.execute("SELECT payload FROM chunks WHERE source_id=? AND digest=? AND segment=?",
                                (source_id,digest,segment)).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_chunk(self, source_id: str, digest: str, segment: int, provider: str, model: str, result: dict):
        self.conn.execute("""INSERT OR REPLACE INTO chunks(source_id,digest,segment,provider,model,payload)
        VALUES(?,?,?,?,?,?)""",(source_id,digest,segment,provider,model,json.dumps(result,ensure_ascii=False)))
        self.conn.commit()

    def connection(self, source_id: str, source_digest: str, repo_url: str, repo_sha: str):
        row=self.conn.execute("SELECT payload FROM connections WHERE source_id=? AND source_digest=? AND repo_url=? AND repo_sha=?",
                              (source_id,source_digest,repo_url,repo_sha)).fetchone()
        return json.loads(row["payload"]) if row else None

    def save_connection(self, source_id: str, source_digest: str, repo_url: str, repo_sha: str,
                        provider: str, model: str, result: dict):
        self.conn.execute("""INSERT INTO connections(source_id,source_digest,repo_url,repo_sha,provider,model,payload)
             VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,repo_url) DO UPDATE SET
             source_digest=excluded.source_digest,repo_sha=excluded.repo_sha,
             provider=excluded.provider,model=excluded.model,payload=excluded.payload,
             updated_at=CURRENT_TIMESTAMP""",
             (source_id,source_digest,repo_url,repo_sha,provider,model,json.dumps(result,ensure_ascii=False)))
        self.conn.commit()

    def last_write_hash(self, relative: str):
        row = self.conn.execute("SELECT digest FROM writes WHERE relative_path=?",(relative,)).fetchone()
        return row["digest"] if row else None

    def register_write(self, relative: str, digest: str):
        self.conn.execute("""INSERT INTO writes(relative_path,digest) VALUES (?,?)
             ON CONFLICT(relative_path) DO UPDATE SET digest=excluded.digest,updated_at=CURRENT_TIMESTAMP""",(relative,digest))
        self.conn.commit()

    def save_repo(self, url: str, name: str, sha: str, payload: dict, status: str):
        self.conn.execute("""INSERT INTO repositories(url,name,sha,payload,status) VALUES(?,?,?,?,?)
          ON CONFLICT(url) DO UPDATE SET name=excluded.name,sha=excluded.sha,
          payload=excluded.payload,status=excluded.status,updated_at=CURRENT_TIMESTAMP""",
          (url,name,sha,json.dumps(payload,ensure_ascii=False),status))
        self.conn.commit()

    def repositories(self):
        return self.conn.execute("SELECT * FROM repositories ORDER BY name").fetchall()

    def github_ref(self, lesson: str, role: str, repository_id: str, slot="current"):
        row = self.conn.execute(
            "SELECT * FROM github_lesson_refs WHERE lesson=? AND role=? AND repository_id=? AND slot=?",
            (lesson, role, repository_id, slot)).fetchone()
        return dict(row) if row else None

    def freeze_github_ref(self, lesson: str, role: str, repository_id: str, slot: str,
                          repo_url: str, ref_kind: str, ref_name: str,
                          folder: str, commit_sha: str):
        """First frozen SHA wins; never overwrite on reprocess or moving branches."""
        if (role not in ("professor", "dupla") or slot not in ("current", "previous")
                or not re.fullmatch(r"Aula-\\d{3,4}", lesson or "")
                or not re.fullmatch(r"[a-fA-F0-9]{40}", commit_sha or "")):
            raise ValueError("Identificador ou SHA de congelamento inválido.")
        expected = (repo_url, ref_kind, ref_name, folder)
        old = self.github_ref(lesson, role, repository_id, slot)
        if old:
            if tuple(old[key] for key in ("repo_url","ref_kind","ref_name","folder")) != expected:
                raise ValueError("Referência já congelada para este cadastro; alteração exige revisão explícita.")
            return {"sha": old["commit_sha"], "created": False}
        with self.conn:
            self.conn.execute("""INSERT OR IGNORE INTO github_lesson_refs
                (lesson,role,repository_id,slot,repo_url,ref_kind,ref_name,folder,commit_sha)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (lesson,role,repository_id,slot,repo_url,ref_kind,ref_name,folder,commit_sha.lower()))
        saved = self.github_ref(lesson, role, repository_id, slot)
        if (not saved or tuple(saved[key] for key in ("repo_url","ref_kind","ref_name","folder")) != expected
                or saved["commit_sha"] != commit_sha.lower()):
            raise ValueError("Referência congelada por outro processo; nenhuma atualização automática aplicada.")
        return {"sha":saved["commit_sha"],"created":True}

    def clear_github_lesson(self, lesson: str):
        with self.conn:
            self.conn.execute("DELETE FROM github_lesson_refs WHERE lesson=?", (lesson,))

    def uncertainties(self):
        return self.conn.execute(
            "SELECT * FROM uncertainties ORDER BY source_id, id").fetchall()

    def uncertainties_for_source(self, source_id: str):
        """Return only open/reviewable questions for this original transcript."""
        return self.conn.execute(
            "SELECT * FROM uncertainties WHERE source_id=? "
            "AND status != 'ARQUIVADA_FONTE_ALTERADA' ORDER BY id",
            (source_id,)
        ).fetchall()

    def review_source_index(self, source_id: str, digest: str):
        row=self.conn.execute(
            "SELECT payload FROM review_source_index WHERE source_id=? AND digest=?",
            (source_id,digest)
        ).fetchone()
        if row is None:
            return None
        try:
            data=json.loads(row["payload"])
        except (TypeError,ValueError):
            return None
        return data if isinstance(data,dict) else None

    def save_review_source_index(self, source_id: str, digest: str, payload: dict):
        with self.conn:
            self.conn.execute("""
                INSERT INTO review_source_index(source_id,digest,payload)
                VALUES(?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET digest=excluded.digest,
                  payload=excluded.payload,updated_at=CURRENT_TIMESTAMP
            """,(source_id,digest,json.dumps(payload,ensure_ascii=False,sort_keys=True)))

    def uncertainty_events(self, uncertainty_id: str):
        return self.conn.execute(
            "SELECT * FROM uncertainty_events WHERE uncertainty_id=? ORDER BY id",
            (uncertainty_id,)).fetchall()

    def upsert_uncertainty(self, uid: str, source_id: str, source_digest: str,
                           label: str, question: str, candidate: str,
                           status: str, evidence: list[dict]) -> bool:
        """Append a revision only when evidence/source/state genuinely changed."""
        serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        import hashlib
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        existing = self.conn.execute("SELECT * FROM uncertainties WHERE id=?", (uid,)).fetchone()
        if (existing and existing["source_digest"] == source_digest and
                existing["status"] == status and existing["candidate"] == candidate and
                existing["evidence_digest"] == digest):
            return False
        with self.conn:
            self.conn.execute("""INSERT INTO uncertainties
                (id, source_id, source_digest, label, question, candidate,
                 status, evidence_digest, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                 source_digest=excluded.source_digest, label=excluded.label,
                 question=excluded.question, candidate=excluded.candidate,
                 status=excluded.status, evidence_digest=excluded.evidence_digest,
                 evidence_json=excluded.evidence_json, updated_at=CURRENT_TIMESTAMP""",
                (uid, source_id, source_digest, label, question, candidate,
                 status, digest, serialized))
            self.conn.execute("""INSERT INTO uncertainty_events
                (uncertainty_id, status, evidence_digest, source_digest,
                 candidate, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (uid, status, digest, source_digest, candidate, serialized))
        return True
