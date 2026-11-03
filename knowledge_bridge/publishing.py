"""Escrita segura no cofre e páginas ligadas por fonte/conceito/projeto."""
from __future__ import annotations

import hashlib
import json
import unicodedata
import os
import re
from difflib import SequenceMatcher
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from .content import MODULES, evidence_excerpt, guess_modules, lesson_identity, slug, concept_slug, timed_lines
from .store import Store
from .memory_atlas import make_atlas, render_atlas, lesson_order, norm
from .code_intel import match_lesson_to_repository, potential_transcript_corrections
from .learning_review import refresh_uncertainties, render_uncertainties


def _escape_md(s: object) -> str:
    return str(s).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _frontmatter(**kwargs) -> str:
    out = ["---"]
    for k,v in kwargs.items():
        out.append(f"{k}: '{str(v).replace(chr(39), chr(39)*2)}'")
    return "\n".join(out + ["---", ""])


def _time_id(timestamp: str) -> str:
    """Obsidian block ID for a verified timestamp from the original TXT."""
    return "min-" + re.sub(r"[^0-9]", "-", timestamp.strip()).strip("-")


def _term_in_source(term: str, source: str) -> bool:
    """Literal, punctuation-aware presence; an IA interpretation isn't proof."""
    needle = norm(term)
    haystack = norm(source)
    return bool(needle and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack))


def _code_ref(repo, path: str, line: int) -> str:
    """Link to the immutable GitHub revision; local repos retain path:line."""
    location = f"{_escape_md(path)}:{line}"
    url = str(repo["url"]).removesuffix(".git").rstrip("/")
    sha = str(repo["sha"])
    if re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url) and re.fullmatch(r"[0-9a-f]{40}", sha, re.I):
        target = f"{url}/blob/{sha}/{quote(path, safe='/')}#L{line}"
        return f"[`{location}`]({target})"
    return f"`{location}`"


