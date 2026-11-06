"""Backup local verificável e restauração não destrutiva do cofre Obsidian.

Não faz upload, não executa código importado e não sobrescreve um cofre.
O backup é um ZIP local NÃO criptografado; deve ser armazenado com cuidado.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath

MAX_FILES = 60000
MAX_BYTES = 12 * 1024**3
DB_FILE = ".base-conhecimento/estado.sqlite3"
MANIFEST = "TRAMA-BACKUP-MANIFEST.json"

# Windows treats some names as devices or aliases. Never restore these from a
# ZIP even on Linux, since the backup may later be restored to Windows.
_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
}


def _safe_archive_name(name: str) -> bool:
    if not isinstance(name,str) or not name or len(name)>900:
        return False
    if any(ord(char)<32 or ord(char)==127 for char in name):
        return False
    pure=PurePosixPath(name)
    if (pure.is_absolute() or ".." in pure.parts or "\\" in name or
            ":" in name or not pure.parts or
            any(part in ("", ".") for part in pure.parts)):
        return False
    for part in pure.parts:
        if (part.rstrip(" .") != part or len(part)>240 or
                part.split(".",1)[0].upper() in _WINDOWS_DEVICES):
            return False
    return True


def _filesystem_path(path: Path) -> Path:
    """Use Windows extended-length paths for verified local files.

    Deep GitHub checkouts can exceed MAX_PATH even when the Obsidian vault
    itself is in Documents. This helper is only for OS filesystem operations;
    ZIP entry names must remain portable POSIX paths and pass validation.
    """
    path = Path(path)
    if os.name != "nt":
        return path
    absolute = str(path.resolve())
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute.lstrip("\\"))
    return Path("\\\\?\\" + absolute)


def _hash_stream(stream):
    digest = hashlib.sha256()
    total = 0
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
        total += len(block)
    return digest.hexdigest(), total


def create_backup(vault: Path, destination: Path) -> dict:
    """Create an atomic snapshot ZIP, never overwriting the destination."""
    vault = Path(vault).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if not vault.is_dir() or not (vault / DB_FILE).is_file():
        raise ValueError("Cofre TRAMA ainda não foi inicializado.")
    if destination.suffix.lower() != ".zip" or destination.is_relative_to(vault):
        raise ValueError("Backup deve ser ZIP fora da pasta do Obsidian.")
    if destination.exists():
        raise FileExistsError("Este arquivo de backup já existe; escolha outro nome.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = []
    total = 0
    filesystem_vault = _filesystem_path(vault)
    for file in sorted(filesystem_vault.rglob("*")):
        if file.is_symlink():
            raise ValueError("Backup não aceita links simbólicos: " + file.name)
        if not file.is_file():
            continue
        rel = file.relative_to(filesystem_vault).as_posix()
        if rel == MANIFEST:
            raise ValueError("Renomeie o manifesto reservado antes de criar backup.")
        if rel == DB_FILE or rel in (DB_FILE + "-wal", DB_FILE + "-shm"):
            continue
        size = file.stat().st_size
        total += size
        if len(files) >= MAX_FILES or total > MAX_BYTES:
            raise ValueError("Cofre excede os limites de backup seguro.")
        files.append((rel, file))
    # Consistent SQLite snapshot even if the source uses WAL.
    with tempfile.TemporaryDirectory(prefix=".trama-db-backup-") as folder:
        db_snapshot = Path(folder) / "estado.sqlite3"
        with closing(sqlite3.connect(f"file:{(vault / DB_FILE).as_posix()}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(db_snapshot)) as target:
                source.backup(target)
        files.append((DB_FILE, db_snapshot))
        fd, temp = tempfile.mkstemp(prefix=".trama-backup-", suffix=".part", dir=str(destination.parent))
        os.close(fd)
        try:
            entries = {}
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=5, allowZip64=True) as archive:
                for rel, original in files:
                    # ZipInfo uses portable / separators on Windows and Linux.
                    # Stream bytes once directly into the ZIP and hash them.
                    info = zipfile.ZipInfo(rel)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o600 << 16
                    sha256 = hashlib.sha256()
                    size = 0
                    with original.open("rb") as inp, archive.open(info, "w") as out:
                        for block in iter(lambda: inp.read(1024 * 1024), b""):
                            sha256.update(block)
                            size += len(block)
                            out.write(block)
                    sha = sha256.hexdigest()
                    # Reject files that changed during creation.
                    with original.open("rb") as current:
                        after, current_size = _hash_stream(current)
                    if (sha, size) != (after, current_size):
                        raise ValueError("Um arquivo mudou durante o backup: " + rel)
                    entries[rel] = {"sha256": sha, "size": size}
                archive.writestr(MANIFEST, json.dumps(
                    {"format": 1, "files": entries}, ensure_ascii=False, sort_keys=True))
            with zipfile.ZipFile(temp) as archive:
                if archive.testzip() is not None:
                    raise ValueError("Falha na verificação de integridade do ZIP.")
            # Never silently replace a previous backup.
            if destination.exists():
                raise FileExistsError("Destino passou a existir durante o backup.")
            # Atomic, no-clobber publication: hardlink fails if name exists.
            # Both files are on the same filesystem (destination.parent).
            os.link(temp, destination)
            return {"ok": True, "path": str(destination), "files": len(entries),
                    "bytes": sum(x["size"] for x in entries.values())}
        finally:
            if os.path.exists(temp):
                os.unlink(temp)


def restore_backup(archive_path: Path, destination_vault: Path) -> dict:
    """Restore only to a new, nonexistent destination, verified before publish."""
    archive_path = Path(archive_path).expanduser().resolve()
    destination_vault = Path(destination_vault).expanduser().resolve()
    if not archive_path.is_file() or destination_vault.exists():
        raise ValueError("Informe um ZIP existente e uma pasta de cofre NOVA.")
    if destination_vault.is_relative_to(archive_path.parent) and destination_vault == archive_path.parent:
        raise ValueError("Pasta de destino inválida.")
    _filesystem_path(destination_vault.parent).mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".trama-restore-", dir=str(destination_vault.parent)))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if (len(names) != len(set(names)) or
                    len(names) != len({n.casefold() for n in names}) or
                    MANIFEST not in names):
                raise ValueError("Manifesto ausente ou nomes duplicados no ZIP.")
            if archive.getinfo(MANIFEST).file_size > 16 * 1024 * 1024:
                raise ValueError("Manifesto excede tamanho máximo permitido.")
            manifest = json.loads(archive.read(MANIFEST))
            if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
                raise ValueError("Formato de backup incompatível.")
            entries = manifest["files"]
            if DB_FILE not in entries or len(entries) > MAX_FILES:
                raise ValueError("Backup inválido, sem catálogo SQLite ou com excesso de arquivos.")
            if set(names) != set(entries) | {MANIFEST}:
                raise ValueError("Arquivos não declarados ou ausentes no manifesto.")
            if (any(not isinstance(item, dict) or
                    not isinstance(item.get("size"), int) or
                    item["size"] < 0 or
                    not isinstance(item.get("sha256"), str) or
                    len(item["sha256"]) != 64
                    for item in entries.values()) or
                    sum(item["size"] for item in entries.values()) > MAX_BYTES):
                raise ValueError("Manifesto inválido ou maior que o limite permitido.")
            # Reject oversized restoration if disk space cannot hold the
            # declared uncompressed data. Keep 32 MiB for filesystem metadata.
            needed=sum(item["size"] for item in entries.values())
            if shutil.disk_usage(destination_vault.parent).free < needed+32*1024*1024:
                raise ValueError("Espaço em disco insuficiente para restaurar o backup.")
            for info in archive.infolist():
                name = info.filename
                if name == MANIFEST:
                    continue
                if not _safe_archive_name(name):
                    raise ValueError("Caminho inseguro no ZIP: " + name)
                if (info.file_size > 8*1024*1024 and
                        info.file_size > max(1, info.compress_size)*1000):
                    raise ValueError("Taxa de compressão suspeita no backup.")
                if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                    raise ValueError("Backup contém atalho simbólico.")
                target = (stage / name).resolve()
                if not target.is_relative_to(stage.resolve()) or info.is_dir():
                    raise ValueError("Entrada de arquivo inválida.")
                expected = entries[name]
                if not isinstance(expected, dict) or not isinstance(expected.get("size"), int):
                    raise ValueError("Manifesto inválido.")
                if expected["size"] < 0 or expected["size"] != info.file_size:
                    raise ValueError("Tamanho divergente no manifesto.")
                filesystem_target = _filesystem_path(target)
                filesystem_target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as inp, filesystem_target.open("xb") as out:
                    digest = hashlib.sha256()
                    size = 0
                    for block in iter(lambda: inp.read(1024 * 1024), b""):
                        size += len(block)
                        if size > expected["size"]:
                            raise ValueError("Arquivo maior que previsto.")
                        digest.update(block)
                        out.write(block)
                if size != expected["size"] or digest.hexdigest() != expected["sha256"]:
                    raise ValueError("Hash divergente: " + name)
        # Do not publish a corrupt catalog.
        with closing(sqlite3.connect(f"file:{(stage / DB_FILE).as_posix()}?mode=ro", uri=True)) as conn:
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Banco SQLite do backup está corrompido.")
        if destination_vault.exists():
            raise FileExistsError("Destino passou a existir durante a restauração.")
        os.rename(_filesystem_path(stage), _filesystem_path(destination_vault))
        return {"ok": True, "path": str(destination_vault),
                "files": len(entries), "bytes": sum(x["size"] for x in entries.values())}
    finally:
        if stage.exists():
            shutil.rmtree(_filesystem_path(stage))
