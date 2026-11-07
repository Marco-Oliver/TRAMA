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

VERSION = '2.2.1'
_REPO = re.compile(r'^[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,100}$')
_VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?$')


class IntegrityVerificationError(ValueError):
    """Checksum mismatch; return only a fixed, safe failure message."""


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
        if not isinstance(page,str) or page != f'https://github.com/{repo}/releases/tag/{tag}':
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
        headers={'Accept':'application/vnd.github+json','User-Agent':'TRAMA-Update-Check/2.0'})
    try:
        with opener(req,timeout=15) as reply:
            obj=json.loads(reply.read(120_000))
        if not isinstance(obj,dict):
            return {'ok':False,'message':'Metadados do release inválidos.'}
        tag=obj.get('tag_name','')
        if not isinstance(tag,str) or len(tag)>40:
            return {'ok':False,'message':'Tag de release inválida.'}
        if not version_tuple(tag) or not version_tuple(tag)>version_tuple(VERSION):
            return {'ok':False,'message':'Nenhuma versão mais nova disponível.'}
        if obj.get('html_url')!=f'https://github.com/{repo}/releases/tag/{tag}':
            return {'ok':False,'message':'URL do release inesperada.'}
        asset_list=obj.get('assets',[])
        if not isinstance(asset_list,list) or len(asset_list)>100:
            return {'ok':False,'message':'Lista de assets inválida.'}
        assets={a.get('name'):a for a in asset_list if isinstance(a,dict)}
        names=('TRAMA_Setup.exe','SHA256SUMS.txt')
        if not all(name in assets for name in names):
            return {'ok':False,'message':'Release sem instalador e hash de verificação.'}
        prefix=f'https://github.com/{repo}/releases/download/{tag}/'
        for name in names:
            if assets[name].get('browser_download_url')!=prefix+name:
                return {'ok':False,'message':'Link do asset fora do canal oficial.'}
        with opener(urllib.request.Request(prefix+'SHA256SUMS.txt',headers={'User-Agent':'TRAMA-Update-Check/2.0'}), timeout=20) as reply:
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
                with opener(urllib.request.Request(prefix+'TRAMA_Setup.exe',headers={'User-Agent':'TRAMA-Update-Check/2.0'}),timeout=90) as reply:
                    while True:
                        part=reply.read(512*1024)
                        if not part:break
                        total+=len(part)
                        if total>350*1024*1024:
                            raise ValueError('Instalador maior que o limite de 350 MB.')
                        h.update(part);out.write(part)
            if total<1024 or h.hexdigest()!=expected:
                raise IntegrityVerificationError('SHA-256 mismatch')
            final=path/f'TRAMA_Setup_{tag}.exe'
            os.replace(tmp,final)
            return {'ok':True,'path':str(final),'sha256':expected,'version':tag,
                    'message':'Instalador verificado. O Windows ainda pedirá confirmação para executar.'}
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    except IntegrityVerificationError:
        return {'ok':False,'message':'Verificação SHA-256 falhou. Instalação bloqueada.'}
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,urllib.error.URLError):
        # Network/OS exceptions may embed signed URLs, local paths or tokens.
        # Do not expose raw exception text to the UI or logs.
        return {'ok':False,'message':'Não foi possível baixar a atualização. Verifique a conexão e tente novamente.'}


# QA Preview channel: published GitHub *prereleases*, never /releases/latest.
# A GitHub Actions artifact alone is NOT a public updater endpoint.
_PREVIEW = re.compile(r'^v?2\.2\.0-preview\.([1-9][0-9]{0,7})$')
_PREVIEW_INSTALLER = 'TRAMA_Preview_Setup.exe'
_PREVIEW_CHECKSUMS = 'SHA256SUMS-Preview.txt'


def preview_build_number(version: str) -> int | None:
    match = _PREVIEW.fullmatch(str(version))
    return int(match.group(1)) if match else None


