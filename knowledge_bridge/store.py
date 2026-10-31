"""Catálogo SQLite com filas e proveniência. Banco não é a fonte de verdade."""
from __future__ import annotations

import json
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
