"""Bateria adversarial INDEPENDENTE da suíte de regressão.

Roda sem conta/IA/rede, com cofre descartável. Não altera dados pessoais.
Não substitui a avaliação factual com Gemini e gravações reais.
"""
from __future__ import annotations
import hashlib
from unittest.mock import patch
import io
import json
import random
import tempfile
import time
from pathlib import Path

from knowledge_bridge.content import concept_slug, lesson_identity
from knowledge_bridge.memory_atlas import make_atlas, related_prior, render_atlas
from knowledge_bridge.pipeline import Application
from knowledge_bridge.update_service import check_release, download_verified_installer, VERSION, version_tuple
from knowledge_bridge.vault_index import VaultIndex

checks=[]

def check(name, fn):
    fn(); checks.append(name)

def make_test_app():
    home=tempfile.TemporaryDirectory(prefix='trama-qa-')
    path=Path(home.name); app=Application(path/'Vault',log=lambda x: None)
    return home,app,path

def fake_transcript(app,root,lesson,video,phrase,concept,timestamp='0:08'):
    path=root/f'A{lesson:02d} - V{video:02d} - Geração aleatória.txt'
    path.write_text(f'[0:00] Apresentação inicial.\n[{timestamp}] O professor explicou {phrase}.\n[0:42] Encerramento.\n',encoding='utf8')
    app.add_file(path)
    src=next(x for x in app.store.sources('transcript') if x['label']==path.name)
    app.store.save_analysis(src['id'],src['digest'],'simulado-sem-rede','qa',{ 'resumo': 'síntese simulada, para verificar estruturas',
        'tipo_aula':'tecnica','pessoas':[],'conceitos':[{'nome':concept,'explicacao':'explicação fictícia','tempo':timestamp}],
        'atividades':[], 'ferramentas':[],'marcos':[], 'exemplos':[], 'duvidas':[]})
    return src


def repeated_out_of_order():
    home,app,root=make_test_app()
    try:
        s3=fake_transcript(app,root,117,1,'interfaces','interfaces','0:08')
        s1=fake_transcript(app,root,2,1,'interfaces','interfaces','0:08')
        s2=fake_transcript(app,root,81,1,'interfaces','interfaces','0:08')
        atlas=make_atlas(app.store)
        events=next(c['mentions'] for c in atlas['concepts'] if c['name']=='interfaces')
        assert [e['lesson'] for e in events]==['Aula-002','Aula-081','Aula-117']
        assert events[0]['stage']=='primeira menção identificada'
        assert events[2]['stage']=='retomado em outra fonte'
        assert 'Aula-002' in related_prior(app.store,'Aula-117','professor explicou interfaces')
        assert 'Aula-117' not in related_prior(app.store,'Aula-081','interfaces')
    finally: app.close();home.cleanup()


def symbols_collision():
    assert len({concept_slug('C#'), concept_slug('C++'),concept_slug('C')})==3
    assert concept_slug('C#')=='c-sharp'
    home,app,root=make_test_app()
    try:
        fake_transcript(app,root,10,1,'C#','C#')
        fake_transcript(app,root,11,1,'C++','C++')
        app.publisher.rebuild()
        assert (app.store.vault/'01-Meu-Conhecimento/Conceitos/c-sharp.md').exists()
        assert (app.store.vault/'01-Meu-Conhecimento/Conceitos/c-plus-plus.md').exists()
        assert len(make_atlas(app.store)['concepts'])==2
    finally:app.close();home.cleanup()


def fabricated_timestamp():
    home,app,root=make_test_app()
    try:
        fake_transcript(app,root,49,1,'exhaustMap','exhaustMap',timestamp='44:44')
        src=app.store.sources('transcript')[0]
        a=app.store.analysis(src['id'],src['digest']);a['conceitos'][0]['tempo']='99:99'
        app.store.save_analysis(src['id'],src['digest'],'stub','qa',a)
        atlas=make_atlas(app.store)
        mention=atlas['concepts'][0]['mentions'][0]
        assert mention['timestamp']=='' and 'sem horário' in mention['confidence']
        assert '99:99' not in render_atlas(atlas)
    finally:app.close();home.cleanup()