def _latest_preview(repo: str, installed: str, opener=None):
    """Find an explicitly published prerelease newer than this Preview build.

    This endpoint includes prereleases, unlike GitHub releases/latest. Never
    select the stable channel or a draft/malformed/foreign-tag release.
    """
    if not _REPO.fullmatch(str(repo)) or '..' in repo:
        raise ValueError('Repositório de Preview inválido.')
    current = preview_build_number(installed)
    if current is None:
        raise ValueError('Versão Preview instalada inválida.')
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/releases?per_page=40',
        headers={'Accept':'application/vnd.github+json',
                 'User-Agent':'TRAMA-Preview-Update-Check/1'})
    with opener(req, timeout=15) as response:
        data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError('Listagem de releases grande demais.')
    releases = json.loads(data)
    if not isinstance(releases, list):
        raise ValueError('Resposta de releases inválida.')
    choices = []
    for release in releases[:40]:
        if not isinstance(release, dict) or release.get('prerelease') is not True or release.get('draft') is True:
            continue
        tag = release.get('tag_name', '')
        number = preview_build_number(tag)
        if number is None or number <= current:
            continue
        if release.get('html_url') != f'https://github.com/{repo}/releases/tag/{tag}':
            continue
        assets = release.get('assets', [])
        if not isinstance(assets, list) or len(assets) > 100:
            continue
        by_name = {item.get('name'): item for item in assets
                   if isinstance(item, dict) and isinstance(item.get('name'), str)}
        required = (_PREVIEW_INSTALLER, _PREVIEW_CHECKSUMS)
        prefix = f'https://github.com/{repo}/releases/download/{tag}/'
        if not all(name in by_name and
                   by_name[name].get('browser_download_url') == prefix + name
                   for name in required):
            continue
        choices.append((number, release))
    return max(choices, key=lambda item: item[0])[1] if choices else None


def check_preview_release(repo: str, installed: str, opener=None) -> dict:
    """Read-only check for an explicitly published Preview installer."""
    try:
        release = _latest_preview(repo, installed, opener=opener)
        if release is None:
            return {'ok':True,'configured':True,'available':False,
                    'installed':installed,
                    'message':'Nenhuma Preview nova publicada. Você está no canal experimental.'}
        return {'ok':True,'configured':True,'available':True,
                'installed':installed, 'version':release['tag_name'],
                'release_page':release['html_url'],
                'message':'Nova Preview disponível para atualizar pelo aplicativo.'}
    except (OSError,ValueError,TypeError,KeyError,urllib.error.URLError):
        return {'ok':False,
                'message':'Não foi possível consultar o canal Preview; o aplicativo continua offline.'}


def download_verified_preview_installer(repo: str, installed: str, destination, opener=None) -> dict:
    """Fetch a newer Preview EXE from published prerelease assets, verify SHA256.

    Does not launch anything, and cannot update the stable TRAMA installation.
    """
    import hashlib
    import os
    import tempfile
    from pathlib import Path

    opener = opener or urllib.request.urlopen
    try:
        release = _latest_preview(repo, installed, opener=opener)
        if release is None:
            return {'ok':False,'message':'Nenhuma Preview mais nova publicada.'}
        tag=release['tag_name']
        prefix=f'https://github.com/{repo}/releases/download/{tag}/'
        with opener(urllib.request.Request(prefix+_PREVIEW_CHECKSUMS,
                    headers={'User-Agent':'TRAMA-Preview-Update-Check/1'}),timeout=20) as response:
            raw=response.read(4097)
        if len(raw)>4096:
            raise ValueError('Manifesto Preview grande demais.')
        expected=''
        for row in raw.decode('ascii').splitlines():
            match=re.fullmatch(r'([a-fA-F0-9]{64})\s+\*?TRAMA_Preview_Setup\.exe',row.strip())
            if match:
                expected=match.group(1).lower()
                break
        if not expected:
            return {'ok':False,'message':'Manifesto Preview sem SHA-256 válido.'}
        folder=Path(destination).expanduser().resolve()
        folder.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix='.preview-download-',suffix='.part',dir=str(folder))
        total=0
        digest=hashlib.sha256()
        try:
            with os.fdopen(fd,'wb') as output:
                with opener(urllib.request.Request(prefix+_PREVIEW_INSTALLER,
                            headers={'User-Agent':'TRAMA-Preview-Update-Check/1'}),timeout=90) as reply:
                    while True:
                        data=reply.read(512*1024)
                        if not data:
                            break
                        total+=len(data)
                        if total>350*1024*1024:
                            raise ValueError('Instalador Preview excede tamanho permitido.')
                        digest.update(data)
                        output.write(data)
            if total<1024 or digest.hexdigest()!=expected:
                raise IntegrityVerificationError('Preview SHA-256 mismatch')
            final=folder/f'TRAMA_Preview_Setup_{tag}.exe'
            os.replace(temp,final)
            return {'ok':True,'path':str(final),'sha256':expected,'version':tag,
                    'message':'Preview verificada. Confirme a instalação na janela do Windows.'}
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    except IntegrityVerificationError:
        return {'ok':False,'message':'SHA-256 da Preview não confere. Instalação bloqueada.'}
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,urllib.error.URLError):
        return {'ok':False,'message':'Não foi possível baixar a Preview; nenhum instalador será executado.'}
