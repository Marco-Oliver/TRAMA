"""Regressões da base 2.2.0: restauração real, longa e não destrutiva.

Usa somente fixtures artificiais, sem acessar o cofre real do usuário,
GitHub, credenciais ou serviços de IA.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from knowledge_bridge.recovery import (
    MANIFEST, _filesystem_path, create_backup, restore_backup,
)


class RestoreBackupFoundationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trama-220-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "original"
        db = self.vault / ".base-conhecimento" / "estado.sqlite3"
        db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE evidencias (id TEXT PRIMARY KEY, descricao TEXT)")
            conn.execute("INSERT INTO evidencias VALUES (?,?)", ("aula-001", "fonte artificial"))
        # Several valid path components, together longer than classic MAX_PATH.
        self.relative = (
            ".base-conhecimento/repos/" +
            "projeto-" + "a" * 80 + "/" +
            "subpasta-" + "b" * 80 + "/" +
            "arquivos-" + "c" * 80 + ".txt"
        )
        self.original_file = _filesystem_path(self.vault / self.relative)
        self.original_file.parent.mkdir(parents=True, exist_ok=True)
        self.original_file.write_text("Apenas texto fictício da Aula 001.", encoding="utf-8")
        self.backup = self.root / "copia.zip"

    def test_restores_long_github_paths_without_touching_original(self):
        report = create_backup(self.vault, self.backup)
        self.assertTrue(report["ok"])
        self.assertGreater(len(str(self.root / "restored" / self.relative)), 260)
        self.assertGreaterEqual(report["files"], 2)
        target = self.root / "restored"
        restored = restore_backup(self.backup, target)
        self.assertTrue(restored["ok"])
        self.assertEqual(
            _filesystem_path(target / self.relative).read_text(encoding="utf-8"),
            "Apenas texto fictício da Aula 001.",
        )
        self.assertEqual(
            self.original_file.read_text(encoding="utf-8"),
            "Apenas texto fictício da Aula 001.",
        )
        with sqlite3.connect(target / ".base-conhecimento" / "estado.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM evidencias").fetchone()[0], 1)

    def test_restore_never_overwrites_an_existing_vault(self):
        create_backup(self.vault, self.backup)
        with self.assertRaises(ValueError):
            restore_backup(self.backup, self.vault)
        self.assertTrue(self.original_file.is_file())

    def test_rejects_path_traversal_before_publishing(self):
        malicious = self.root / "malicioso.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../escape.txt", "bad")
            archive.writestr(MANIFEST, json.dumps({
                "format": 1,
                "files": {
                    "../escape.txt": {"sha256": "0" * 64, "size": 3},
                    ".base-conhecimento/estado.sqlite3": {"sha256": "0" * 64, "size": 0},
                },
            }))
            archive.writestr(".base-conhecimento/estado.sqlite3", "")
        target = self.root / "malicious-restore"
        with self.assertRaises(ValueError):
            restore_backup(malicious, target)
        self.assertFalse(target.exists())
        self.assertFalse((self.root / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