def protect_human_edit():
    home,app,root=make_test_app()
    try:
        fake_transcript(app,root,6,1,'interfaces','interfaces')
        app.publisher.rebuild()
        note=app.store.vault/'02-Minhas-Aulas/Aula-006/00-Visao-geral.md'
        note.write_text(note.read_text(encoding='utf-8')+'\nMinha anotação humana e irrevogável.\n',encoding='utf-8')
        app.publisher.rebuild()
        assert 'Minha anotação humana e irrevogável.' in note.read_text(encoding='utf-8')
        # If output changed, the new proposal is separate; human note survives.
        assert list(note.parent.glob('00-Visao-geral.PROPOSTA*.md'))
    finally:app.close();home.cleanup()


def extra_video_same_lesson():
    home,app,root=make_test_app()
    try:
        for video in [3,1,2]:
            fake_transcript(app,root,1,video,'orientação geral','metodologia')
        app.publisher.rebuild()
        overview=app.store.vault/'02-Minhas-Aulas/Aula-001/00-Visao-geral.md'
        text=overview.read_text(encoding='utf-8')
        assert 'V01' in text and 'V02' in text and 'V03' in text
        assert len(list(overview.parent.glob('00-Visao-geral.md')))==1
        assert not (app.store.vault/'02-Minhas-Aulas/Aula-002').exists()
    finally:app.close();home.cleanup()


def no_technical_lesson():
    home,app,root=make_test_app()
    try:
        f=root/'A01 - V01 - Apresentação.txt'
        f.write_text('[0:00] Olá, sou professora.\n[0:13] Vamos apresentar as duplas.\n',encoding='utf8')
        app.add_file(f)
        src=app.store.sources('transcript')[0]
        app.store.save_analysis(src['id'],src['digest'],'stub','qa',{
             'resumo':'Pessoas se apresentaram','tipo_aula':'apresentacao','pessoas':[],
             'conceitos':[], 'atividades':[], 'ferramentas':[], 'marcos':[], 'exemplos':[], 'duvidas':[]})
        app.publisher.rebuild()
        atlas=make_atlas(app.store)
        assert not atlas['concepts']
        assert (app.store.vault/'02-Minhas-Aulas/Aula-001/00-Visao-geral.md').is_file()
        assert not list((app.store.vault/'01-Meu-Conhecimento/Conceitos').glob('*.md'))
    finally:app.close();home.cleanup()


def false_repo_ownership():
    home,app,root=make_test_app()
    try:
        fake_transcript(app,root,10,1,'interfaces','interfaces')
        app.store.save_repo('https://github.com/example/shared','shared','a'*40,{
             'history':[{'author':'Aluno A'}, {'author':'Aluno B'}],
             'evidence':[{'concept':'interfaces','path':'src/main.cs','line':18,'snippet':'public interface ILogger{}'}],
             'collaboration':True,'technologies':['C#'],'files':[], 'documentation':[]},'INDEXED')
        app.publisher.rebuild()
        txt=(app.store.vault/'01-Meu-Conhecimento/Mapa-da-Evolucao.md').read_text(encoding='utf-8')
        assert 'candidato' in txt.lower() and 'autoria' in txt.lower()
        assert 'src/main.cs:18' in txt
        assert 'você implementou' not in txt and 'você domina' not in txt
    finally:app.close();home.cleanup()


def reject_malicious_updates():
    invalid=('evil.example/repo','../../windows','a/b/../c','https://github.com/owner/repo','a/b?token=abc')
    for repo in invalid:
        assert check_release(repo)['ok']==False, repo
    assert check_release('')['configured']==False
    class Dummy:
        def __init__(self,raw):self.raw=raw
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,n):return self.raw[:n]
    bad=json.dumps({'tag_name':'v99.0.0','html_url':'https://evil.example/release','assets':[{'name':'TRAMA_Setup.exe'}]}).encode()
    assert check_release('trusted/repo',opener=lambda *a,**k: Dummy(bad))['ok']==False
    current = version_tuple(VERSION)
    newer = f'v{current[0]}.{current[1]}.{current[2]+1}'
    good=json.dumps({'tag_name':newer,'html_url':f'https://github.com/trusted/repo/releases/tag/{newer}','assets':[{'name':'TRAMA_Setup.exe'}]}).encode()
    assert check_release('trusted/repo',opener=lambda *a,**k: Dummy(good))['available']==True


