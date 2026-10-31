"""Verificação opcional de releases oficiais.

Nunca instala silenciosamente, não aceita domínios arbitrários e não faz
upload do cofre, transcrições ou credenciais. Sem repositório oficial
configurado, não anuncia atualizações fictícias.
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.error

VERSION = '2.0.0'
_REPO = re.compile(r'^[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,100}$')
_VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?$')


def version_tuple(version: str):
    match = _VERSION.fullmatch(str(version))
    return tuple(int(x) for x in match.groups()) if match else None


def check_release(repo: str, opener=None) -> dict:
    """Read GitHub release metadata. Does not download or execute the installer."""
    if not repo:
        return {'ok': True, 'configured': False, 'message': 'Canal de atualização ainda não publicado.'}
    if not _REPO.fullmatch(repo) or '..' in repo:
        return {'ok': False, 'message': 'Repositório de atualizações inválido.'}
    opener = opener or urllib.request.urlopen
    url = f'https://api.github.com/repos/{repo}/releases/latest'
    req = urllib.request.Request(url, headers={'Accept':'application/vnd.github+json',
        'User-Agent':'TRAMA-Update-Check/2.0'})
    try:
        with opener(req, timeout=12) as response:
            body = response.read(100_000)
        release = json.loads(body)
        tag = release.get('tag_name','')
        current, latest = version_tuple(VERSION), version_tuple(tag)
        if not latest:
            return {'ok': False, 'message': 'Versão do release não reconhecida.'}
        # The app only displays metadata. Installation requires manually
        # clicking a GitHub release page and verifying the publisher.
        page = release.get('html_url','')
        if not isinstance(page,str) or not page.startswith(f'https://github.com/{repo}/releases/'):
            return {'ok': False, 'message': 'Página do release inesperada.'}
        assets = release.get('assets',[])
        found = any(isinstance(x,dict) and x.get('name')=='TRAMA_Setup.exe' for x in assets)
        return {'ok':True,'configured':True,'available':bool(latest>current and found),
                'version':tag,'installed':VERSION,'release_page':page,
                'message':('Atualização disponível.' if latest>current and found else
                    'Nenhum instalador novo publicado.')}
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        return {'ok':False,'message':'Não foi possível verificar atualizações; o aplicativo continua funcionando offline.'}


def download_verified_installer(repo: str, destination, opener=None) -> dict:
    """Baixa EXE de release + verifica SHA-256. NÃO executa nada.

    Somente assets oficiais com nome fixo e manifesto SHA256SUMS.txt
    são aceitos. Limites de tamanho impedem download infinito.
    """
    import hashlib
    import os
    import tempfile
    from pathlib import Path
    if not _REPO.fullmatch(str(repo)) or '..' in repo:
        return {'ok':False,'message':'Canal de atualização inválido.'}
    opener = opener or urllib.request.urlopen
    path = Path(destination).expanduser().resolve()
    path.mkdir(parents=True,exist_ok=True)
    req=urllib.request.Request(
        f'https://api.github.com/repos/{repo}/releases/latest',
        headers={'Accept':'application/vnd.github+json','User-Agent':'TRAMA-Update-Check/1.9'})
    try:
        with opener(req,timeout=15) as reply:
            obj=json.loads(reply.read(120_000))
        tag=obj.get('tag_name','')
        if not version_tuple(tag) or not version_tuple(tag)>version_tuple(VERSION):
            return {'ok':False,'message':'Nenhuma versão mais nova disponível.'}
        if obj.get('html_url')!=f'https://github.com/{repo}/releases/tag/{tag}':
            return {'ok':False,'message':'URL do release inesperada.'}
        assets={a.get('name'):a for a in obj.get('assets',[]) if isinstance(a,dict)}
        names=('TRAMA_Setup.exe','SHA256SUMS.txt')
        if not all(name in assets for name in names):
            return {'ok':False,'message':'Release sem instalador e hash de verificação.'}
        prefix=f'https://github.com/{repo}/releases/download/{tag}/'
        for name in names:
            if assets[name].get('browser_download_url')!=prefix+name:
                return {'ok':False,'message':'Link do asset fora do canal oficial.'}
        with opener(urllib.request.Request(prefix+'SHA256SUMS.txt',headers={'User-Agent':'TRAMA-Update-Check/1.9'}), timeout=20) as reply:
            text=reply.read(4096).decode('ascii')
        expected=''
        for row in text.splitlines():
            m=re.fullmatch(r'([a-fA-F0-9]{64})\s+\*?TRAMA_Setup\.exe',row.strip())
            if m:expected=m.group(1).lower();break
        if not expected:
            return {'ok':False,'message':'Manifesto de hash inválido.'}
        fd,tmp=tempfile.mkstemp(prefix='.trama-download-',suffix='.part',dir=str(path))
        h=hashlib.sha256();total=0
        try:
            with os.fdopen(fd,'wb') as out:
                with opener(urllib.request.Request(prefix+'TRAMA_Setup.exe',headers={'User-Agent':'TRAMA-Update-Check/1.9'}),timeout=90) as reply:
                    while True:
                        part=reply.read(512*1024)
                        if not part:break
                        total+=len(part)
                        if total>350*1024*1024:
                            raise ValueError('Instalador maior que o limite de 350 MB.')
                        h.update(part);out.write(part)
            if total<1024 or h.hexdigest()!=expected:
                raise ValueError('Assinatura SHA-256 do instalador não corresponde ao manifesto.')
            final=path/f'TRAMA_Setup_{tag}.exe'
            os.replace(tmp,final)
            return {'ok':True,'path':str(final),'sha256':expected,'version':tag,
                    'message':'Instalador verificado. O Windows ainda pedirá confirmação para executar.'}
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,urllib.error.URLError) as exc:
        return {'ok':False,'message':'Atualização não foi baixada: '+str(exc)[:140]}
