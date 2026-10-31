"""Validate real v1.9.0 SQLite catalog after v2.0.0 opens it."""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

file = Path(sys.argv[1])
assert file.is_file(), "Catálogo SQLite não encontrado"
connection = sqlite3.connect(f"file:{file.as_posix()}?mode=ro", uri=True)
try:
    assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert connection.execute("select count(*) from sources").fetchone()[0] >= 1
    assert connection.execute(
        "select count(*) from sqlite_master where type='table' and name='uncertainties'"
    ).fetchone()[0] == 1
finally:
    connection.close()
print("PASS: SQLite v1.9.0 permanece íntegro e recebeu a tabela da v2.0.0")