def nondestructive_reimport():
    home,app,root=make_test_app()
    try:
        rng=random.Random(20261030)
        for i in range(26):
            token=''.join(rng.choices('abcdefxyz',k=16))
            source=root/f'A{i+1:02d} V01 {token}.txt'
            source.write_text(f'[0:10] Explicação {token}\n',encoding='utf-8')
            assert app.add_file(source)
            assert not app.add_file(source)
        app.publisher.rebuild()
        assert len(app.store.sources('transcript'))==26
        assert len(list((app.store.vault/'99-Anexos/Transcricoes-Originais').glob('*.txt')))==26
        assert len(list((app.store.vault/'02-Minhas-Aulas').glob('Aula-*')))==26
    finally:app.close();home.cleanup()

def tampered_update_assets():
    repo='owner-private/trama'
    tag='v1.9.7'
    base=f'https://github.com/{repo}/releases/download/{tag}/'
    data=b'MZ'+bytes(range(256))*8
    digest=hashlib.sha256(data).hexdigest()
    assets=[{'name':n,'browser_download_url':base+n} for n in ('TRAMA_Setup.exe','SHA256SUMS.txt')]
    release=json.dumps({'tag_name':tag,'html_url':f'https://github.com/{repo}/releases/tag/{tag}',
        'assets':assets}).encode()
    class Reply:
        def __init__(self,raw):self.raw=raw;self.pos=0
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self,count):
            chunk=self.raw[self.pos:self.pos+count];self.pos+=len(chunk);return chunk
    def opener(req,timeout=10,corrupt=False,attack=False):
        url=req.full_url
        if url.endswith('/latest'):raw=release
        elif url.endswith('/SHA256SUMS.txt'):raw=f'{digest}  TRAMA_Setup.exe\n'.encode()
        elif url.endswith('/TRAMA_Setup.exe'):raw=data[:-1]+b'X' if corrupt else data
        else:raise AssertionError(url)
        return Reply(raw)
    with tempfile.TemporaryDirectory(prefix='trama-update-') as home:
        p=Path(home)
        ok=download_verified_installer(repo,p/'updates',opener=lambda *a,**kw:opener(*a,**kw))
        assert ok['ok'] and Path(ok['path']).read_bytes()==data
        bad=download_verified_installer(repo,p/'updates',opener=lambda *a,**kw:opener(*a,**kw,corrupt=True))
        assert not bad['ok'] and 'SHA-256' in bad['message']
        assert not list((p/'updates').glob('*.part'))
        # Simulate attacker editing the installer AFTER an otherwise trusted download.
        from knowledge_bridge import bridge as module
        b=module.Bridge.__new__(module.Bridge)
        b._verified_installer=(ok['path'],digest)
        Path(ok['path']).write_bytes(data[:-1]+b'X')
        with patch.object(module,'DATA_HOME',p),patch.object(module.sys,'platform','win32'),patch.object(module.os,'startfile',create=True) as opened:
            blocked=b.launch_update(ok['path'],True)
            assert not blocked['ok'] and 'alterado' in blocked['message']
            opened.assert_not_called()


for name, fn in [
    ('out-of-order concept history',repeated_out_of_order),
    ('C# vs C++ namespace collision',symbols_collision),
    ('fabricated timestamp',fabricated_timestamp),
    ('manual edits remain intact',protect_human_edit),
    ('three recordings one lesson',extra_video_same_lesson),
    ('presentation without code',no_technical_lesson),
    ('shared Git history no personal attribution',false_repo_ownership),
    ('malicious update metadata',reject_malicious_updates),
    ('random repeated sources',nondestructive_reimport),
    ('tampered Windows updater payload',tampered_update_assets),
]:
    start=time.monotonic()
    try:check(name,fn)
    except BaseException:
        print('FAIL:', name)
        raise
    else:print('PASS:',name,f'({time.monotonic()-start:.2f}s)')
print(f'Independent adversarial scenarios: {len(checks)} / {len(checks)} passed')