class Publisher:
    def __init__(self, store: Store):
        self.db, self.vault = store, store.vault
        for folder in ["00-Inicio", "01-Meu-Conhecimento", "02-Minhas-Aulas", "03-Meus-Projetos",
                       "05-Anotacoes-Pessoais", "90-Sistema", "99-Anexos/Videos", "99-Anexos/Transcricoes-Originais",
                       "99-Anexos/Materiais-Originais", "99-Anexos/Contexto-Classroom"]:
            (self.vault / folder).mkdir(parents=True, exist_ok=True)

    def write(self, rel: str, content: str) -> str:
        """Só sobrescreve algo que ainda corresponde ao hash da última gravação nossa."""
        rel = rel.replace("\\", "/")
        path = self.vault / rel
        if not path.resolve().is_relative_to(self.vault):
            raise ValueError("Saída fora do cofre")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            previous = self.db.last_write_hash(rel)
            current = hashlib.sha256(path.read_bytes()).hexdigest()
            if current == hashlib.sha256(content.encode("utf-8")).hexdigest():
                return "unchanged"
            if current != previous:
                # Avoid duplicate proposals when earlier suggestions were
                # edited; keep every human-edited proposal intact.
                proposals = sorted(path.parent.glob(path.stem + ".PROPOSTA*.md"))
                if any(p.is_file() and p.read_text(encoding="utf-8") == content for p in proposals):
                    return "manual-protected"
                conflict = path.with_name(path.stem + ".PROPOSTA.md")
                n = 1
                while conflict.exists():
                    conflict = path.with_name(f"{path.stem}.PROPOSTA-{n}.md")
                    n += 1
                conflict.write_text(content, encoding="utf-8")
                return "manual-protected"
        data = content.encode("utf-8")
        fd, tmp = tempfile.mkstemp(prefix=".nota-", dir=str(path.parent))
        try:
            with os.fdopen(fd,"wb") as out:
                out.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        self.db.register_write(rel, hashlib.sha256(data).hexdigest())
        return "written"

    def attachment(self, original: Path, kind: str) -> str:
        if kind == "video":
            raise ValueError("Vídeos não são copiados. Registre o link no contexto do Classroom.")
        from .content import file_hash
        digest = file_hash(original)
        subfolder = {"video": "Videos", "transcript": "Transcricoes-Originais",
                     "material": "Materiais-Originais"}.get(kind)
        if not subfolder:
            raise ValueError("Tipo de anexo inválido")
        # Conteúdo idêntico é armazenado uma vez, mesmo quando pertence
        # a aulas ou gravações distintas. O catálogo preserva cada fonte.
        target_dir=self.vault/'99-Anexos'/subfolder
        for candidate in target_dir.glob(digest[:14]+'-*'+original.suffix.lower()):
            if candidate.is_file() and file_hash(candidate)==digest:
                return candidate.relative_to(self.vault).as_posix()
        rel = f"99-Anexos/{subfolder}/{digest[:14]}-{slug(original.stem,45)}{original.suffix.lower()}"
        output = self.vault / rel
        if output.exists():
            # Uma cópia incompleta nunca pode ser tratada como importação concluída.
            if output.stat().st_size != original.stat().st_size or file_hash(output) != digest:
                raise ValueError("Cópia parcial/inconsistente detectada em anexos. Revise o arquivo antes de continuar.")
            return rel
        # Copia para arquivo temporário primeiro: se o programa fechar ou faltar
        # espaço, o destino final não aparece como se estivesse completo.
        fd, tmp = tempfile.mkstemp(prefix=".anexo-parcial-",dir=str(output.parent))
        try:
            os.close(fd)
            shutil.copy2(original,tmp)
            # The input might change while being copied. Never publish a copy
            # that differs from the digest stored in the source catalog.
            if file_hash(Path(tmp)) != digest:
                raise ValueError("O arquivo de origem mudou durante a cópia. Importe novamente.")
            os.replace(tmp,output)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return rel

    def _lesson_extras(self, lesson: str):
        """Sources for a lesson may exist without any programming content."""
        return [src for src in self.db.sources() if src["lesson"] == lesson and src["kind"] != "transcript"]

    def _context_rows(self, lesson: str):
        out = []
        for source in self._lesson_extras(lesson):
            if source["kind"] != "classroom":
                continue
            try:
                obj = json.loads((self.vault / source["stored_path"]).read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    out.append((source, obj))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
        return out

    def _append_context(self, body: list[str], lesson: str) -> None:
        body.extend(["", "## Contexto e materiais do Classroom", "",
                     "> Contexto de múltiplas fontes. Extrações automáticas são sugestões; confira o arquivo original."])
        rows = self._context_rows(lesson)
        if not rows:
            body.append("*Descrição do Classroom ainda não cadastrada.*")
        for src, item in rows:
            body.extend(["", f"### {_escape_md(item.get('titulo') or lesson)}", "",
                         f"- Origem: {_escape_md(item.get('origem') or 'registro de contexto')}",
                         f"- Data informada: {_escape_md(item.get('data') or 'não informada')}",
                         f"- Fonte preservada: `{_escape_md(src['stored_path'])}`"])
            if item.get('arquivo_fonte'):
                body.append(f"- Arquivo usado na extração: `{_escape_md(item['arquivo_fonte'])}`")
            if item.get('incertezas'):
                body.append(f"- **Revisar:** {_escape_md(item['incertezas'])}")
            for field, heading in (("descricao", "Descrição e agenda"), ("pessoas", "Pessoas e funções informadas"),
                                   ("atividades", "Atividades e decisões informadas")):
                value = item.get(field, "")
                if isinstance(value, str) and value.strip():
                    body.extend(["", f"**{heading}:**"])
                    body.extend(f"> {_escape_md(line)}" for line in value.splitlines() if line.strip())
            recordings = item.get("videos", [])
            if recordings:
                body.extend(["", "**Gravações (somente links, sem cópia do vídeo):**"])
                for entry in recordings[:30]:
                    if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                        title = _escape_md(entry.get("titulo", "Gravação"))
                        url = entry["url"]
                        if url.startswith(("https://", "http://")):
                            body.append(f"- **{title}**: <{url}>")
            for link in item.get("links", [])[:30]:
                if isinstance(link, str) and link.startswith(("https://", "http://")):
                    body.append(f"- Material/link do Classroom: <{link}>")
        body.extend(["", "## Arquivos e materiais preservados", ""])
        extras = [src for src in self._lesson_extras(lesson) if src["kind"] in ("video", "material")]
        if not extras:
            body.append("*Nenhum arquivo local anexado. Gravações podem estar registradas apenas por link acima.*")
        for src in extras:
            name = Path(src["stored_path"]).name
            body.append(f"- **{_escape_md(src['kind'])}:** [[{_escape_md(name)}|{_escape_md(src['label'])}]]")
        body.extend(["", "> Prints e PDFs são preservados como fontes. Somente arquivos com contexto automático "
                     "identificado acima foram analisados visualmente; hipóteses não são fatos confirmados."])

    def _other_lesson_note(self, lesson: str, sources: list) -> str:
        """A lesson with only video, screenshots or Classroom is still a lesson."""
        rel = f"02-Minhas-Aulas/{lesson}/00-contexto-{slug(lesson)}.md"
        title = lesson
        for _, record in self._context_rows(lesson):
            if record.get("titulo"):
                title = f"{lesson} — {record['titulo']}"
                break
        body = [_frontmatter(tipo="aula", aula=lesson, estado="sem_transcricao",
                             fonte="classroom_ou_materiais"), f"# {_escape_md(title)}", "",
                "## Situação da aula", "",
                "Aula cadastrada mesmo sem transcrição. Não presumir que houve conteúdo técnico.", "",
                "## Transcrição", "", "*Ainda não fornecida. Não gerar resumo de vídeo só pelo nome do arquivo.*"]
        self._append_context(body, lesson)
        self.write(rel, "\n".join(body) + "\n")
        return rel

    def lesson_overview(self, lesson: str, recordings: list[tuple]) -> str:
        """Human-readable landing page; source transcripts are never rewritten here.

        A lesson can span many V01/V02 recordings. All links are references
        to real files already published in the same vault.
        """
        contexts = [item for _, item in self._context_rows(lesson)]
        title = next((str(item.get('titulo', '')).strip() for item in contexts
                      if item.get('titulo')), '')
        heading = f"{lesson} — {title}" if title else lesson
        safe_name = _escape_md(heading)
        rel = f"02-Minhas-Aulas/{lesson}/00-Visao-geral.md"
        rows = [_frontmatter(tipo='visao_geral', aula=lesson, estado='fontes_organizadas'),
                f"# {safe_name}", '',
                '> **Como ler esta página:** ela reúne o que consta nos materiais. '
                'Plano de aula não é prova de execução; citação de conteúdo não comprova domínio pessoal.',
                '', '## Em poucas palavras', '']
        summaries = []
        for src, note in recordings:
            analysis = self.db.analysis(src['id'], src['digest'])
            if analysis and analysis.get('resumo'):
                summaries.append((src, note, analysis))
        if summaries:
            rows.append(f"Esta aula reúne **{len(recordings)} {'gravação' if len(recordings)==1 else 'gravações'} com transcrição**. "
                        'Consulte cada parte abaixo para a explicação detalhada.')
            for src, note, analysis in summaries:
                label = _escape_md(src['label'].removesuffix('.txt').removesuffix('.md'))
                text = str(analysis['resumo']).replace('**Parte 1:**', '').strip()
                rows.extend(['', f"### [[{Path(note).stem}|{label}]]", '', text[:1250]])
        else:
            rows.append('**Pendente:** a IA ainda não gerou o resumo desta aula. Os materiais abaixo permanecem disponíveis.')
        rows += ['', '## Gravações e transcrições', '']
        if recordings:
            for src, note in sorted(recordings, key=lambda p:(p[0]['video'] or 'zz',p[0]['label'])):
                label = _escape_md(Path(src['label']).stem)
                status = 'resumida com IA' if self.db.analysis(src['id'], src['digest']) else 'aguardando análise'
                rows.append(f"- [[{Path(note).stem}|{label}]] — {status}; "
                            f"transcrição original: `{_escape_md(src['label'])}` (consulte a aba Transcrição)")
        else:
            rows.append('*Nenhuma gravação transcrita importada ainda.*')
        links=[]
        for item in contexts:
            for record in item.get('videos', []) if isinstance(item.get('videos'), list) else []:
                if isinstance(record,dict) and str(record.get('url','')).startswith(('https://','http://')):
                    pair=(str(record.get('titulo') or 'Gravação')[:200], record['url'])
                    if pair not in links:links.append(pair)
        if links:
            rows += ['', '**Assistir aos vídeos originais (sem download):**']
            for name,url in links[:45]:
                rows.append(f"- {_escape_md(name)}: <{url}>")
        rows += ['', '## Classroom — contexto e atividades', '']
        if contexts:
            for item in contexts:
                if item.get('data'):rows.append(f"- Data informada: {_escape_md(item['data'])}")
                if item.get('descricao'):
                    rows.extend(['', '**Descrição/agenda publicada:**', ''])
                    for line in str(item['descricao']).splitlines()[:100]:
                        if line.strip():rows.append(f"> {_escape_md(line)}")
                if item.get('atividades'):
                    rows.extend(['', '**Atividades registradas na publicação (não necessariamente realizadas):**',''])
                    for line in str(item['atividades']).splitlines()[:40]:
                        if line.strip():rows.append(f"- {_escape_md(line)}")
                for link in item.get('links', []) if isinstance(item.get('links'),list) else []:
                    if isinstance(link,str) and link.startswith(('https://','http://')):
                        rows.append(f"- Material publicado: <{link}>")
        else:
            rows.append('*Nenhuma publicação do Classroom relacionada a esta aula foi cadastrada.*')
        rows += ['', '## Pessoas e assuntos mencionados', '']
        person_links=[]; concept_links=[]
        for item in contexts:
            for line in str(item.get('pessoas','')).splitlines():
                name = re.split(r"\s+[—–-]\s+|\s*:\s*",line.strip(),maxsplit=1)[0].strip()
                if 3<=len(name)<=80:
                    link=f"[[{slug(name)}|{_escape_md(name)}]]"
                    if link not in person_links:person_links.append(link)
        for src, note in recordings:
            a=self.db.analysis(src['id'],src['digest']) or {}
            raw=(self.vault/src['stored_path']).read_text(encoding='utf-8-sig',errors='replace')
            normalized=self._person_key(raw)
            for person in a.get('pessoas',[]):
                name=person.get('nome','').strip()
                if len(name)<3 or self._person_key(name) not in normalized:continue
                name,warning=self._reviewable_person_name(name, lesson)
                link=f"[[{slug(name)}|{_escape_md(name)}]]"
                if link not in person_links:person_links.append(link)
            for c in a.get('conceitos',[]):
                name=c.get('nome','').strip()
                if not name:continue
                link=f"[[{concept_slug(name)}|{_escape_md(name)}]]"
                if link not in concept_links:concept_links.append(link)
        rows.extend(['**Pessoas (conforme fontes):**', ''] +
                    ([f'- {link} — confira o contexto na fonte' for link in person_links] if person_links else ['*Ainda sem pessoas associadas com evidência.*']))
        variant_warnings=[]
        for src, _note in recordings:
            analysis=self.db.analysis(src['id'],src['digest']) or {}
            for person in analysis.get('pessoas',[]):
                _canonical,possible=self._reviewable_person_name(person.get('nome',''),lesson)
                if possible and possible not in variant_warnings:variant_warnings.append(possible)
        if variant_warnings:
            rows.extend(['', '**Grafias de nomes a conferir:**', ''])
            rows.extend('- '+_escape_md(w) for w in variant_warnings)
        rows.extend(['', '**Conceitos identificados pela IA (conferir na fonte):**', ''] +
                    ([f'- {link}' for link in concept_links] if concept_links else ['*Nenhum conceito técnico comprovado nesta aula.*']))
        rows += ['', '## Evolução e relações com aulas anteriores', '',
                 '> As conexões abaixo vêm de conceitos identificados pela IA em fontes cadastradas. '
                 'São **candidatas**, não comprovação de aprendizado, domínio ou autoria.',
                 '']
        atlas = getattr(self, '_atlas', {'concepts':[],'repos':[]})
        evolution=[]
        for concept in atlas.get('concepts',[]):
            mentions=concept.get('mentions',[])
            current=[m for m in mentions if m['lesson']==lesson]
            earlier=[m for m in mentions if lesson_order(m['lesson']) < lesson_order(lesson)]
            if not current:continue
            if earlier:
                prior=earlier[0]
                first=f"[[{Path(prior['note']).stem}|{prior['lesson']}]]"
                recent=earlier[-1]
                newest=f"[[{Path(recent['note']).stem}|{recent['lesson']}]]"
                evolution.append(f"- **[[{concept['slug']}|{_escape_md(concept['name'])}]]:** "
                    f"primeira menção cadastrada em {first}; retomado nesta aula "
                    f"(referência anterior mais recente: {newest}). "
                    f"Evidência atual: {current[0]['timestamp'] or 'horário não confirmado'} — "
                    f"{current[0]['confidence']}.")
            else:
                evolution.append(f"- **[[{concept['slug']}|{_escape_md(concept['name'])}]]:** "
                    'primeira menção entre as aulas já analisadas; ' 
                    f"horário: {current[0]['timestamp'] or 'não confirmado'}. Não presumir domínio.")
        if evolution:
            rows.extend(evolution[:35])
            rows.extend(['', '- [[Mapa-da-Evolucao|Abrir mapa completo da evolução]]'])
        else:
            rows.append('*Nenhum conceito com relação temporal validável nesta aula. '
                        'Isso é normal em apresentações ou encontros sem conteúdo técnico.*')
        rows += ['', '## Projetos relacionados', '']
        found_code=False
        for repo in self.db.repositories():
            try:
                payload=json.loads(repo['payload'])
                matches=[]
                for src, _note in recordings:
                    raw=(self.vault/src['stored_path']).read_text(encoding='utf-8-sig',errors='replace')
                    a=self.db.analysis(src['id'],src['digest'])
                    matches.extend(match_lesson_to_repository(raw,a,payload,cap=2))
                if matches:
                    found_code=True
                    ref=f"{slug(repo['name'])}-{repo['sha'][:7]}"
                    rows.append(f"- [[{ref}|{_escape_md(repo['name'])}]] — código relacionado por conceito; "
                                f"ex.: {_code_ref(repo, matches[0]['path'], matches[0]['line'])}. "
                                '**Possível relação; não comprova autoria nem momento da implementação.**')
            except (ValueError, KeyError, TypeError):
                continue
        if not found_code:
            rows.append('*Ainda não há código com relação verificável para esta aula.*')
        rows += ['', '## Fontes e materiais', '']
        for src in self._lesson_extras(lesson):
            if src['kind']=='classroom':
                rows.append(f"- Contexto registrado: `{_escape_md(src['stored_path'])}`")
            elif src['kind']=='material':
                rows.append(f"- Material preservado: `{_escape_md(src['label'])}` (arquivo no cofre: `{_escape_md(src['stored_path'])}`)")
        if not recordings and not contexts:
            rows.append('*Ainda não há fontes suficientes.*')
        rows += ['', '## O que ainda precisa ser conferido', '',
                 '- Confira nomes e termos suspeitos na gravação original; IA não é prova de correção da transcrição.',
                 '- A presença de um conceito numa transcrição não significa que você o praticou ou domina.',
                 '- Relações com projetos só são confirmadas quando há referência real a código, arquivo e linha.']
        self.write(rel, '\n'.join(rows).strip()+'\n')
        return rel

    @staticmethod
    def _person_key(value: str) -> str:
        return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold().strip()

    @staticmethod
    def _possible_spelling_variant(name: str, authoritative: str) -> bool:
        """Suggest a spelling conflict; NEVER certify two identities as equal.

        Used to keep suspicious near-identical names in one reviewable context
        rather than creating two definite person profiles from automatic text.
        """
        def parts(raw):
            normalized=unicodedata.normalize('NFKD',raw).encode('ascii','ignore').decode().casefold()
            return [p for p in re.split(r'\W+', normalized) if p]
        a,b=parts(name),parts(authoritative)
        if len(a)<2 or len(b)<2 or a==b or a[-1]!=b[-1] or min(len(a[0]),len(b[0]))<4:
            return False
        return SequenceMatcher(None,a[0],b[0]).ratio()>=0.86

    def _classroom_person_names(self, lesson: str) -> list[str]:
        names=[]
        for _, item in self._context_rows(lesson):
            for line in str(item.get('pessoas','')).splitlines()[:25]:
                name=re.split(r'\s+[—–-]\s+|\s*:\s*', line.strip().lstrip('-• '),maxsplit=1)[0].strip()
                if 3 <= len(name) <=80 and name not in names:names.append(name)
        return names

    def _reviewable_person_name(self, name: str, lesson: str) -> tuple[str,str]:
        canonical=self._classroom_person_names(lesson)
        for candidate in canonical:
            if self._person_key(candidate)==self._person_key(name):
                return candidate,''
            if self._possible_spelling_variant(name,candidate):
                return candidate,(f'Possível variante de grafia: a transcrição menciona "{name}", '
                                   f'mas o Classroom registra "{candidate}". Confirmar se é a mesma pessoa.')
        return name,''

    def transcript_note(self, src, analysis: dict | None):
        lesson = src["lesson"] or "Aulas-Sem-Numero"
        video = src["video"] or "Sem-V"
        fname = f"{slug(Path(src['label']).stem, 52)}-{src['id'][:7]}.md"
        rel = f"02-Minhas-Aulas/{lesson}/{fname}"
        concepts = analysis.get("conceitos",[]) if analysis else []
        concept_links = []
        for c in concepts:
            name = c.get("nome", "").strip()
            if name:
                concept_links.append(f"[[{concept_slug(name)}|{_escape_md(name)}]]")
        raw = self.vault / src["stored_path"]
        text = raw.read_text(encoding="utf-8-sig",errors="replace")
        # Uma apresentação ou encontro administrativo não vira falsamente um
        # módulo técnico só porque alguém mencionou a palavra 'programação'.
        lesson_kind=analysis.get('tipo_aula','indefinida') if analysis else 'indefinida'
        modules = [] if lesson_kind in ('apresentacao','organizacional','atividade') and not concepts else [
            m for m in guess_modules(text[:24000] + ' ' + ' '.join(c.get('nome','') for c in concepts))
            if m != 'A-Classificar']
        times = evidence_excerpt(text)
        head = _frontmatter(tipo="aula", fonte_id=src["id"], aula=lesson,
                            gravacao=video, estado="resumida_com_ia" if analysis else "aguardando_ia")
        body = [head, f"# {Path(src['label']).stem}", "", "## Resumo da aula"]
        if analysis:
            body += [analysis.get("resumo", "Sem resumo."), "",
                     "## Conceitos identificados pela IA (conferir na fonte)", "",
                     "> Os nomes e explicações abaixo são interpretações da transcrição. "
                     "Um termo mencionado não significa que foi ensinado ou dominado."]
            for c in concepts:
                name = c.get("nome","")
                if not name:
                    continue
                tempo = f" ({c['tempo']})" if c.get("tempo") else ""
                body.append(f"- **{_escape_md(name)}**{tempo}: {_escape_md(c.get('explicacao',''))}")
            body += ["", "## Exemplos mencionados"] + [f"- {_escape_md(x)}" for x in analysis.get("exemplos",[])]
            body += ["", "## Termos para conferir (não são erros confirmados)", "",
                     "> Estes termos foram sinalizados pela IA. Nomes próprios, apelidos e siglas podem estar corretos na fala."] + [f"- {_escape_md(x)}" for x in analysis.get("duvidas",[])]
        else:
            body += ["*Resumo ainda não gerado por IA. Se você configurou uma API gratuita em Ajustes, clique em Gerar Resumos para processar as transcrições pendentes. Os trechos abaixo não são síntese.*", "",
                     "## Trechos da transcrição para consulta (não são síntese)"]
            body += [f"- **{t}** — {_escape_md(s)}" for t,s in times]
        if analysis:
            body += ["", "## Tipo e contexto do encontro", "",
                     f"- Classificação sugerida pela IA: **{_escape_md(analysis.get('tipo_aula', 'indefinida'))}**.",
                     "- Uma apresentação não comprova aprendizado de programação."]
            for key, heading in (("pessoas", "Pessoas citadas e papéis"),
                                 ("atividades", "Atividades mencionadas"),
                                 ("ferramentas", "Ferramentas e recursos citados"),
                                 ("marcos", "Metodologia, decisões e contexto")):
                body.extend(["", f"## {heading}", "",
                             "> Extração assistida por IA; confirme na fonte original antes de tratar como fato."])
                for entry in analysis.get(key, [])[:16]:
                    if not isinstance(entry, dict):
                        continue
                    parts = [entry.get(name, "") for name in ("nome", "papel", "informacao", "descricao", "contexto") if entry.get(name)]
                    if parts:
                        body.append(f"- {_escape_md(' — '.join(parts))} " +
                                    (f"(**{_escape_md(entry.get('tempo', ''))}**)" if entry.get('tempo') else "(sem horário confirmado)"))
                if body[-1].startswith('> Extração'):
                    body.append('*Não identificado nesta aula.*')
        self._append_context(body, lesson)
        # Source-grounded anchors make timestamps navigable without
        # modifying the preserved transcript in 99-Anexos.
        # Only publish anchored excerpts that help review the notes.
        # The complete, unmodified transcript remains in 99-Anexos;
        # copying every timed line here makes large vaults unwieldy.
        referenced_times = {str(c.get("tempo", "")).strip()
                            for c in concepts if isinstance(c, dict)}
        if analysis:
            for category in ("pessoas", "atividades", "ferramentas", "marcos"):
                referenced_times.update(str(item.get("tempo", "")).strip()
                    for item in analysis.get(category, [])
                    if isinstance(item, dict))
        referenced_times.update(t for t, _sentence in evidence_excerpt(text))
        indexed = {}
        for stamp, sentence in timed_lines(text):
            if stamp in referenced_times and stamp != "sem horário" and stamp not in indexed:
                indexed[stamp] = sentence
        if indexed:
            body += ["", "## Trechos da transcrição com horários verificáveis", "",
                     "> Trechos selecionados da transcrição; os horários não foram confirmados no vídeo."]
            for stamp, sentence in indexed.items():
                body.append(f"- **{stamp}** — {_escape_md(sentence[:420])} ^{_time_id(stamp)}")
        body += ["", "## Fontes originais", f"- Transcrição: [[{Path(src['stored_path']).stem}]]",
                 f"- Arquivo original: `{_escape_md(src['label'])}`", "", "## Conhecimentos relacionados",
                 ", ".join(concept_links) if concept_links else "*Serão vinculados após análise com IA.*",
                 "", "## Acesso às gravações"]
        registered_videos=[]
        for _, record in self._context_rows(lesson):
            registered_videos.extend(record.get('videos', []))
        for entry in registered_videos:
            if isinstance(entry, dict) and entry.get('url', '').startswith(('https://','http://')):
                body.append(f"- **{_escape_md(entry.get('titulo','Gravação'))}**: <{entry['url']}>")
        # Arquivos importados no passado continuam disponíveis; não fazemos novas cópias.
        for video_src in self.db.sources("video"):
            if src["lesson"] and src["lesson"] == video_src["lesson"] and (src["video"] == video_src["video"] or not src["video"] or not video_src["video"]):
                body.append(f"- Legado local: ![[{Path(video_src['stored_path']).name}]]")
        if not registered_videos and not any(s['lesson'] == lesson for s in self.db.sources('video')):
            body.append("*Link da gravação ainda não informado. Cadastre em Aulas → Contexto +.*")
        body += ["", "> Os códigos e nomes técnicos devem ser conferidos com o repositório antes de serem considerados verificados."]
        body += ["", "## Relações com códigos e projetos", ""]
        import json
        project_matches = []
        for repo in self.db.repositories():
            payload = json.loads(repo["payload"])
            matched = match_lesson_to_repository(text, analysis, payload, cap=5)
            if not matched:
                continue
            project_ref = f"{slug(repo['name'])}-{repo['sha'][:7]}"
            body.append(f"### [[{project_ref}|{_escape_md(repo['name'])}]]")
            body.append("*Conexão sugerida por conceito mencionado + código encontrado; não prova autoria nem que foi programado nesta aula.*")
            for e in matched:
                body.append(f"- `{e['concept']}` — {_code_ref(repo, e['path'], e['line'])} no commit `{repo['sha'][:10]}`")
                snippet = str(e.get("snippet", "")).strip()
                if snippet:
                    ext = Path(e["path"]).suffix.lower()
                    language = {".cs": "csharp", ".ts": "typescript", ".tsx": "tsx",
                                ".js": "javascript", ".jsx": "jsx", ".py": "python",
                                ".sql": "sql"}.get(ext, "text")
                    body.extend(["", f"```{language}", snippet.replace("```", "` ` `"), "```", ""])
            project_matches.append((repo, payload))
        if not project_matches:
            body.append("*Nenhum vínculo com código encontrado ainda. Pode ser incluído quando os repositórios chegarem.*")
        body += ["", "## Comparação revisada por IA (com referências)"]
        validated_any=False
        for repo, payload in project_matches:
            result=self.db.connection(src['id'],src['digest'],repo['url'],repo['sha'])
            if not result:continue
            validated_any=True
            body += [f"### {repo['name']} — commit `{repo['sha'][:10]}`", "",
                     "> Interpretação assistida por IA, não confirmação de autoria, domínio nem data exata da implementação."]
            for item in result.get('relacoes',[]):
                body.append(f"- **{_escape_md(item['conceito'])}** ({item['tempo'] or 'sem minuto'}): "
                            f"{_escape_md(item['evolucao'])} — {_code_ref(repo, item['path'], item['line'])} "
                            f"**[{item['status']}]**")
            for item in result.get('novidades',[]):
                body.append(f"- **Possível novidade — {_escape_md(item['conceito'])}:** "
                            f"{_escape_md(item['explicacao'])} ({item['tempo'] or 'sem minuto'})")
            for item in result.get('correcoes',[]):
                body.append(f"- **Possível erro de transcrição:** `{_escape_md(item['ouvido'])}` → "
                            f"`{_escape_md(item['sugestao'])}` — {_code_ref(repo, item['path'], item['line'])} "
                            f"**[{item['status']}]**")
        if not validated_any:
            body.append('*Ainda sem comparação pela IA; relações acima são pistas verificadas de texto e código.*')
        body += ["", "## Termos suspeitos da transcrição", ""]
        suggested=[]
        for repo, payload in project_matches:
            for hint in potential_transcript_corrections(text, payload):
                key=(hint['heard'].lower(),hint['candidate'])
                if key in suggested:
                    continue
                suggested.append(key)
                body.append(f"- **HIPÓTESE, não correção automática:** `{_escape_md(hint['heard'])}` pode corresponder a "
                            f"`{hint['candidate']}`, encontrado em {_code_ref(repo, hint['path'], hint['line'])} "
                            f"({repo['name']}); confira o vídeo antes de confirmar.")
        if not suggested:
            body.append("*Nenhuma correção fundamentada encontrada.*")
        self.write(rel, "\n".join(body).strip() + "\n")
        return rel, concepts, modules

    def rebuild(self):
        """Deriva notas e revisão incremental das fontes originais cadastradas."""
        # Fail closed before *any* Markdown write if a cached transcript no
        # longer agrees with the SQLite catalog. User notes stay untouched.
        from .content import file_hash
        for source in self.db.sources("transcript"):
            stored = self.vault / (source["stored_path"] or "")
            path = stored.resolve()
            if (stored.is_symlink() or not path.is_relative_to(self.vault) or
                    not path.is_file() or file_hash(path) != source["digest"]):
                self.db.update_status(source["id"], "NEEDS_REVIEW")
                raise ValueError("Fonte do cofre alterada ou ausente: " +
                                 source["label"] + ". Reimporte o original.")
        refresh_uncertainties(self.db)
        self._atlas = make_atlas(self.db)
        concept_map = defaultdict(list)
        module_map = defaultdict(list)
        lesson_links = []
        person_map = defaultdict(list)
        transcripts_by_lesson = set()
        for src in self.db.sources("transcript"):
            analysis = self.db.analysis(src["id"],src["digest"])
            note, concepts, modules = self.transcript_note(src, analysis)
            lesson_links.append((src, note))
            if src["lesson"]:
                transcripts_by_lesson.add(src["lesson"])
            if analysis:
                original = (self.vault / src["stored_path"]).read_text(encoding="utf-8-sig", errors="replace")
                normalized = self._person_key(original)
                for person in analysis.get("pessoas", []):
                    name = person.get("nome", "").strip()
                    # Must be a literal mention somewhere in the original transcript,
                    # not just a fabricated name returned by an LLM.
                    if not 3 <= len(name) <= 130 or self._person_key(name) not in normalized:
                        continue
                    canonical,warning=self._reviewable_person_name(name,src['lesson'] or '')
                    details={**person}
                    if warning:
                        details['informacao']=(str(person.get('informacao',''))+' — '+warning).strip(' —')
                    person_map[slug(canonical)].append((canonical, src, note, details,
                        'transcrição (nome a conferir)' if warning else 'transcrição (extração IA, revisar)'))
            for m in modules:
                module_map[m].append((src,note,analysis))
            if not analysis:
                continue
            for concept in concepts:
                name = concept.get("nome", "").strip()
                if name:
                    concept_map[concept_slug(name)].append((name,src,note,concept))
        # Classroom can contain names as explicitly user-provided text, even if there is
        # no transcript or code. It is a separate kind of evidence and must be labeled.
        lesson_to_note = {s['lesson']: n for s, n in lesson_links if s['lesson']}
        for src in self.db.sources("classroom"):
            for _, item in self._context_rows(src["lesson"]):
                for row in item.get("pessoas", "").splitlines()[:25]:
                    line = row.strip().lstrip("-• ")
                    if not line:
                        continue
                    name = re.split(r"\s+[—–-]\s+|\s*:\s*", line, maxsplit=1)[0].strip()
                    if not 3 <= len(name) <= 80:
                        continue
                    person_map[slug(name)].append((name, src, lesson_to_note.get(src["lesson"], f"02-Minhas-Aulas/{src['lesson']}/00-contexto-{slug(src['lesson'])}.md"),
                                                   {"informacao": line}, "Classroom (registrado pelo usuário)"))
        for cslug, records in person_map.items():
            name = records[0][0]
            body = [_frontmatter(tipo="pessoa", estado="referencias_a_revisar", fontes=len(records)),
                    f"# {_escape_md(name)}", "", "> Identificador baseado no nome; pessoas homônimas podem existir.",
                    "> Informações extraídas da fonte ou cadastradas manualmente; não presumir identidade, cargo ou fatos não citados.",
                    "", "## Menções nas aulas", ""]
            for _, src, note, person, origin in records:
                body.append(f"- [[{Path(note).stem}|{_escape_md(src['lesson'] or src['label'])}]]: "
                            f"{_escape_md(person.get('informacao') or person.get('papel') or 'Mencionado')} "
                            f"({origin}; {person.get('tempo') or 'sem horário confirmado'}).")
            self.write(f"01-Meu-Conhecimento/Pessoas/{cslug}.md", "\n".join(body) + "\n")

        # Página inicial para leitura humana: uma aula = várias gravações e fontes.
        lesson_group = defaultdict(list)
        for src, note in lesson_links:
            if src['lesson']:lesson_group[src['lesson']].append((src,note))
        all_lessons = sorted({s['lesson'] for s in self.db.sources() if s['lesson']})
        overview_links = {}
        for lesson in all_lessons:
            overview_links[lesson] = self.lesson_overview(lesson, lesson_group.get(lesson, []))

        # Index every lesson, even a lesson with only a Classroom description or video.
        for lesson in sorted({s['lesson'] for s in self.db.sources() if s['lesson']} - transcripts_by_lesson):
            self._other_lesson_note(lesson, [s for s in self.db.sources() if s['lesson'] == lesson])

        repo_rows = self.db.repositories()
        repo_info = []
        for repo in repo_rows:
            import json
            payload = json.loads(repo["payload"])
            repo_info.append((repo,payload))
            rel = f"03-Meus-Projetos/{slug(repo['name'])}-{repo['sha'][:7]}.md"
            body = [_frontmatter(tipo="projeto", sha=repo["sha"], estado=repo["status"]),
                    f"# Projeto — {repo['name']}", "", f"- Repositório: {repo['url']}",
                    f"- Commit analisado: `{repo['sha']}`", "",
                    "## Contexto e colaboração", "",
                    "- Pode ser trabalho individual, em dupla ou em equipe: **não inferir autoria individual de um arquivo**.",
                    "- Autores de commits ajudam a investigar a contribuição, mas não comprovam quem escreveu cada linha.",
                    f"- Múltiplos autores de commits identificados: {'sim' if payload.get('collaboration') else 'não detectado / histórico incompleto'}.",
                    "", "### Histórico recente disponível"]
            for h in payload.get("history",[])[:25]:
                if not isinstance(h, dict):continue
                body.append(f"- `{_escape_md(h.get('sha','desconhecido'))}` ({_escape_md(h.get('date','sem data'))}) — {_escape_md(h.get('subject','sem assunto'))} "
                            f"— autor registrado: {_escape_md(h.get('author','desconhecido'))}")
            if not payload.get("history"):
                body.append("*Histórico não disponível ou repositório sem commits registrados.*")
            body += ["", "## Tecnologias observadas", ", ".join(payload.get("technologies",[])) or "*Não detectadas*",
                     "", "## Documentação do próprio repositório"]
            for doc in payload.get("documentation",[])[:10]:
                body.append(f"- `{_escape_md(doc['path'])}`: {_escape_md(doc['excerpt'][:250])}")
            if not payload.get("documentation"):
                body.append("*Nenhum documento Markdown encontrado no conjunto seguro analisado.*")
            body += ["", "## Código real — trechos com arquivo e linha", "",
                     "> Evidências do commit acima, somente leitura. Uma correspondência textual não comprova que o aluno domina o conceito."]
            for e in payload.get("evidence",[])[:30]:
                ext = Path(e["path"]).suffix.lower()
                lang = {".cs":"csharp", ".ts":"typescript", ".tsx":"tsx", ".js":"javascript",
                        ".jsx":"jsx", ".py":"python", ".sql":"sql"}.get(ext,"text")
                body += [f"### `{e['concept']}` — {_code_ref(repo, e['path'], e['line'])}", "",
                         f"```{lang}", e["snippet"].replace("```","` ` `"), "```", ""]
            if not payload.get("evidence"):
                body.append("*Nenhum símbolo da lista rastreada encontrado.*")
            body += ["", "## Conexões com aulas", ""]
            linked = False
            for src, note in lesson_links:
                raw=(self.vault/src["stored_path"]).read_text(encoding="utf-8-sig",errors="replace")
                analysis=self.db.analysis(src["id"],src["digest"])
                links=match_lesson_to_repository(raw,analysis,payload,cap=4)
                if links:
                    linked=True
                    body.append(f"- [[{Path(note).stem}|{_escape_md(src['label'])}]] — " + ", ".join(
                        f"`{link['concept']}` ({_escape_md(link['path'])}:{link['line']})" for link in links))
            if not linked:
                body.append("*Aguardando aulas com evidências compatíveis.*")
            body += ["", "## Próximos conhecimentos e pendências",
                     "- Compare o código com as aulas vinculadas. Se houver divergência, consulte a transcrição e o vídeo.",
                     "- Para atribuir prática pessoal ou domínio, adicione confirmação ou evidência de atividade individual."]
            self.write(rel,"\n".join(body)+"\n")
        # Concept pages never certify that an AI interpretation was taught.
        # They retain all distinct explanations across chunks and show
        # whether the literal technical term appears in the preserved source.
        for cslug, entries in concept_map.items():
            name = entries[0][0]
            observed = []
            for _, src, note, concept in entries:
                original = (self.vault / src["stored_path"]).read_text(
                    encoding="utf-8-sig", errors="replace")
                observed.append(_term_in_source(name, original))
            state = "termo_encontrado_na_fonte" if any(observed) else "interpretacao_ia_sem_termo_literal"
            body = [_frontmatter(tipo="conceito", fontes=len(entries), estado=state),
                    f"# {_escape_md(name)}", "",
                    "> Conceito identificado por IA. Um termo literal na transcrição "
                    "não confirma sozinho que houve explicação, prática ou domínio.",
                    "", "## Explicações e referências das aulas", ""]
            for (_, src, note, concept), literal in zip(entries, observed):
                raw = (self.vault / src["stored_path"]).read_text(
                    encoding="utf-8-sig", errors="replace")
                valid_times = {t for t, _ in timed_lines(raw) if t != "sem horário"}
                stamp = str(concept.get("tempo", "")).strip()
                where = f"[[{Path(note).with_suffix('').as_posix()}|{_escape_md(src['label'])}]]"
                timestamp_link = (f" · [[{Path(note).with_suffix('').as_posix()}#^{_time_id(stamp)}|{stamp}]]"
                                  if stamp in valid_times else " · horário não localizado")
                evidence_status = ("termo encontrado literalmente na transcrição"
                                   if literal else "interpretação da IA; termo não encontrado literalmente")
                body.append(f"- **{_escape_md(concept.get('explicacao', ''))}** — {where}"
                            f"{timestamp_link} · *{evidence_status}*.")
            body += ["", "## Evidências e aprendizagem", "",
                     "- **Mencionado:** confira a fala original antes de considerar o conceito confirmado.",
                     "- **Ensinado:** requer explicação verificável na fonte; termo citado não basta.",
                     "- **Praticado:** requer exercício/atividade com evidência.",
                     "- **Domínio do aluno:** não é deduzido automaticamente.",
                     "", "## Projetos relacionados", ""]
            for repo, payload in repo_info:
                matches = [e for e in payload.get("evidence",[])
                           if norm(e["concept"]) == norm(name)]
                if matches:
                    first = matches[0]
                    body.append(f"- [[{slug(repo['name'])}-{repo['sha'][:7]}|{_escape_md(repo['name'])}]]: "
                                f"{_code_ref(repo, first['path'], first['line'])} — "
                                "código existente, sem atribuição automática de autoria.")
            if body[-1] == "## Projetos relacionados":
                body.append("*Nenhum vínculo de código encontrado no índice.*")
            self.write(f"01-Meu-Conhecimento/Conceitos/{cslug}.md",
                       "\n".join(body) + "\n")

        # A module page is a readable review guide, not a 260-character index.
        # All source summaries are retained; interpretation remains attributed.
        for module, entries in module_map.items():
            by_lesson = defaultdict(list)
            for src, note, analysis in entries:
                by_lesson[src["lesson"] or "Aulas-Sem-Numero"].append((src, note, analysis))
            body = [_frontmatter(tipo="modulo", fontes=len(entries),
                                 estado="sintese_de_fontes_nao_revisada"),
                    f"# {module.replace('-', ' ')}", "",
                    "> Guia de revisão gerado a partir das fontes analisadas. "
                    "A classificação do módulo é automática por palavras-chave; "
                    "confira se cada aula realmente pertence a ele. "
                    "As explicações abaixo vêm de análises por IA e precisam de conferência com o professor.",
                    "", "## Percurso das aulas", ""]
            for lesson in sorted(by_lesson, key=lesson_order):
                recordings = sorted(by_lesson[lesson],
                                    key=lambda item: (item[0]["video"] or "", item[0]["label"]))
                if lesson != "Aulas-Sem-Numero":
                    body.append(f"### [[02-Minhas-Aulas/{lesson}/00-Visao-geral|{lesson}]]")
                else:
                    body.append("### Aulas ainda sem número identificado")
                body.append("")
                for src, note, analysis in recordings:
                    link = Path(note).with_suffix("").as_posix()
                    body.append(f"#### [[{link}|{_escape_md(src['label'])}]]")
                    if not analysis:
                        body.extend(["", "*Transcrição importada; resumo pendente de IA.*", ""])
                        continue
                    summary = str(analysis.get("resumo", "")).strip()
                    body.extend(["", summary if summary else "*Resumo pendente.*", ""])
                    examples = analysis.get("exemplos", [])
                    if examples:
                        body.extend(["**Exemplos relatados na aula:**", ""])
                        for example in examples:
                            body.append(f"- {_escape_md(example)}")
                    doubts = analysis.get("duvidas", [])
                    if doubts:
                        body.extend(["", "**Passagens a conferir:**", ""])
                        for doubt in doubts:
                            body.append(f"- {_escape_md(doubt)}")
                    body.append("")
            body += ["", "## Conceitos e explicações encontrados nas fontes", "",
                     "> Termos e explicações extraídos pela IA, não certificação de que foram ensinados.", ""]
            seen = set()
            for src, note, analysis in entries:
                if not analysis:
                    continue
                raw = (self.vault / src["stored_path"]).read_text(
                    encoding="utf-8-sig", errors="replace")
                valid_times = {t for t, _ in timed_lines(raw) if t != "sem horário"}
                for concept in analysis.get("conceitos", []):
                    name = str(concept.get("nome", "")).strip()
                    if not name:
                        continue
                    explanation = str(concept.get("explicacao", "")).strip()
                    stamp = str(concept.get("tempo", "")).strip()
                    key = (src["id"], concept_slug(name), stamp, explanation.casefold())
                    if key in seen:
                        continue
                    seen.add(key)
                    note_path = Path(note).with_suffix("").as_posix()
                    where = (f"[[{note_path}#^{_time_id(stamp)}|{src['lesson']} · {stamp}]]"
                             if stamp in valid_times else
                             f"[[{note_path}|{src['lesson'] or src['label']}]]")
                    literal = "termo literal presente" if _term_in_source(name, raw) else "termo inferido pela IA"
                    body.append(f"- **[[{concept_slug(name)}|{_escape_md(name)}]]**: "
                                f"{_escape_md(explanation)} — {where} ({literal}).")
            if not seen:
                body.append("*Nenhum conceito extraído ainda; o resumo por gravação permanece disponível.*")
            body += ["", "## Projetos e documentação relacionados", ""]
            project_found = False
            for repo, payload in repo_info:
                docs = [d for d in payload.get("documentation", [])
                        if module in guess_modules(d["path"] + " " + d["excerpt"])]
                if not docs:
                    continue
                project_found = True
                body.append(f"- [[{slug(repo['name'])}-{repo['sha'][:7]}|{_escape_md(repo['name'])}]] — "
                            + ", ".join(f"`{_escape_md(d['path'])}`" for d in docs[:4])
                            + "; documentação existente no repositório, não necessariamente conteúdo da aula")
            if not project_found:
                body.append("*Nenhuma documentação de repositório associada a este módulo.*")
            body += ["", "## Como revisar", "",
                     "1. Leia o resumo de cada gravação e abra a nota para ver as fontes.",
                     "2. Compare conceitos e exemplos com os trechos de transcrição e o código.",
                     "3. Registre dúvidas em suas notas pessoais; este índice não altera fontes originais."]
            self.write(f"01-Meu-Conhecimento/Modulos/{module}.md",
                       "\n".join(body) + "\n")
        # Uma linha do tempo única e auditável, produzida a partir das mesmas
        # fontes do Obsidian; não consome requisições nem deduz domínio.
        atlas = self._atlas
        self.write("01-Meu-Conhecimento/Mapa-da-Evolucao.md", render_atlas(atlas))
        doubts_index, doubts_notes = render_uncertainties(self.db)
        for relative, note_text in doubts_notes:
            self.write(relative, note_text)
        self.write("01-Meu-Conhecimento/Indice-de-Duvidas.md", doubts_index)
        context = ["# MEU_CONTEXTO — Guia para IA", "",
                   "> Este documento resume **o que foi abordado nos materiais**, não comprova domínio pessoal.",
                   "> Use as notas vinculadas como evidência antes de recomendar recursos de programação.", "",
                   "## Módulos vistos nos materiais", "", "- [[Mapa-da-Evolucao|Mapa de evolução com horários e código]]"]
        context += [f"- [[{m}|{m.replace('-', ' ')}]]: {len(entries)} fonte(s)" for m,entries in module_map.items()]
        context += ["", "## Dúvidas e interpretações pendentes",
                    "- [[Indice-de-Duvidas|Índice rastreável de dúvidas e evidências posteriores]]",
                    "> Evidências posteriores são pistas, nunca correções confirmadas automaticamente.",
                    "", "## Conceitos encontrados"]
        context += [f"- [[{k}|{_escape_md(v[0][0])}]] — identificado pela IA; confirmar na fonte" for k,v in sorted(concept_map.items())]
        context += ["", "## Evolução: antes na aula, agora no código"]
        for repo,payload in repo_info:
            matches=[]
            for src,note in lesson_links:
                raw=(self.vault/src["stored_path"]).read_text(encoding="utf-8-sig",errors="replace")
                analysis=self.db.analysis(src["id"],src["digest"])
                ev=match_lesson_to_repository(raw,analysis,payload,cap=3)
                if ev:
                    matches.append((src,note,ev))
            if matches:
                context.append(f"- **{repo['name']}:** " + "; ".join(
                    f"[[{Path(n).stem}|{src['lesson'] or src['label']}]] aborda "
                    + ", ".join(f"`{e['concept']}`" for e in ev) for src,n,ev in matches[:5])
                    + f"; trechos observados em [[{slug(repo['name'])}-{repo['sha'][:7]}|{repo['name']}]]. "
                    + "*Associação candidata, não prova de quem implementou ou quando.*")
        context += ["", "## Pessoas mencionadas nas fontes", ""]
        context += [f"- [[{k}|{_escape_md(v[0][0])}]] — {len(v)} fonte(s); contexto/identidade a conferir" for k,v in sorted(person_map.items())]
        context += ["", "## Aulas sem transcrição ou código", ""]
        context += [f"- [[00-contexto-{slug(lesson)}|{lesson}]] — contexto registrado" for lesson in sorted({s['lesson'] for s in self.db.sources() if s['lesson']} - transcripts_by_lesson)]
        context += ["", "## Projetos analisados"]
        context += [f"- {r['name']} — `{r['sha'][:10]}` (código observado; autoria e domínio não presumidos)" for r,_ in repo_info]
        context += ["", "## Orientações para a IA", "- Antes de explicar, consulte os conceitos, aulas e projetos relevantes.",
                    "- Priorize técnicas comprovadamente vistas nas fontes; pergunte antes de usar algo novo.",
                    "- Diferencie o que foi ensinado, o que consta no GitHub e o que eu demonstrei dominar.",
                    "- Se não houver evidência, diga que não encontrou; não invente domínio.",
                    "- Para quebra-cucas, oriente em pequenas etapas e evite solução completa sem pedido."]
        self.write("00-Inicio/MEU_CONTEXTO.md", "\n".join(context)+"\n")
        index = ["# Minha Biblioteca", "", "## Comece aqui", "- [[MEU_CONTEXTO]] — contexto para IAs", "",
                 "## Conhecimentos", "- [[Mapa-da-Evolucao|Mapa de evolução do aprendizado]]",
                 "- [[Indice-de-Duvidas|Dúvidas e referências para revisão]]"]
        index += [f"- [[{module}|{module.replace('-', ' ')}]]" for module in module_map]
        index += ["", "## Aulas — abra a visão geral para reunir V01, V02 e demais materiais"]
        index += [f"- [[02-Minhas-Aulas/{lesson}/00-Visao-geral|{lesson} — visão geral]]" for lesson in all_lessons]
        for lesson in sorted({s['lesson'] for s in self.db.sources() if s['lesson']} - transcripts_by_lesson):
            index.append(f"- [[00-contexto-{slug(lesson)}|{lesson}]] — contexto sem transcrição")
        index += [f"- [[{Path(note).stem}|{src['label']}]] — gravação e transcrição" for src,note in lesson_links]
        index += ["", "## Projetos"]
        index += [f"- [[{slug(repo['name'])}-{repo['sha'][:7]}|{repo['name']}]] — {repo['url']}" for repo,_ in repo_info]
        index += ["", "> A aplicação não altera conteúdo de `05-Anotacoes-Pessoais`."]
        self.write("00-Inicio/Dashboard.md", "\n".join(index)+"\n")
        states = defaultdict(int)
        for src in self.db.sources():
            states[src["status"]] += 1
        self.write("90-Sistema/Processamento.md", "# Status do processamento\n\n" +
                   "\n".join(f"- **{status}:** {count}" for status,count in sorted(states.items())) + "\n")
        return {"aulas":len({s["lesson"] for s in self.db.sources() if s["lesson"]}), "conceitos":len(concept_map), "pessoas":len(person_map), "projetos":len(repo_info)}
