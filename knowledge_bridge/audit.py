"""Conferência local de evidências, sem IA externa nem modificação de arquivos.

Verifica integridade e rastreabilidade; NÃO certifica a interpretação semântica
produzida por modelos generativos. O vídeo não é baixado nem transcrito.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from .content import timed_lines
from .memory_atlas import literal_technical_mention


def _normalize(text):
    value = unicodedata.normalize('NFKD', str(text)).encode('ascii','ignore').decode().casefold()
    return re.sub(r'[^a-z0-9]+',' ', value).strip()


def audit_lesson(vault: Path, lesson: str) -> dict:
    """Return concise, bounded offline checks for the evidence of one lesson.

    Never uses web, secret keys or writes to the vault.  Read only SQL, closed
    explicitly so Windows will not keep SQLite files locked.
    """
    path = vault.expanduser().resolve()
    db = path / '.base-conhecimento' / 'estado.sqlite3'
    if not re.fullmatch(r'Aula-\d{3,4}', str(lesson)):
        return {'ok':False, 'message':'Esta nota não é de uma aula numerada.'}
    if not db.is_file():
        return {'ok':False, 'message':'Ainda não há catálogo de fontes para esta aula.'}
    try:
        with closing(sqlite3.connect(f'file:{quote(db.as_posix())}?mode=ro', uri=True, timeout=2)) as con:
            con.row_factory=sqlite3.Row
            sources=con.execute('SELECT * FROM sources WHERE lesson=? ORDER BY kind,label', (lesson,)).fetchall()
            if not sources:return {'ok':False,'message':'Esta aula não possui fontes cadastradas no TRAMA.'}
            analyses={r['source_id']:r for r in con.execute('SELECT * FROM analyses') if r['source_id'] in {s['id'] for s in sources}}
            findings=[]
            counters={'transcricoes':0,'com_resumo':0,'contextos':0,'materiais':0,'videos_links':0,
                      'horarios_validos':0,'horarios_recuperados_txt':0,
                      'referencias_duvidosas':0,'arquivos_integros':0}
            for src in sources:
                if src['kind']=='classroom':
                    counters['contextos']+=1
                    file=(path/src['stored_path']).resolve()
                    if not file.is_relative_to(path) or not file.is_file():
                        findings.append('O contexto do Classroom não está disponível no cofre.')
                        continue
                    try:
                        record=json.loads(file.read_text(encoding='utf-8'))
                        counters['videos_links']+=len([item for item in record.get('videos',[])
                            if isinstance(item,dict) and str(item.get('url','')).startswith(('https://','http://'))])
                    except (OSError,ValueError,UnicodeError):
                        findings.append('Uma fonte do Classroom não pôde ser lida.')
                    continue
                if src['kind']=='material':
                    counters['materiais']+=1
                if src['kind']!='transcript':continue
                counters['transcricoes']+=1
                file=(path/src['stored_path']).resolve()
                if not file.is_relative_to(path) or not file.is_file():
                    findings.append(f"Transcrição ausente: {src['label'][:100]}")
                    continue
                digest=hashlib.sha256(file.read_bytes()).hexdigest()
                if digest==src['digest']:
                    counters['arquivos_integros']+=1
                else:
                    findings.append(f"Transcrição modificada em relação ao arquivo importado: {src['label'][:80]}")
                raw=file.read_text(encoding='utf-8-sig',errors='replace')
                segments=timed_lines(raw)
                timestamps={t for t,_ in segments if t!='sem horário'}
                result=analyses.get(src['id'])
                if not result or result['digest']!=src['digest']:
                    findings.append(f"Ainda sem resumo atualizado: {src['label'][:90]}")
                    continue
                try:analysis=json.loads(result['payload'])
                except (TypeError,ValueError):
                    findings.append('Uma análise de IA não pôde ser lida.');continue
                if not str(analysis.get('resumo','')).strip():
                    findings.append('Uma análise de IA está sem resumo textual.');continue
                counters['com_resumo']+=1
                for category in ('conceitos','pessoas','atividades','ferramentas','marcos'):
                    for item in analysis.get(category,[]) if isinstance(analysis.get(category),list) else []:
                        if not isinstance(item,dict):continue
                        stamp=str(item.get('tempo','')).strip()
                        if stamp:
                            if stamp in timestamps:counters['horarios_validos']+=1
                            else:
                                counters['referencias_duvidosas']+=1
                                findings.append(f'Horário não encontrado na transcrição: {stamp[:20]}')
                        if category=='conceitos':
                            name=str(item.get('nome','')).strip()
                            if len(name)>=3:
                                literal=literal_technical_mention(name,raw)
                                if not literal:
                                    counters['referencias_duvidosas']+=1
                                    findings.append(f'Conceito sem menção literal verificável: {name[:85]}')
                                else:
                                    grounded=[t for t,line in segments
                                              if t!='sem horário' and
                                              literal_technical_mention(name,line)]
                                    if grounded and (not stamp or stamp not in grounded):
                                        counters['horarios_recuperados_txt']+=1
                                    if stamp in timestamps and not any(
                                            t==stamp and literal_technical_mention(name,line)
                                            for t,line in segments):
                                        counters['referencias_duvidosas']+=1
                                        findings.append(
                                            f'Horário informado pela IA não contém o termo literal: '
                                            f'{name[:65]} ({stamp[:20]}).'
                                        )
            if counters['transcricoes']==0:
                findings.append('Aula sem transcrição: ainda é possível registrar a agenda e as pessoas do Classroom.')
            if counters['transcricoes'] and counters['com_resumo']<counters['transcricoes']:
                findings.append('Existem gravações pendentes. Gerar Resumos poderá consumir a cota da IA gratuita.')
            if counters['contextos']==0:
                findings.append('Sem contexto do Classroom: descrições, pessoas e atividades podem estar incompletas.')
            # No automated structural test can prove a human-language summary
            # accurately reflects the full video. Preserve that limit explicitly.
            findings.append('Qualidade do texto: a conferência local não prova que o resumo reproduz corretamente a fala; revise trechos importantes no vídeo.')
            if counters['videos_links']:
                findings.append('Links de vídeo são referências; disponibilidade/permissão do Classroom não foram testadas.')
            return {'ok':True, 'aula':lesson, 'contagens':counters,
                    'pendencias':findings[:20], 'tipo':'conferencia_de_fontes_local',
                    'message':'Fontes verificadas no disco. Interpretação da IA não certificada.'}
    except (OSError, sqlite3.Error, ValueError) as exc:
        return {'ok':False,'message':'Não foi possível conferir as fontes: '+str(exc)[:130]}
