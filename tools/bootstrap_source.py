"""Importa apenas o pacote previamente auditado, sem dados pessoais."""
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "TRAMA_GitHub_Source_1_9.tar.gz"
EXPECTED_SHA256 = "ef020d97a50193b663428504c1c0dc106111d8c633d52b281c77db45501e04f7"
REQUIRED = {
    "requirements.txt", "TRAMA.spec", "trama_launcher.py",
    "knowledge_bridge/bridge.py", "knowledge_bridge/secure_keys.py",
    "knowledge_bridge/update_service.py",
    ".github/workflows/release.yml", "tools/audit_release.py",
}
FORBIDDEN = {
    ".obsidian", ".base-conhecimento", "TRAMA-Vault", "userdata",
    "user_data", ".env", "config.env", "keys.json",
    "secrets.json", "credentials.json", "__pycache__",
}
if not ARCHIVE.is_file():
    raise SystemExit("Envie TRAMA_GitHub_Source_1_9.tar.gz à raiz do repositório.")
if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != EXPECTED_SHA256:
    raise SystemExit("Pacote incorreto: checksum SHA-256 não confere.")
with tarfile.open(ARCHIVE, "r:gz") as package:
    members = package.getmembers()
    paths = set()
    for member in members:
        rel = PurePosixPath(member.name)
        parts = [part for part in rel.parts if part != "."]
        if (rel.is_absolute() or ".." in parts or
            not (member.isfile() or member.isdir()) or
            any(part in FORBIDDEN for part in parts)):
            raise SystemExit("Arquivo não permitido no pacote: " + member.name)
        if member.isfile():
            paths.add("/".join(parts))
    missing = REQUIRED - paths
    if missing:
        raise SystemExit("Pacote incompleto: " + ", ".join(sorted(missing)))
    for member in members:
        rel = PurePosixPath(member.name)
        parts = [p for p in rel.parts if p != "."]
        # Do not overwrite the audited GitHub workflows installed separately.
        if parts and parts[0] == ".github":
            continue
        package.extract(member, ROOT)
ARCHIVE.unlink()
print("Código-fonte íntegro extraído. Nenhuma chave ou cofre foi importado.")
