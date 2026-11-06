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
 private INTEGER CHECK(private IN (0,1)),
 origem TEXT NOT NULL DEFAULT 'manual',
 confianca TEXT NOT NULL DEFAULT 'alta',
 frozen_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(lesson, role, repository_id, slot)
);
CREATE TABLE IF NOT EXISTS github_auto_repositories (
 repo_url TEXT PRIMARY KEY, role TEXT NOT NULL, private INTEGER,
 status TEXT NOT NULL, versions_json TEXT NOT NULL DEFAULT '[]',
 message TEXT NOT NULL DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS github_auto_decisions (
 repo_url TEXT NOT NULL, lesson TEXT NOT NULL,
 version_sha TEXT NOT NULL DEFAULT '', confianca TEXT NOT NULL DEFAULT '',
 decision TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(repo_url, lesson)
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
        # Existing vaults retain their frozen SHAs; unknown historical privacy
        # remains NULL until verified, never guessed to be public.
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(github_lesson_refs)")}
        if "private" not in columns:
            self.conn.execute("ALTER TABLE github_lesson_refs ADD COLUMN private INTEGER CHECK(private IN (0,1))")
        if "origem" not in columns:
            self.conn.execute("ALTER TABLE github_lesson_refs ADD COLUMN origem TEXT NOT NULL DEFAULT 'manual'")
        if "confianca" not in columns:
            self.conn.execute("ALTER TABLE github_lesson_refs ADD COLUMN confianca TEXT NOT NULL DEFAULT 'alta'")
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

    def github_lesson_refs(self, lesson: str, config=None):
        """Validated immutable current SHAs; optionally reuse one config per publication."""
        if config is None:
            from .lesson_code_config import read_config
            config=read_config(self.vault)
        if config["fatal"]:
            return -1, []
        if lesson in config.get("invalid", {}):
            return -1, []  # Never expose stale code when this lesson's JSON is corrupt.
        record=config["aulas"].get(lesson)
        if not record:
            # Automatic registrations live in SQLite; manual JSON remains
            # optional, advanced and authoritative when it exists.
            automatic = [dict(row) for row in self.conn.execute(
                "SELECT * FROM github_lesson_refs WHERE lesson=? AND origem='automatica' AND slot='current' ORDER BY repo_url",
                (lesson,)).fetchall()]
            return len(automatic), automatic
        locked=[]
        total=0
        for role in ("professor","dupla"):
            for entry in record.get(role,[]):
                total+=1
                row=self.github_ref(lesson,role,entry["id"],"current")
                if not row:
                    continue
                expected=(entry["repo"],entry["ref_tipo"],entry["ref"],entry.get("pasta",""))
                stored=tuple(row[key] for key in ("repo_url","ref_kind","ref_name","folder"))
                if stored==expected:
                    locked.append(row)
        return total,locked

    def github_lesson_repo_allowed(self, lesson: str, repo_url: str, sha: str) -> bool:
        """Never attach a moving branch to an explicitly mapped lesson."""
        if not isinstance(repo_url,str) or not repo_url.startswith("https://github.com/"):
            return True  # local repository indexing is a separate legacy workflow
        total,locked=self.github_lesson_refs(lesson)
        if total<0:
            return False
        if not total:
            return True  # No registration: preserve the original global HEAD index.
        if not isinstance(sha,str):
            return False
        normal=lambda url: url.rstrip("/").removesuffix(".git").casefold()
        return any(normal(row["repo_url"])==normal(repo_url) and
                   row["commit_sha"]==sha.lower() for row in locked)

    def freeze_github_ref(self, lesson: str, role: str, repository_id: str, slot: str,
                          repo_url: str, ref_kind: str, ref_name: str,
                          folder: str, commit_sha: str, private=None):
        """First frozen SHA wins; never overwrite on reprocess or moving branches."""
        if private is not None and type(private) is not bool:
            raise ValueError("Visibilidade do repositório GitHub inválida.")
        if (role not in ("professor", "dupla") or slot not in ("current", "previous")
                or not re.fullmatch(r"Aula-\d{3,4}", lesson or "")
                or not re.fullmatch(r"[a-fA-F0-9]{40}", commit_sha or "")):
            raise ValueError("Identificador ou SHA de congelamento inválido.")
        expected = (repo_url, ref_kind, ref_name, folder)
        old = self.github_ref(lesson, role, repository_id, slot)
        if old:
            if tuple(old[key] for key in ("repo_url","ref_kind","ref_name","folder")) != expected:
                raise ValueError("Referência já congelada para este cadastro; alteração exige revisão explícita.")
            if old["private"] is None and private is not None:
                with self.conn:
                    self.conn.execute(
                        "UPDATE github_lesson_refs SET private=? WHERE lesson=? AND role=? AND repository_id=? AND slot=? AND private IS NULL",
                        (int(private),lesson,role,repository_id,slot))
            return {"sha": old["commit_sha"], "created": False, "private": private if old["private"] is None else bool(old["private"])}
        with self.conn:
            self.conn.execute("""INSERT OR IGNORE INTO github_lesson_refs
                (lesson,role,repository_id,slot,repo_url,ref_kind,ref_name,folder,commit_sha,private)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (lesson,role,repository_id,slot,repo_url,ref_kind,ref_name,folder,commit_sha.lower(),
                 int(private) if private is not None else None))
        saved = self.github_ref(lesson, role, repository_id, slot)
        if (not saved or tuple(saved[key] for key in ("repo_url","ref_kind","ref_name","folder")) != expected
                or saved["commit_sha"] != commit_sha.lower()):
            raise ValueError("Referência congelada por outro processo; nenhuma atualização automática aplicada.")
        return {"sha":saved["commit_sha"],"created":True,
                "private":None if saved["private"] is None else bool(saved["private"])}

    def unfreeze_github_ref(self, lesson: str, role: str, repository_id: str, slot: str):
        """Explicitly clear one slot; it can subsequently be frozen again."""
        if (not isinstance(lesson, str) or not re.fullmatch(r"Aula-\d{3,4}", lesson)
                or role not in ("professor", "dupla")
                or slot not in ("current", "previous")
                or not isinstance(repository_id, str) or not repository_id):
            raise ValueError("Aula, repositório ou versão inválida.")
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM github_lesson_refs WHERE lesson=? AND role=? AND repository_id=? AND slot=?",
                (lesson, role, repository_id, slot))
        return cursor.rowcount == 1

    def clear_github_lesson(self, lesson: str):
        with self.conn:
            self.conn.execute("DELETE FROM github_lesson_refs WHERE lesson=?", (lesson,))


    def auto_repositories(self):
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM github_auto_repositories ORDER BY repo_url").fetchall()]

    def save_auto_repository(self, repo_url, role, private, status, versions=None, message=""):
        if role not in ("professor", "dupla") or type(private) is not bool:
            raise ValueError("Repositório automático inválido.")
        # On rate limit, preserve last usable version catalogue.
        previous = self.conn.execute(
            "SELECT versions_json FROM github_auto_repositories WHERE repo_url=?", (repo_url,)).fetchone()
        stored = json.dumps(versions,ensure_ascii=False) if versions is not None else (
            previous["versions_json"] if previous else "[]")
        with self.conn:
            self.conn.execute("""INSERT INTO github_auto_repositories
              (repo_url,role,private,status,versions_json,message)
              VALUES(?,?,?,?,?,?) ON CONFLICT(repo_url) DO UPDATE SET
              role=excluded.role,private=excluded.private,status=excluded.status,
              versions_json=excluded.versions_json,message=excluded.message,
              updated_at=CURRENT_TIMESTAMP""",
              (repo_url,role,int(private),status,stored,str(message)[:500]))

    def automatic_decisions(self, repo_url):
        return {r["lesson"]:dict(r) for r in self.conn.execute(
            "SELECT * FROM github_auto_decisions WHERE repo_url=?", (repo_url,))}

    def set_auto_decision(self, repo_url, lesson, role, private, version, confidence,
                          recalculate=False):
        """Never alter a manual SHA. No-code decisions remain stable across runs."""
        from .lesson_code_config import read_config
        config = read_config(self.vault)
        if config["fatal"] or lesson in config.get("invalid",{}) or lesson in config["aulas"]:
            return False
        manual = self.conn.execute(
            "SELECT 1 FROM github_lesson_refs WHERE lesson=? AND origem!='automatica' LIMIT 1",
            (lesson,)).fetchone()
        if manual:
            return False
        existing = self.conn.execute(
            "SELECT 1 FROM github_auto_decisions WHERE repo_url=? AND lesson=?",
            (repo_url,lesson)).fetchone()
        if existing and not recalculate:
            return False
        ident = "auto-" + __import__("hashlib").sha256(repo_url.encode()).hexdigest()[:22]
        with self.conn:
            self.conn.execute(
                "DELETE FROM github_lesson_refs WHERE lesson=? AND repo_url=? AND origem='automatica'",
                (lesson,repo_url))
            sha = version["sha"] if version is not None else ""
            self.conn.execute("""INSERT INTO github_auto_decisions
               (repo_url,lesson,version_sha,confianca,decision)
               VALUES(?,?,?,?,?) ON CONFLICT(repo_url,lesson) DO UPDATE SET
               version_sha=excluded.version_sha,confianca=excluded.confianca,
               decision=excluded.decision,updated_at=CURRENT_TIMESTAMP""",
               (repo_url,lesson,sha,confidence,"version" if version else "none"))
            if version is not None:
                self.conn.execute("""INSERT INTO github_lesson_refs
                   (lesson,role,repository_id,slot,repo_url,ref_kind,ref_name,
                    folder,commit_sha,private,origem,confianca)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (lesson,role,ident,"current",repo_url,version["kind"],
                    version["name"],version.get("folder",""),sha,int(private),
                    "automatica",confidence))
        return True

    def clear_auto_decisions(self, repo_url):
        """Explicit recalculation: only automatic decisions and locks."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM github_lesson_refs WHERE repo_url=? AND origem='automatica'",(repo_url,))
            self.conn.execute(
                "DELETE FROM github_auto_decisions WHERE repo_url=?",(repo_url,))

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
