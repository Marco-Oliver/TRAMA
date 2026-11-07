"""Mapa temporal rastreável das três camadas do TRAMA.

Não usa IA nem deduz domínio/autoria: reúne afirmações de análises existentes,
confere se a âncora citada realmente existe e mostra a fonte original.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from .content import slug, concept_slug, concept_file_slug, timed_lines


def norm(value: object) -> str:
    txt = unicodedata.normalize('NFKD', str(value)).encode('ascii','ignore').decode().casefold()
    txt = txt.replace('++', ' plus plus ').replace('#', ' sharp ').replace('+', ' plus ')
    return re.sub(r'[^a-z0-9]+', ' ', txt).strip()


def literal_technical_mention(label: str, source: str) -> str:
    """Return an actually present rendering of a technical name, or empty.

    The model may label 'SDK (Software Development Kit)' when speech only says
    'SDK', or 'Comando dotnet --version' when speech says 'dotnet --version'.
    Both are literal terms, but expanding their explanations remains an
    unverified interpretation. This intentionally does NOT fuzzy-correct
    'exaust map' to 'exhaustMap' or infer a concept from source code alone.
    """
    if not isinstance(label, str) or not isinstance(source, str):
        return ""
    label = label.strip()[:120]
    if not label:
        return ""
    candidates = [label]
    parenthesized = re.fullmatch(r"(.{2,75}?)\s+\(([^()]{3,65})\)", label)
    if parenthesized:
        candidates.append(parenthesized.group(1).strip())
    for candidate in tuple(candidates):
        short = re.sub(
            r"^(?:comando|operador|função|funcao|método|metodo|classe)\s+",
            "", candidate, flags=re.I
        ).strip()
        if short != candidate:
            candidates.append(short)
    normalized_source = " " + norm(source) + " "
    for candidate in candidates:
        needle = norm(candidate)
        if needle == "c" and candidate.strip().casefold() == "c":
            # C is a real programming-language name, but must not match
            # C#, C++, variable names or words just containing the letter.
            if re.search(r"(?<![A-Za-z0-9_+#])c(?![A-Za-z0-9_+#])",
                         source, flags=re.I):
                return candidate
        elif len(needle) >= 3 and " " + needle + " " in normalized_source:
            return candidate
    return ""


def safe(value: object, limit: int = 300) -> str:
    return str(value).replace('\n', ' ').replace('\r', ' ').replace('|', '\\|')[:limit].strip()


def lesson_order(code: str) -> tuple:
    m = re.fullmatch(r'Aula-(\d+)', str(code))
    return (0, int(m.group(1))) if m else (1, str(code))


def note_for(src) -> str:
    return (f"02-Minhas-Aulas/{src['lesson'] or 'Aulas-Sem-Numero'}/"
            f"{slug(Path(src['label']).stem,52)}-{src['id'][:7]}.md")


def make_atlas(store, max_concepts: int = 2000,
               concept_targets: dict | None = None) -> dict:
    """Somente fontes catalogadas. Nenhum acesso à rede. Saída JSON serializável."""
    sources = store.sources('transcript')
    concepts: dict[str, dict] = {}
    for src in sources:
        result = store.analysis(src['id'], src['digest'])
        if not result:
            continue
        # A presentation/organizational event is not a technical learning
        # milestone even if the model listed words under 'conceitos'.
        if result.get('tipo_aula') in ('apresentacao','organizacional','atividade'):
            continue
        original = (store.vault / src['stored_path']).resolve()
        if not original.is_relative_to(store.vault) or not original.is_file():
            continue
        raw = original.read_text(encoding='utf-8-sig',errors='replace')
        segments = timed_lines(raw)
        by_timestamp = defaultdict(list)
        for timed, spoken in segments:
            if timed != 'sem horário':
                by_timestamp[timed].append(spoken)
        for row in result.get('conceitos',[]) if isinstance(result.get('conceitos'),list) else []:
            if not isinstance(row,dict):continue
            name = str(row.get('nome','')).strip()[:90]
            key = concept_slug(name)
            if (len(key)<3 and key != "c") or len(key)>90:continue
            if key not in concepts and len(concepts)>=max_concepts:continue
            stamp = str(row.get('tempo','')).strip('[]')
            stated = by_timestamp.get(stamp, [])
            literal = bool(literal_technical_mention(name, raw))
            same_time = [spoken for spoken in stated
                         if literal_technical_mention(name, spoken)]
            observed = [(timed, spoken) for timed, spoken in segments
                        if timed != 'sem horário' and
                        literal_technical_mention(name, spoken)]
            if same_time:
                resolved_time, excerpt = stamp, same_time[0]
                confidence = ('termo encontrado em horário repetido; conferir a ocorrência'
                              if len(stated) > 1 else
                              'termo encontrado no horário citado')
            elif observed:
                # The model's timestamp is missing, mistaken or belongs to a
                # different utterance. Trust the TXT for the literal mention.
                resolved_time, excerpt = observed[0]
                confidence = ('menção literal em outro horário no TXT; '
                              'horário da IA não confirma essa menção'
                              if stated else
                              'menção literal com horário recuperado do TXT')
            elif stated:
                resolved_time, excerpt = stamp, stated[0]
                confidence = ('horário informado pela IA sem menção literal '
                              'do conceito no trecho')
            else:
                resolved_time, excerpt = '', ''
                confidence = ('termo presente no TXT, mas sem horário identificável'
                              if literal else
                              'sem menção literal nem horário confirmado')
            # No label or model claim alone certifies teaching or mastery.
            rec = {'lesson':src['lesson'] or 'Sem número', 'video':src['video'] or '',
                   'source_id':src['id'], 'note':note_for(src), 'label':src['label'],
                   'timestamp':resolved_time, 'excerpt':excerpt[:250],
                   'explanation':str(row.get('explicacao',''))[:600],
                   'confidence':confidence, 'literal':literal}
            target = (concept_targets or {}).get(key, concept_file_slug(name))
            bucket = concepts.setdefault(key, {'name':name,'key':key,'slug':target,'mentions':[]})
            if not any(x['source_id']==rec['source_id'] and x['timestamp']==rec['timestamp'] for x in bucket['mentions']):
                bucket['mentions'].append(rec)
    for value in concepts.values():
        value['mentions'].sort(key=lambda r:(lesson_order(r['lesson']),r['video'],r['label']))
        prior = set()
        for row in value['mentions']:
            row['stage'] = 'primeira menção identificada' if not prior else 'retomado em outra fonte'
            if row['lesson'] in prior:row['stage']='outra gravação da mesma aula'
            prior.add(row['lesson'])
    repositories=[]
    for repo in store.repositories():
        try:payload=json.loads(repo['payload'])
        except (ValueError,TypeError):continue
        evidence=[]
        for item in payload.get('evidence',[])[:500]:
            if not isinstance(item,dict):continue
            key=concept_slug(str(item.get('concept','')))
            if key not in concepts:continue
            path=str(item.get('path',''))[:220]
            line=item.get('line',0)
            if not path or not isinstance(line,int) or line<1:continue
            evidence.append({'key':key,'name':concepts[key]['name'],'path':path,'line':line,
                             'snippet':str(item.get('snippet',''))[:800]})
        if evidence:
            repositories.append({'name':repo['name'],'sha':repo['sha'],'url':repo['url'],
                                 'evidence':evidence[:60],
                                 'authors_count':len(set(h.get('author') for h in payload.get('history',[]) if isinstance(h,dict)))})
    return {'concepts':sorted(concepts.values(),key=lambda c:(lesson_order(c['mentions'][0]['lesson']),c['name'].casefold())),
            'repos':repositories,'lessons':sorted({s['lesson'] for s in store.sources() if s['lesson']},key=lesson_order)}


def render_atlas(atlas: dict) -> str:
    out=['# Mapa da evolução do conhecimento','',
         '> **Como ler:** este mapa foi gerado a partir das fontes cadastradas. '
         'A ordem é pelo número das aulas, não comprova a data em que o aluno aprendeu ou dominou um conceito.',
         '> **Importante:** correspondências de código são candidatas; não comprovam autoria individual ou quando o trecho foi implementado.',
         '', '## Trajetória por conceito','']
    if not atlas['concepts']:out.append('*Sem conceitos analisados ainda. Aulas introdutórias continuam na seção Minhas Aulas.*')
    for c in atlas['concepts']:
        out += [f"### [[{c['slug']}|{safe(c['name'],90)}]]", '']
        for row in c['mentions'][:40]:
            caption=f"[[{Path(row['note']).stem}|{safe(row['lesson'])} {safe(row['video'])}]]"
            stamp=f" · {row['timestamp']}" if row['timestamp'] else ''
            out.append(f"- **{row['stage']}**: {caption}{stamp} — {row['confidence']}.")
            if row['excerpt']:
                out.append(f"  - Fala no horário citado: “{safe(row['excerpt'],210)}”")
        for repo in atlas['repos']:
            items=[e for e in repo['evidence'] if e['key']==c['key']]
            if items:
                e=items[0]
                out.append(f"- **Código relacionado (candidato):** {safe(repo['name'])}, "
                           f"`{safe(e['path'])}:{e['line']}` no commit `{safe(repo['sha'][:12])}`. "
                           'O trecho existe no índice Git; autoria e data de uso em aula não confirmadas.')
        out.append('')
    out += ['## Limites desta análise','',
            '- Primeira menção identificada significa primeira entre as fontes **já importadas**, não necessariamente primeira aula do curso.',
            '- Um conceito só entra no mapa quando uma análise de aula o reconheceu; uma simples coincidência de palavras não comprova aplicação.',
            '- A IA pode classificar um conceito errado; consulte a fala original e as evidências antes de aceitar a interpretação.',
            '- Este mapa pode ser reconstruído a qualquer momento sem novas chamadas de API.']
    return '\n'.join(out)+'\n'


def related_prior(store, lesson: str, text: str, limit: int = 5) -> str:
    """Contexto anterior pequeno e rastreável para o prompt, sem consumir IA extra."""
    needle=norm(text)
    if not needle:return ''
    hits=[]
    for src in store.sources('transcript'):
        if not src['lesson'] or lesson_order(src['lesson']) >= lesson_order(lesson):continue
        result=store.analysis(src['id'],src['digest'])
        if not result:continue
        for c in result.get('conceitos',[]) if isinstance(result.get('conceitos'),list) else []:
            key=norm(c.get('nome','')) if isinstance(c,dict) else ''
            if len(key)<4 or (' '+key+' ') not in (' '+needle+' '):continue
            hits.append((lesson_order(src['lesson']),src['lesson'],str(c.get('nome',''))[:80],
                         str(c.get('explicacao',''))[:170],str(c.get('tempo',''))[:12]))
    # Relevância é mais forte que recência; uma entrada por par aula-conceito.
    seen=set();chosen=[]
    for _, previous, name, expl, stamp in sorted(hits,reverse=True):
        key=(previous,norm(name))
        if key in seen:continue
        seen.add(key);chosen.append(f'{previous}, {name}, {stamp or "sem horário"}: {expl}')
        if len(chosen)>=limit:break
    return ('Fontes anteriores relacionadas, referências apenas (não assuma domínio):\n'
            + '\n'.join(chosen)) if chosen else ''
