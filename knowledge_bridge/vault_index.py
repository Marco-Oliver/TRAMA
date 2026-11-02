"""Índice local, somente leitura, do cofre do Obsidian.

Nenhuma chamada de rede, código carregado da biblioteca ou HTML é executado.
Links [[wiki]] são resolvidos apenas dentro do cofre selecionado.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import stat

WIKI_RE = re.compile(r"(?<!!)\[\[([^\[\]\n]+)\]\]")
FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
HEADING_RE = re.compile(r"(?m)^#\s+(.+?)\s*$")


@dataclass(frozen=True)
class VaultNote:
    path: Path
    relative: str
    stem: str
    title: str
    section: str
    content: str
    links: tuple[str, ...]
    metadata: dict[str, str]


class VaultIndex:
    def __init__(self, vault: Path, allowed_sections: set[str] | None = None):
        self.vault = vault.expanduser().resolve()
        self.allowed_sections = frozenset(allowed_sections) if allowed_sections is not None else None
        self.notes: list[VaultNote] = []
        self.by_relative: dict[str, VaultNote] = {}
        self.by_stem: dict[str, list[VaultNote]] = {}
        self.load()

    def load(self):
        self.notes.clear()
        self.by_relative.clear()
        self.by_stem.clear()
        if not self.vault.is_dir():
            return
        # Evita seguir links simbólicos para fora do cofre e limitar leituras gigantes.
        for file in sorted(self.vault.rglob('*.md'), key=lambda p: str(p).casefold()):
            if len(self.notes) >= 12000:
                break
            try:
                relative_path = file.relative_to(self.vault)
                if (not relative_path.parts or
                        self.allowed_sections is not None and
                        relative_path.parts[0] not in self.allowed_sections):
                    continue
                # Do not even open excluded sections or hidden folders.
                if any(p.startswith('.') for p in relative_path.parts):
                    continue
                # Reject symbolic links in EVERY path component, not only
                # the Markdown file. This also protects in-vault aliases.
                if any((self.vault / Path(*relative_path.parts[:i])).is_symlink()
                       for i in range(1, len(relative_path.parts) + 1)):
                    continue
                if not file.is_file() or not file.resolve().is_relative_to(self.vault):
                    continue
                # O_NOFOLLOW prevents a final-component symlink swap on
                # platforms that support it; fstat checks the opened handle.
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                with os.fdopen(os.open(file, flags), "rb") as opened:
                    info = os.fstat(opened.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
                        continue
                    content = opened.read(2_000_001)
                if len(content) > 2_000_000:
                    continue
                relative = relative_path.as_posix()
                raw = content.decode('utf-8-sig', errors='replace')
            except (OSError, ValueError, UnicodeError):
                continue
            info = {}
            fm = FRONT_RE.match(raw)
            if fm:
                for line in fm.group(1).splitlines():
                    key, sep, value = line.partition(':')
                    if sep and re.fullmatch(r'[\w-]{1,45}', key.strip()):
                        info[key.strip()] = value.strip().strip("'\"")
            body = raw[fm.end():] if fm else raw
            heading = HEADING_RE.search(body)
            title = heading.group(1).strip() if heading else file.stem.replace('-', ' ')
            refs = []
            for match in WIKI_RE.finditer(body):
                name = match.group(1).split('|', 1)[0].split('#', 1)[0].strip()
                if name and name not in refs:
                    refs.append(name)
            section = relative.split('/', 1)[0]
            note = VaultNote(file, relative, file.stem, title, section, body, tuple(refs), info)
            self.notes.append(note)
            self.by_relative[relative.lower()] = note
            self.by_stem.setdefault(file.stem.casefold(), []).append(note)

    def resolve(self, reference: str, source: VaultNote | None = None) -> VaultNote | None:
        # Obsidian permite [[nome]], [[subpasta/nome]] e [[nome|apelido]].
        raw = reference.split('|', 1)[0].split('#', 1)[0].strip().replace('\\', '/')
        if not raw or raw.startswith('/') or '..' in Path(raw).parts:
            return None
        if raw.lower().endswith('.md'):
            raw = raw[:-3]
        choices = self.by_stem.get(Path(raw).name.casefold(), [])
        if '/' in raw:
            wanted = raw.casefold().rstrip('/') + '.md'
            matches = [x for x in choices if x.relative.casefold().endswith(wanted)]
            if len(matches) == 1:
                return matches[0]
            # An explicit path must never silently resolve to another note.
            return None
        if source and choices:
            same_folder = [x for x in choices if x.path.parent == source.path.parent]
            if len(same_folder) == 1:
                return same_folder[0]
        # Duplicate stems can occur across lessons. Avoid pointing to an
        # unrelated recording or overview just because it sorts first.
        return choices[0] if len(choices) == 1 else None

    def related(self, source: VaultNote, max_items: int = 20) -> list[VaultNote]:
        out = []
        seen = {source.relative}
        for ref in source.links:
            target = self.resolve(ref, source)
            if target and target.relative not in seen:
                seen.add(target.relative)
                out.append(target)
        # Backlinks: o grafo precisa funcionar nas duas direções.
        for other in self.notes:
            if len(out) >= max_items:
                break
            if other.relative in seen:
                continue
            if any(self.resolve(ref, other) == source for ref in other.links):
                out.append(other)
                seen.add(other.relative)
        return out[:max_items]

    def filter(self, category: str, query: str = '') -> list[VaultNote]:
        prefixes = {
            'aulas': '02-Minhas-Aulas',
            'conhecimento': '01-Meu-Conhecimento',
            'projetos': '03-Meus-Projetos',
            'biblioteca': '',
        }
        prefix = prefixes.get(category, '')
        q = query.strip().casefold()
        return [n for n in self.notes if (not prefix or n.section == prefix) and
                (not q or q in (n.title + ' ' + n.relative + ' ' + n.content[:40_000]).casefold())]

    def graph(self, cap: int = 180) -> tuple[list[VaultNote], list[tuple[int, int]]]:
        """Nós e arestas dos links reais, sem fabricar relações semânticas."""
        # Coloca nós com conexões primeiro, mantendo um limite visual sensato.
        candidates = [n for n in self.notes if n.section not in ('90-Sistema', '99-Anexos')]
        connected = {n.relative for n in candidates if n.links}
        for n in candidates:
            for link in n.links:
                other = self.resolve(link, n)
                if other:
                    connected.add(other.relative)
        nodes = sorted(candidates, key=lambda n: (n.relative not in connected, n.relative.casefold()))[:cap]
        ids = {n.relative: i for i, n in enumerate(nodes)}
        edges = set()
        for n in nodes:
            for reference in n.links:
                other = self.resolve(reference, n)
                if other and other.relative in ids:
                    a, b = ids[n.relative], ids[other.relative]
                    if a != b:
                        edges.add(tuple(sorted((a, b))))
        return nodes, sorted(edges)
