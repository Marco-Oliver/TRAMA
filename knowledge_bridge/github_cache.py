"""Bounded local LRU cache for verified GitHub bytes.

Only public repo content may be stored unencrypted. Private repository content
is encrypted by Windows DPAPI, or not persisted at all on other platforms.
No vault, SQLite, log, or note ever receives these cached file bytes.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile

from .paths import DATA_HOME
from .secure_keys import _crypt

MAX_CACHE = 300 * 1024 * 1024
MAX_OBJECT = 300_000


class GithubCache:
    def __init__(self, root=None, vault=None, max_bytes=MAX_CACHE):
        self.root = Path(root) if root is not None else DATA_HOME / "github-cache"
        self.root = self.root.expanduser()
        self.max_bytes = min(MAX_CACHE, max(0, int(max_bytes)))
        if self.root.is_symlink():
            raise ValueError("Cache GitHub não pode apontar para link simbólico.")
        if vault is not None and self.root.resolve().is_relative_to(Path(vault).resolve()):
            raise ValueError("Cache GitHub não pode ficar dentro do cofre Obsidian.")

    def _entry(self, key, private):
        # Hash names; neither private repo names nor filenames appear on disk.
        if not isinstance(key, tuple) or not key or any(not isinstance(x, str) for x in key):
            raise ValueError("Chave de cache inválida.")
        digest = hashlib.sha256((("private:" if private else "public:") +
                                 "\n".join(key)).encode("utf-8")).hexdigest()
        return self.root / (digest + ".entry")

    def _read(self, path):
        if path.is_symlink():
            return None
        try:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(path, flags), "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_OBJECT + 4096:
                    return None
                return stream.read(MAX_OBJECT + 4096 + 1)
        except OSError:
            return None

    def get(self, key, private=False):
        if type(private) is not bool:
            return None
        path = self._entry(key, private)
        stored = self._read(path)
        if not stored:
            return None
        expected = b"E" if private else b"P"
        if not stored.startswith(expected):
            return None
        try:
            data = _crypt(stored[1:], False) if private else stored[1:]
        except (OSError, ValueError, RuntimeError):
            return None
        if len(data) > MAX_OBJECT:
            return None
        try:
            os.utime(path, None, follow_symlinks=False)
        except OSError:
            pass
        return data

    def put(self, key, data, private=False):
        if (type(private) is not bool or not isinstance(data, bytes)
                or len(data) > MAX_OBJECT or not self.max_bytes):
            return False
        if private and sys.platform != "win32":
            return False  # Absolutely no private plaintext fallback on Linux/macOS.
        path = self._entry(key, private)
        if self.root.is_symlink() or path.is_symlink():
            return False
        try:
            protected = b"E" + _crypt(data, True) if private else b"P" + data
        except (OSError, ValueError, RuntimeError):
            return False
        if len(protected) > min(self.max_bytes, MAX_OBJECT + 4096):
            return False
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.root.is_symlink():
                return False
            fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".writing-", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(protected)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            self._evict()
            return True
        except OSError:
            return False

    def _evict(self):
        """Strict maximum for cache objects; oldest access time by mtime goes first."""
        try:
            candidates = []
            for path in self.root.glob("*.entry"):
                if path.is_symlink() or not path.is_file():
                    continue
                info = path.stat()
                if not stat.S_ISREG(info.st_mode):
                    continue
                candidates.append((info.st_mtime_ns, path, info.st_size))
            total = sum(size for _, _, size in candidates)
            for _, path, size in sorted(candidates):
                if total <= self.max_bytes:
                    break
                try:
                    path.unlink()
                    total -= size
                except OSError:
                    continue
        except OSError:
            pass
