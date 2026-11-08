"""Entrada única, incremental e auditável: arquivos + links -> fontes -> três camadas.

Não lê Classroom automaticamente e não baixa vídeos. A IA só recebe materiais após
consentimento explícito; respostas de imagens são hipóteses com proveniência.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import json
import mimetypes
import re
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from defusedxml import ElementTree

from .ai import BudgetStopped, NoFreeProvider, ProviderError
from .classroom import lesson_number, normalize_context
from .classroom_paste import parse_import_paste
from .academy_material import AcademyDocs, official_route
from .content import lesson_identity
from .pipeline import Application, MATERIAL_EXTS, TEXT_EXTS, VIDEO_EXTS

SUPPORTED = MATERIAL_EXTS | TEXT_EXTS
VISUAL = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
          '.webp': 'image/webp', '.pdf': 'application/pdf'}
MAX_FILES = 100
MAX_VISUAL_BYTES = 6 * 1024 * 1024


def _lesson_from_text(value: str) -> str | None:
    lesson, _ = lesson_identity(value)
    return lesson


def parse_link_rows(value: str) -> list[dict]:
    """Preserva links completos e títulos: Aula 01 | V02 - Tema | URL.

    Aula é a publicação do Classroom; V01, V02, V03 são gravações da MESMA
    aula quando o rótulo assim identifica. Não inventa número por ordem.
    """
    if not isinstance(value, str) or len(value) > 20000:
        raise ValueError('Cole até 20 mil caracteres de links por lote.')
    results = []
    for row in value.splitlines():
        row = row.strip()
        if not row:
            continue
        if '|' in row:
            label, url = (x.strip() for x in row.rsplit('|', 1))
        else:
            label, url = '', row
        if len(url) > 1700 or any(c.isspace() for c in url) or any(c in url for c in '<>\\'):
            raise ValueError('Link inválido; cole uma URL completa em cada linha.')
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password:
            raise ValueError('Os links devem ser HTTPS, sem credenciais.')
        # Os endereços são apenas armazenados, não executados automaticamente.
        is_repo = bool(re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+(?:\.git)?/?', url, re.I))
        lesson = _lesson_from_text(label) or _lesson_from_text(parts.path)
        results.append({'url':url,'label':label[:160], 'lesson':lesson,
                        'repo':is_repo,'video':parts.hostname in ('drive.google.com', 'meet.google.com')})
    if len(results) > 80:
        raise ValueError('Máximo de 80 links por lote.')
    return list({entry['url']:entry for entry in results}.values())


def _plain_document(path: Path) -> str:
    """Extrai DOCX localmente, sem API; não interpreta imagens incluídas nele."""
    if path.suffix.lower() != '.docx':
        return ''
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > 2_000_000:
                return ''
            xml = archive.read(info)
        root = ElementTree.fromstring(xml)
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        return '\n'.join(''.join(x.text or '' for x in p.iter(ns+'t'))
                         for p in root.iter(ns+'p'))[:12000]
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return ''


def clean_visual_result(value: dict) -> dict:
    """Resultado sugerido pela IA: validação estrutural e de URL, sem confiança falsa."""
    if not isinstance(value, dict):
        raise ValueError('Resposta da IA inválida.')
    def string(key: str, limit: int) -> str:
        item = value.get(key)
        return item.strip()[:limit] if isinstance(item, str) else ''
    lesson_value = value.get('aula', 0)
    lesson = None
    try:
        if lesson_value not in (0, '', None, '0'):
            lesson = lesson_number(str(lesson_value))
    except ValueError:
        pass
    date = string('data',25)
    if date and not re.fullmatch(r'\d{2}/\d{2}/\d{4}', date):
        date = ''
    people = value.get('pessoas', [])
    activities = value.get('atividades', [])
    def rows(items: object) -> str:
        if not isinstance(items, list):return ''
        return '\n'.join(x.strip()[:250] for x in items[:20] if isinstance(x, str) and x.strip())
    raw_links = value.get('links', [])
    valid_links = []
    if isinstance(raw_links,list):
        for url in raw_links[:20]:
            if isinstance(url,str):
                try:
                    entry = parse_link_rows(url)
                    if entry:valid_links.append(entry[0]['url'])
                except ValueError:
                    pass
    videos = value.get('videos', [])
    video_lines=[]
    if isinstance(videos,list):
        for v in videos[:20]:
            if isinstance(v,dict):
                url=v.get('url')
                if isinstance(url,str):
                    try:
                        parsed=parse_link_rows(url)
                    except ValueError:
                        parsed=[]
                    if parsed:
                        video_lines.append(f"{str(v.get('titulo') or 'Gravação')[:130]} | {url}")
    return {'aula':lesson,'titulo':string('titulo',220),'data':date,
            'descricao':string('descricao',12000) or string('resumo',1200),
            'pessoas':rows(people),'atividades':rows(activities),
            'links':'\n'.join(valid_links),'videos':'\n'.join(video_lines),
            'incertezas':rows(value.get('incertezas',[]))}


class AutoOrganizer:
    def __init__(self, app: Application, log=print):
        self.app = app
        self.log = log

    def _source_for(self, path: Path):
        return next((s for s in self.app.store.sources() if s['original_path'].casefold()==str(path.resolve()).casefold()),None)

    def _save_extracted(self, source, lesson: str, data: dict, *, reason: str) -> bool:
        """Nota automática separada da manual: não sobrescreve Contexto +."""
        payload = normalize_context({'aula':lesson,'titulo':data.get('titulo',''),
             'data':data.get('data',''),'descricao':data.get('descricao',''),
             'pessoas':data.get('pessoas',''),'atividades':data.get('atividades',''),
             'links':data.get('links',''),'videos':data.get('videos','')})
        if data.get('_pasted_classroom'):
            payload['origem']='Post do Classroom colado pelo usuário (não verificado automaticamente)'
            payload['autor']=str(data.get('autor',''))[:100]
            payload['gravacoes']=[str(x)[:160] for x in data.get('gravacoes',[])[:30]
                                   if isinstance(x,str) and re.fullmatch(
                                       r'A\d+\s*[-–—]\s*V\d+\s*[-–—]\s*.+',
                                       x.strip(),re.I)]
        else:
            payload['origem']='Extração por IA (hipótese, não verificada): '+reason
        payload['arquivo_fonte']=source['stored_path'] if source is not None else ''
        if data.get('incertezas'):
            payload['incertezas']=data['incertezas'][:2000]
        folder=self.app.store.vault/'99-Anexos'/'Contexto-Classroom'
        folder.mkdir(parents=True,exist_ok=True)
        src_id=source['id'] if source is not None else hashlib.sha256(reason.encode()).hexdigest()[:24]
        rel=f'99-Anexos/Contexto-Classroom/{lesson}-auto-{src_id}.json'
        path=self.app.store.vault/rel
        raw=(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode()
        digest=hashlib.sha256(raw).hexdigest()
        if data.get('_pasted_classroom'):
            # An earlier version of this *same post* must not be overwritten
            # silently. Links and other Classroom sources are independent.
            prior=self.app.store.get_source('autoctx-'+src_id)
            if prior and prior['digest']!=digest:
                return False
        if path.exists() and path.read_bytes()!=raw:
            # Guardar histórico dos dados extraídos antes de substituí-los.
            archive=folder/'Historico';archive.mkdir(exist_ok=True)
            old=path.read_bytes();old_hash=hashlib.sha256(old).hexdigest()
            old_file=archive/f'{lesson}-auto-{src_id}-{old_hash[:12]}.json'
            if not old_file.exists():old_file.write_bytes(old)
        if not path.exists() or path.read_bytes()!=raw:
            result = self.app.publisher.write(rel,raw.decode())
            if result == 'manual-protected':
                self.log(f'Nota de contexto preservada após edição humana: {rel}')
                return False
        return self.app.store.upsert_source(dict(id='autoctx-'+src_id,
                original_path='auto-context:'+src_id,kind='classroom',digest=digest,
                label=f'Contexto extraído ({lesson})',lesson=lesson,video='',stored_path=rel))

    def _assign(self, source, lesson: str):
        if source and source['lesson'] != lesson:
            self.app.store.upsert_source(dict(id=source['id'],original_path=source['original_path'],
                kind=source['kind'],digest=source['digest'],label=source['label'],
                lesson=lesson,video=source['video'],stored_path=source['stored_path']))

    def _save_pending(self, messages: list[str]):
        """Guardar pendências do lote sem apagar pendências de tentativas anteriores."""
        folder=self.app.store.vault/'90-Sistema'
        folder.mkdir(exist_ok=True)
        file=folder/'TRAMA-Importacoes-Pendentes.json'
        try:
            existing=json.loads(file.read_text(encoding='utf-8')) if file.exists() else []
            if not isinstance(existing,list):existing=[]
        except (ValueError,OSError):existing=[]
        old={x.get('id') for x in existing if isinstance(x,dict)}
        for msg in messages[:120]:
            digest=hashlib.sha256(msg.encode()).hexdigest()[:20]
            if digest in old:continue
            existing.append({'id':digest,'registrado_em':datetime.now(timezone.utc).isoformat(),
                             'pendencia':msg[:1800],'situacao':'a_revisar'})
            old.add(digest)
        file.write_text(json.dumps(existing[-500:],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    def run(self, paths: list[Path], links_text: str, *, authorized: bool) -> dict:
        if not authorized:
            raise ValueError('Confirme antes de enviar prints/transcrições à IA externa.')
        if len(paths)>MAX_FILES:raise ValueError('Selecione até 100 arquivos por lote.')
        pasted=parse_import_paste(links_text)
        links=pasted['links']
        outcome={'files':0,'visual_analyzed':0,'lessons':[], 'repositories':0,
                 'classroom_posts':0,
                 'pending':list(pasted['warnings']), 'errors':[], 'calls':0, 'processed':False}
        seen_lessons={post['aula'] for post in pasted['posts']}
        fresh_lessons=set()
        candidates=[]
        for path in paths:
            path=Path(path).expanduser()
            if path.is_symlink():
                outcome['errors'].append(path.name+': link simbólico recusado por segurança.')
                continue
            path=path.resolve()
            if path.suffix.lower() in VIDEO_EXTS:
                outcome['pending'].append(path.name+': vídeo não copiado; informe o link.')
                continue
            if path.suffix.lower() not in SUPPORTED:
                outcome['pending'].append(path.name+': formato ainda não reconhecido.')
                continue
            try:
                changed=self.app.add_file(path)
                if changed:outcome['files']+=1
                source=self._source_for(path)
                if not source:continue
                if source['lesson']:
                    seen_lessons.add(source['lesson'])
                    if changed and source['kind']=='transcript':
                        fresh_lessons.add(source['lesson'])
                if path.suffix.lower() in MATERIAL_EXTS:
                    candidates.append((path,source))
            except (OSError,ValueError) as exc:
                outcome['errors'].append(path.name+': '+str(exc)[:160])
        for entry in links:
            if entry['lesson']:seen_lessons.add(entry['lesson'])
        used_images=0
        for path,source in candidates:
            data=None
            # Cache pelo digest, mesmo se o usuário reenviar a imagem.
            cache=self.app.store.analysis(source['id'],source['digest'])
            if isinstance(cache,dict) and cache.get('_auto_visual'):
                data=cache
            elif path.suffix.lower() in VISUAL:
                if 'gemini' not in self.app.ai.active():
                    # A fonte pode ser vinculada por filename/lote sem alegar leitura do print.
                    guess = source['lesson'] or (next(iter(seen_lessons)) if len(seen_lessons)==1 else None)
                    if guess:
                        self._assign(source,guess)
                        outcome['pending'].append(path.name+': vinculado a '+guess+' por nome/lote, mas imagem ainda não lida pela IA.')
                    else:
                        outcome['pending'].append(path.name+': chave Gemini Free ausente ou cota bloqueada; fonte preservada.')
                    continue
                if path.stat().st_size>MAX_VISUAL_BYTES:
                    outcome['pending'].append(path.name+': arquivo maior que 6 MB; salvo, análise visual pendente.')
                    continue
                try:
                    result=self.app.ai.read_classroom_material(VISUAL[path.suffix.lower()],
                                path.read_bytes(),path.name)
                    data=clean_visual_result(result.payload)
                    data['_auto_visual']=True
                    self.app.store.save_analysis(source['id'],source['digest'],result.provider,result.model,data)
                    outcome['visual_analyzed']+=1
                except (NoFreeProvider,BudgetStopped,ProviderError,ValueError) as exc:
                    outcome['pending'].append(path.name+': análise visual pendente ('+str(exc)[:90]+').')
                    continue
            elif path.suffix.lower()=='.docx':
                text=_plain_document(path)
                if text:
                    # DOCX está preservado e anexado; sua extração estruturada fica pendente
                    # se não houver número explícito no nome.
                    data={'titulo':path.stem,'descricao':text,'pessoas':'','atividades':'',
                          'links':'','videos':'','data':'','incertezas':'Documento local sem classificação por IA.'}
            if not data:continue
            extracted=data if data.get('_auto_visual') else clean_visual_result(data) if isinstance(data.get('aula'),int) else data
            lesson=extracted.get('aula') or source['lesson']
            if lesson and source['lesson'] and lesson!=source['lesson']:
                outcome['pending'].append(path.name+': número da aula difere entre imagem e nome; revisar.')
                continue
            if not lesson and len(seen_lessons)==1:
                lesson=next(iter(seen_lessons))
                extracted['incertezas']=(extracted.get('incertezas','')+'\nAssociação sugerida por lote único.').strip()
            if not lesson:
                outcome['pending'].append(path.name+': não foi possível identificar a aula com segurança.')
                continue
            seen_lessons.add(lesson)
            self._assign(source,lesson)
            try:
                self._save_extracted(source,lesson,extracted,reason=path.name)
            except (ValueError,OSError) as exc:
                outcome['pending'].append(path.name+': contexto incompleto ('+str(exc)[:100]+').')
        # Pasted posts have their own stable source/file identity. A context
        # created only from links (or manual Contexto +) never blocks a post.
        # _save_extracted guards edits to that exact post and publisher.write
        # protects user-edited files.
        for post in pasted['posts']:
            lesson=post['aula']
            post_id=hashlib.sha256(
                ('classroom-post:'+lesson+':'+post['titulo'].casefold()).encode()
            ).hexdigest()[:24]
            synthetic={'id':post_id,'stored_path':'(post do Classroom colado)'}
            data={**post,'_pasted_classroom':True}
            try:
                if self._save_extracted(synthetic,lesson,data,reason='Post copiado do Classroom'):
                    outcome['classroom_posts']+=1
                else:
                    outcome['pending'].append(lesson+': contexto já existente ou protegido; não sobrescrito.')
            except (ValueError,OSError) as exc:
                outcome['pending'].append(lesson+': post do Classroom para revisão ('+str(exc)[:100]+').')
            if lesson not in fresh_lessons and any(
                    row['lesson']==lesson for row in self.app.store.sources('transcript')):
                outcome['pending'].append(
                    lesson+': Contexto registrado sem alterar a análise anterior; '
                    'reprocesse a aula para a IA usar.')
        # Links sem identificação são vinculados somente se existir uma aula única.
        by_lesson={}
        unassigned_docs=None
        docs_suggestion_paused=False
        for entry in links:
            if entry['repo']:
                try:
                    outcome['repositories']+=int(self.app.add_repo(entry['url']))
                except (OSError,ValueError,RuntimeError) as exc:
                    outcome['pending'].append('GitHub '+entry['url']+': '+str(exc)[:100])
                continue
            lesson=entry['lesson'] or (next(iter(seen_lessons)) if len(seen_lessons)==1 else None)
            if lesson is None:
                if official_route(entry['url']) is not None and not docs_suggestion_paused:
                    try:
                        if unassigned_docs is None:
                            unassigned_docs=AcademyDocs(self.app.store)
                        guess=unassigned_docs.suggest_unassigned_lesson(entry['url'])
                        if guess:
                            candidate,reason=guess
                            outcome['pending'].append(
                                'Link oficial sem aula: provável '+candidate+
                                ' ('+reason+'). Confirme reenviando como '+
                                candidate.replace('-', ' ')+ ' | '+entry['url'])
                            continue
                    except (OSError,ValueError,RuntimeError) as exc:
                        docs_suggestion_paused=True
                        outcome['pending'].append(
                            'Sugestão de aula pausada por acesso/cota GitHub; '+
                            'tente novamente depois. '+str(exc)[:120])
                outcome['pending'].append('Link sem aula identificada: '+entry['url'])
                continue
            by_lesson.setdefault(lesson,[]).append(entry)
        for lesson, items in by_lesson.items():
            # Um registro estável por aula evita multiplicar notas a cada
            # lote; mescla gravações novas com as já cadastradas.
            src_id=hashlib.sha256(('links:'+lesson).encode()).hexdigest()[:24]
            previous=self.app.store.vault/'99-Anexos'/'Contexto-Classroom'/f'{lesson}-auto-{src_id}.json'
            old_links=[];old_videos=[]
            if previous.exists():
                try:
                    old=json.loads(previous.read_text(encoding='utf-8'))
                    if isinstance(old.get('links'),list):old_links=old['links']
                    if isinstance(old.get('videos'),list):old_videos=old['videos']
                except (ValueError,OSError,TypeError):pass
            text_links=list(old_links)
            videos={v['url']:v for v in old_videos if isinstance(v,dict) and isinstance(v.get('url'),str)}
            for item in items:
                if item['video']:
                    # O rótulo pode ser "Aula 01 | V02 | URL". Preservar V02.
                    label=item['label'].split('|')[-1].strip() or 'Gravação'
                    videos[item['url']]={'titulo':label,'url':item['url']}
                elif item['url'] not in text_links:
                    text_links.append(item['url'])
            data={'titulo':'','descricao':'','pessoas':'','atividades':'','data':'',
                  'links':'\n'.join(text_links),
                  'videos':'\n'.join(v['titulo']+' | '+v['url'] for v in videos.values()),
                  'incertezas':'Links atribuídos à aula por referência explícita ou por lote com aula única.'}
            synthetic={'id':src_id,'stored_path':'(URLs informadas pelo usuário)'}
            try:self._save_extracted(synthetic,lesson,data,reason='Links fornecidos no lote')
            except (ValueError,OSError) as exc:outcome['pending'].append(f'{lesson}: {exc}')
        # The Academy docs are a THIRD source: freeze the official Git SHA
        # once per lesson and link only .md files at that immutable revision.
        # Network is solely GitHub's read-only source, never an AI endpoint.
        official=[(lesson,entry["url"])
                  for lesson,entries in by_lesson.items() for entry in entries
                  if official_route(entry["url"]) is not None]
        if official:
            resolver=AcademyDocs(self.app.store)
            for lesson,url in list(dict.fromkeys(official))[:60]:
                try:
                    created,notice=resolver.attach(lesson,url)
                    if not created:
                        outcome["pending"].append(lesson+": "+notice)
                except (OSError,ValueError,RuntimeError) as exc:
                    outcome["pending"].append(
                        lesson+": material oficial indisponível no SHA fixado ("+
                        str(exc)[:140]+"). Link preservado.")
            if len(official)>60:
                outcome["pending"].append("Limite de 60 URLs oficiais por lote; restantes não vinculadas.")
        # Version association does not require an AI provider or user-by-user
        # Git mapping; operate after all TXT and repository links are imported.
        automatic = self.app.assign_github_versions()
        outcome['automatic_versions'] = automatic.get('mapped', 0)
        outcome['pending'].extend(automatic.get('pending', []))
        if fresh_lessons and self.app.ai.active():
            # Never silently reprocess existing older lessons due to a pasted
            # Classroom post or unrelated new source. Explicit reprocess is a
            # separate user action.
            self.app.process(lesson_filters=fresh_lessons)
            outcome['processed']=True
            waiting=[row['label'] for row in self.app.store.sources('transcript')
                     if row['lesson'] in fresh_lessons and
                     row['status'] in ('WAITING_FOR_PROVIDER','NEEDS_REVIEW')]
            if waiting:
                outcome['pending'].append(f'{len(waiting)} transcrição(ões) pendente(s) por limite da IA ou falha: '+', '.join(waiting[:3]))
        else:
            self.app.publisher.rebuild()
        outcome['lessons']=sorted(seen_lessons)
        if outcome['pending'] or outcome['errors']:
            self._save_pending([*outcome['pending'],*outcome['errors']])
        outcome['calls']=self.app.ai.attempts
        return outcome
