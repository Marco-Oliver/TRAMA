"""Auditoria mínima para impedir que dados do usuário entrem na compilação."""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
invalid_names = {'.env','config.env','keys.json','secrets.json','credentials.json'}
forbidden_parts = {'.obsidian','.base-conhecimento','TRAMA-Vault','Meu-Obsidian','__pycache__','.buildvenv','dist','release'}
forbidden_ext = {'.sqlite','.sqlite3','.db','.pem','.p12','.pfx'}
errors = []
for file in root.rglob('*'):
    if not file.is_file(): continue
    rel = file.relative_to(root)
    if '__pycache__' in rel.parts or '.pytest_cache' in rel.parts:
        continue
    if set(rel.parts) & forbidden_parts or file.name in invalid_names or file.suffix.lower() in forbidden_ext:
        errors.append('Arquivo local proibido: '+str(rel))
        continue
    if file.suffix.lower() not in {'.py','.js','.html','.css','.md','.txt','.json','.yml','.yaml','.bat','.iss','.spec'}:
        continue
    text = file.read_text('utf-8', errors='replace')
    if re.search(r'AIza[0-9A-Za-z_-]{30,}', text): errors.append('Possível chave Gemini em '+str(rel))
    if re.search(r'github_pat_[0-9A-Za-z_]{20,}|ghp_[0-9A-Za-z]{30,}', text): errors.append('Possível token GitHub em '+str(rel))
if errors:
    print('PUBLICAÇÃO BLOQUEADA:', *errors, sep='\n- ', file=sys.stderr)
    sys.exit(1)
print('Fontes auditadas: nenhum cofre, banco ou chave detectado.')
