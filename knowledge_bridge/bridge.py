"""Bridge local do TRAMA para uma janela WebView nativa.

Não inicia servidor HTTP. Expõe somente operações explícitas e com validação;
nenhum HTML, script, comando ou arquivo importado é executado.
"""
from __future__ import annotations
from contextlib import closing
import base64
import binascii
import hashlib
import tempfile
import json
import os
import re
import sqlite3
import stat
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import webbrowser
import threading

from .pipeline import Application
from .update_service import (check_release, download_verified_installer,
                             check_preview_release, download_verified_preview_installer,
                             preview_build_number)
from .secure_keys import KeyVault, PROVIDERS
from .ai import FreeAIRouter, ALLOWED, ProviderError, NoFreeProvider, AllProvidersFailed, BudgetStopped
from .diagnostic import run_ai_diagnostic, format_diagnostic_report, MissingTestSources
from .vault_index import VaultIndex
from .code_intel import redact_sensitive
from .paths import DATA_HOME, SETTINGS_FILE, CONFIG_FILE, PREVIEW_BUNDLE

ALLOWED_ATTACHMENTS={'.txt','.md','.mp4','.mkv','.mov','.webm','.png','.jpg','.jpeg','.webp','.pdf','.docx'}

_GRAPH_INDEX_STEMS = {"minha-biblioteca", "meu_contexto", "mapa-da-evolucao", "bem-vindo", "indice-de-duvidas"}

def _graph_kind(note) -> str:
    """Classificação só para cor e filtro do gráfico; não altera notas."""
    tipo = str(note.metadata.get("tipo", "")).casefold()
    stem = note.stem.casefold()
    # render_uncertainties() writes these notes without a 'tipo' frontmatter.
    if "duvida" in tipo or note.relative.casefold().startswith("01-meu-conhecimento/duvidas/"):
        return "duvida"
    if (tipo in ("visao_geral", "indice", "mapa") or stem.startswith("00-")
            or stem in _GRAPH_INDEX_STEMS or note.section == "00-Inicio"):
        return "indice"
    if note.section == "01-Meu-Conhecimento":
        return "conceito"
    if note.section == "02-Minhas-Aulas":
        return "aula"
    if note.section == "03-Meus-Projetos":
        return "projeto"
    return "outro"

class Bridge:
    def __init__(self):
        self._window=None
        self._write_lock=threading.Lock()
        self.settings=self._read_settings()
        self._key_vault=KeyVault(DATA_HOME / "api_keys.dpapi.json")
        self._is_maximized=False
        self._is_fullscreen=False
        self._verified_installer=None  # path + sha256 only after verified download
        self._teacher_lock=threading.Lock()
        self._teacher_history=[]
        self._mapping_preview=None  # Candidate refs are never persisted without user confirmation.
        self._teacher_vault=None
        self._teacher_requests=0
        # Fila em memória: nada é enviado nem escrito no Obsidian até Processar tudo.
        self._stage_guard=threading.RLock()
        self._queued={}
        self._temp_stage=None

    def _read_settings(self):
        try:
            data=json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}

    def _save(self):
        """Replace local settings atomically; avoid partial JSON after interruption."""
        DATA_HOME.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix='.trama-settings-',suffix='.tmp',dir=DATA_HOME)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as out:
                json.dump(self.settings,out,indent=2,ensure_ascii=False)
                out.write(chr(10))
            os.replace(temp,SETTINGS_FILE)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _vault(self):
        raw=self.settings.get('vault','')
        if not raw:return None
        path=Path(raw).expanduser().resolve()
        return path if path.is_dir() else None

    def _index(self):
        path=self._vault()
        return VaultIndex(path) if path else None

    @staticmethod
    def _safe_classroom_record(vault, stored):
        """Only read bounded, non-symlink Classroom JSON inside the vault."""
        if (not isinstance(stored,str) or not stored or len(stored)>700 or
                '\\' in stored or Path(stored).is_absolute() or
                any(part in ('.','..') for part in stored.split('/'))):
            return None
        path=vault/stored
        rel=Path(stored)
        try:
            if any((vault/Path(*rel.parts[:i])).is_symlink()
                   for i in range(1,len(rel.parts)+1)):
                return None
            if not path.resolve().is_relative_to(vault.resolve()):
                return None
            flags=os.O_RDONLY | getattr(os,'O_BINARY',0) | getattr(os,'O_NOFOLLOW',0)
            with os.fdopen(os.open(path,flags),'rb') as source:
                stat_info=os.fstat(source.fileno())
                if not stat.S_ISREG(stat_info.st_mode) or stat_info.st_size>2_000_000:
                    return None
                payload=source.read(2_000_001)
            if len(payload)>2_000_000:
                return None
            result=json.loads(payload.decode('utf-8-sig'))
            return result if isinstance(result,dict) else None
        except (OSError,ValueError,UnicodeError,TypeError):
            return None

    def _stats(self,path):
        output={'transcriptions':0,'videos':0,'repositories':0,'notes':0,'materials':0,'classrooms':0}
        db=path/'.base-conhecimento'/'estado.sqlite3'
        if not db.is_file():return output
        try:
            with closing(sqlite3.connect(db.as_uri() + '?mode=ro',uri=True,timeout=2)) as con:
                for kind,count in con.execute('SELECT kind,COUNT(*) FROM sources GROUP BY kind'):
                    if kind=='transcript':output['transcriptions']=count
                    if kind=='video':output['videos']=count
                    if kind=='material':output['materials']=count
                    if kind=='classroom':output['classrooms']=count
                output['repositories']=con.execute('SELECT COUNT(*) FROM repositories').fetchone()[0]
                for (stored,) in con.execute("SELECT stored_path FROM sources WHERE kind='classroom'"):
                    try:
                        record=self._safe_classroom_record(path,stored)
                        rows=record.get('videos',[]) if record else []
                        if isinstance(rows,list):
                            output['videos'] += sum(1 for entry in rows[:100] if isinstance(entry,dict) and self._valid_video_url(entry.get('url')))
                    except (OSError,ValueError,UnicodeError,AttributeError,TypeError):
                        continue
        except (sqlite3.Error,OSError):pass
        return output

    def vault_disk_usage(self):
        """Summarize local storage by category without reading source content."""
        vault=self._vault()
        if vault is None:
            return {'ok':False,'message':'Conecte o Obsidian para consultar o espaço usado.'}
        totals={'notes':0,'attachments':0,'repositories':0,'catalog':0,'other':0}
        scanned=0
        capped=False
        try:
            for root,dirs,files in os.walk(vault,followlinks=False):
                root=Path(root)
                dirs[:]=[name for name in dirs
                         if not (root/name).is_symlink()]
                for name in files:
                    file=root/name
                    if file.is_symlink() or not file.is_file():
                        continue
                    try:
                        size=file.stat().st_size
                    except OSError:
                        continue
                    parts=file.relative_to(vault).parts
                    if len(parts)>=2 and parts[0]=='.base-conhecimento' and parts[1]=='repos':
                        category='repositories'
                    elif parts[0]=='99-Anexos':
                        category='attachments'
                    elif parts[0]=='.base-conhecimento':
                        category='catalog'
                    elif file.suffix.lower()=='.md':
                        category='notes'
                    else:
                        category='other'
                    totals[category]+=size
                    scanned+=1
                    if scanned>=120000:
                        capped=True
                        break
                if capped:
                    break
        except OSError:
            return {'ok':False,'message':'Não foi possível conferir o tamanho do cofre.'}
        return {'ok':True,'total_bytes':sum(totals.values()),'categories':totals,
                'files':scanned,'partial':capped}

    def snapshot(self):
        idx=self._index()
        if not idx:
            return {'connected':False,'vault':'','notes':[],'stats':self._stats(Path.home())}
        return {
            'connected':True,'vault':str(idx.vault),'scanned_at':datetime.now().strftime('%d/%m/%Y %H:%M'),
            'favorites':[p for p in self.settings.get('favorites',[]) if isinstance(p,str)][:200],
            'notes':[{'id':n.relative,'title':n.title,'section':n.section,
                      'lesson':n.metadata.get('aula',''),
                      'kind':n.metadata.get('tipo',''),
                      'state':n.metadata.get('estado',''),
                      'updated':datetime.fromtimestamp(n.path.stat().st_mtime).strftime('%d/%m/%Y'),'tags':self._tags(n)}
                     for n in idx.notes],
            'stats':{**self._stats(idx.vault),'notes':len(idx.notes)}
        }

    @staticmethod
    def _tags(note):
        """Apenas tags locais declaradas; não infere conhecimentos com IA."""
        raw=note.metadata.get('tags','')
        tags=[t.strip().strip('\"\'') for t in raw.strip('[]').split(',') if t.strip()]
        inline=re.findall(r'(?<![\w/])#([\w/-]{2,45})',note.content)
        return sorted({x.lower() for x in [*tags,*inline] if x})[:50]

    @staticmethod
    def _section(raw, heading):
        match=re.search(r'(?mi)^##\s+'+re.escape(heading)+r'\s*\n(.*?)(?=^##\s+|\Z)',raw,re.S|re.M)
        return match.group(1).strip() if match else ''

    def _media(self,idx,note):
        db=idx.vault/'.base-conhecimento'/'estado.sqlite3'
        out={'video':[],'transcript':[],'video_links':[]}
        if not db.is_file():return out
        lesson=note.metadata.get('aula','')
        if not lesson:return out
        try:
            with closing(sqlite3.connect(db.as_uri() + '?mode=ro',uri=True,timeout=2)) as con:
                for kind,label,stored,video in con.execute('SELECT kind,label,stored_path,video FROM sources WHERE lesson=?',(lesson,)):
                    if kind in ('video', 'transcript') and stored:
                        out[kind].append({'label':label,'stored':stored,'video_id':video or ''})
                    elif kind == 'classroom' and stored:
                        try:
                            item=self._safe_classroom_record(idx.vault,stored)
                            rows=item.get('videos',[]) if item else []
                            if not isinstance(rows,list):
                                continue
                            for entry in rows[:30]:
                                if not isinstance(entry,dict):
                                    continue
                                url=entry.get('url','')
                                if self._valid_video_url(url):
                                    out['video_links'].append({'label':str(entry.get('titulo','Gravação'))[:160], 'url':url})
                        except (OSError,ValueError,UnicodeError,AttributeError,TypeError):
                            continue
        except (sqlite3.Error,OSError):pass
        return out

    def note(self,note_id):
        if not isinstance(note_id,str) or len(note_id)>500:return {'error':'Identificador inválido'}
        idx=self._index()
        if not idx:return {'error':'Selecione um cofre do Obsidian'}
        selected=idx.by_relative.get(note_id.lower())
        if not selected:return {'error':'Nota não encontrada'}
        related=idx.related(selected,60)
        kind=selected.metadata.get('tipo','')
        if kind=='conceito':
            summary=self._section(selected.content,'Explicações e referências das aulas') or ''
            concepts=''
        elif kind=='pessoa':
            summary=self._section(selected.content,'Menções nas aulas') or ''
            concepts=''
        else:
            summary=(self._section(selected.content,'Resumo da aula') or
                     self._section(selected.content,'Em poucas palavras') or
                     self._section(selected.content,'Resumo') or '')
            concepts=(self._section(selected.content,'Conhecimentos técnicos citados') or
                      self._section(selected.content,'Conceitos identificados pela IA (conferir na fonte)') or
                      self._section(selected.content,'Conceitos ensinados (extraídos pela IA)') or
                      self._section(selected.content,'Conceitos principais') or '')
        examples=self._section(selected.content,'Exemplos mencionados')
        if not summary:
            paragraphs=[p.strip() for p in selected.content.split('\n\n') if p.strip() and not p.lstrip().startswith('#')]
            summary=paragraphs[0][:1400] if paragraphs else 'Aguardando conteúdo.'
        return {
            'id':selected.relative,'title':selected.title,'kind':selected.metadata.get('tipo','Markdown'),
            'lesson':selected.metadata.get('aula',''),'state':selected.metadata.get('estado',''),
            'updated':datetime.fromtimestamp(selected.path.stat().st_mtime).strftime('%d/%m/%Y'),'tags':self._tags(selected),
            'content':selected.content,'summary':summary,'concepts':concepts,
            'examples':examples,'media':self._media(idx,selected),
            'related':[{'id':n.relative,'title':n.title,'section':n.section,'kind':n.metadata.get('tipo',''), 'tags':self._tags(n)} for n in related],
        }

    def search_notes(self, query, limit=80):
        """Search the actual Markdown text in the selected Obsidian vault.

        Read-only, local and bounded. Never sends vault text to an AI provider;
        return only short matched excerpts, not a dump of every note.
        """
        if (not isinstance(query,str) or len(query)>120 or
                any(ord(c)<32 or ord(c)==127 for c in query)):
            return {'ok':False,'message':'Pesquisa inválida. Use até 120 caracteres.'}
        q=query.strip().casefold()
        if len(q)<2:
            return {'ok':True,'matches':[],'total':0}
        if type(limit) is not int or limit<1 or limit>100:
            return {'ok':False,'message':'Limite de pesquisa inválido.'}
        idx=self._index()
        if not idx:
            return {'ok':False,'message':'Conecte primeiro seu cofre do Obsidian.'}
        results=[]
        total=0
        for note in idx.notes:
            path_hit=q in note.relative.casefold() or q in note.title.casefold()
            content_fold=note.content.casefold()
            where=content_fold.find(q)
            if not path_hit and where<0:
                continue
            total+=1
            if len(results)>=limit:
                continue
            snippet=''
            if where>=0:
                left=max(0,where-65)
                right=min(len(note.content),where+len(q)+105)
                snippet=' '.join(note.content[left:right].split())[:220]
                if left: snippet='…'+snippet
                if right<len(note.content): snippet+='…'
            results.append({'id':note.relative,'title':note.title,
                            'section':note.section,'snippet':snippet,
                            'in_content':where>=0})
        results.sort(key=lambda item:(not item['in_content'],
                                     item['title'].casefold(),item['id'].casefold()))
        return {'ok':True,'matches':results,'total':total,
                'truncated':total>limit}

    def graph(self):
        idx=self._index()
        if not idx:return {'nodes':[],'edges':[]}
        nodes,edges=idx.graph(cap=450)
        return {'nodes':[{'id':n.relative,'title':n.title,'section':n.section,
                          'kind':_graph_kind(n)} for n in nodes],
                'edges':edges}

    def audit_note(self, note_id):
        """Verify evidence for the selected lesson without contacting a model."""
        idx=self._index()
        if not idx or not isinstance(note_id,str):
            return {'ok':False,'message':'Selecione uma nota de aula no Obsidian.'}
        note=idx.by_relative.get(note_id.casefold())
        if not note:
            return {'ok':False,'message':'Nota não encontrada.'}
        from .audit import audit_lesson
        return audit_lesson(idx.vault, note.metadata.get('aula',''))

    def organize_library(self, confirmed=False):
        """Refresh only generated Markdown from the catalog, never call an AI service.

        Publisher.write protects user-modified notes by producing *.PROPOSTA.md.
        No original transcripts, user notes or stored materials are removed.
        """
        if confirmed is not True:
            return {'ok': False, 'message': 'Confirme a organização da biblioteca.'}
        vault=self._vault()
        if not vault:return {'ok':False,'message':'Configure o cofre primeiro.'}
        if not self._write_lock.acquire(blocking=False):
            return {'ok':False,'message':'Há um processamento em andamento.'}
        app=None
        try:
            app=Application(vault, CONFIG_FILE, log=lambda _s:None)
            result=app.publisher.rebuild()
            return {'ok':True,'result':result,
                    'message':'Visões gerais atualizadas sem chamar a IA. Notas editadas foram preservadas.'}
        except (OSError, ValueError, sqlite3.Error) as ex:
            return {'ok':False,'message':'Falha na organização: '+str(ex)[:160]}
        finally:
            if app:app.close()
            self._write_lock.release()

    def backup_vault(self, confirmed=False):
        """Save a local ZIP backup after explicit consent; never uploads data."""
        if not confirmed:
            return {'ok': False, 'message': 'Confirme a criação de backup local.'}
        vault = self._vault()
        if not vault or not self._window:
            return {'ok': False, 'message': 'Selecione um cofre e abra o aplicativo.'}
        if not self._write_lock.acquire(blocking=False):
            return {'ok': False, 'message': 'Aguarde a conclusão do processamento.'}
        try:
            import webview
            from .recovery import create_backup
            save_dialog = getattr(webview, "SAVE_DIALOG", None)
            if save_dialog is None:
                save_dialog = webview.FileDialog.SAVE
            selection = self._window.create_file_dialog(
                save_dialog, save_filename="TRAMA_Backup.zip",
                file_types=("Arquivo ZIP (*.zip)",))
            if not selection:
                return {'ok': False, 'message': 'Backup cancelado.'}
            destination = selection[0] if isinstance(selection, (tuple, list)) else selection
            report = create_backup(vault, Path(destination))
            return {**report, 'message': 'Backup criado localmente. Guarde o ZIP em local seguro: não é criptografado.'}
        except (OSError, ValueError, RuntimeError) as error:
            return {'ok': False, 'message': 'Backup não criado: ' + str(error)[:140]}
        finally:
            self._write_lock.release()

    def restore_vault(self, confirmed=False):
        """Restore ZIP into a *new* folder; never replace the selected vault."""
        if not confirmed:
            return {'ok': False, 'message': 'Confirme que deseja restaurar em uma pasta nova.'}
        if not self._window:
            return {'ok': False, 'message': 'Janela não disponível.'}
        if not self._write_lock.acquire(blocking=False):
            return {'ok': False, 'message': 'Aguarde o processamento atual.'}
        try:
            import webview
            import zipfile
            from .recovery import restore_backup
            open_dialog = getattr(webview, "OPEN_DIALOG", None) or webview.FileDialog.OPEN
            folder_dialog = getattr(webview, "FOLDER_DIALOG", None) or webview.FileDialog.FOLDER
            selected = self._window.create_file_dialog(
                open_dialog, file_types=("Arquivo ZIP (*.zip)",))
            if not selected:
                return {'ok': False, 'message': 'Restauração cancelada.'}
            archive = selected[0] if isinstance(selected, (list, tuple)) else selected
            parent = self._window.create_file_dialog(folder_dialog)
            if not parent:
                return {'ok': False, 'message': 'Restauração cancelada.'}
            folder = Path(parent[0] if isinstance(parent, (list, tuple)) else parent).resolve()
            vault = self._vault()
            if vault and folder.is_relative_to(vault):
                return {'ok': False, 'message': 'Escolha uma pasta fora do cofre atual.'}
            destination = folder / ("TRAMA-Restaurado-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            restored = restore_backup(Path(archive), destination)
            return {**restored, 'message':
                    'Restaurado em ' + str(destination) + '. Use Selecionar pasta para abri-la; o cofre anterior foi preservado.'}
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
            return {'ok': False, 'message': 'Backup não restaurado: ' + str(error)[:140]}
        finally:
            self._write_lock.release()

    def select_vault(self):
        if not self._window:return {'ok':False,'message':'Janela não disponível'}
        import webview
        folder_dialog=getattr(webview,"FOLDER_DIALOG",None) or webview.FileDialog.FOLDER
        selected=self._window.create_file_dialog(folder_dialog)
        if not selected:return {'ok':False}
        path=Path(selected[0]).expanduser().resolve()
        if not path.is_dir():return {'ok':False,'message':'Pasta inválida'}
        self.settings['vault']=str(path)
        self._save()
        return {'ok':True}

    def import_materials(self):
        if not self._vault():return {'ok':False,'message':'Configure o cofre do Obsidian primeiro.'}
        if not self._window:return {'ok':False,'message':'Janela não disponível'}
        import webview
        open_dialog=getattr(webview,"OPEN_DIALOG",None) or webview.FileDialog.OPEN
        selected=self._window.create_file_dialog(open_dialog,allow_multiple=True)
        if not selected:return {'ok':False,'message':'Nenhum arquivo selecionado'}
        if not self._write_lock.acquire(blocking=False):return {'ok':False,'message':'Já existe um processamento em andamento.'}
        processed=0
        errors=[]
        app=Application(self._vault(),CONFIG_FILE,log=lambda _s:None)
        try:
            for item in selected[:250]:
                p=Path(item)
                if p.suffix.lower() not in ALLOWED_ATTACHMENTS:
                    errors.append(p.name+': formato não suportado');continue
                try:processed+=int(app.add_file(p))
                except (OSError,ValueError) as ex:errors.append(p.name+': '+str(ex)[:150])
            app.publisher.rebuild()
        finally:
            app.close()
            self._write_lock.release()
        return {'ok':True,'count':processed,'errors':errors[:10]}

    def staged_items(self):
        """Retorna só metadados para a interface, nunca caminhos locais completos."""
        with self._stage_guard:
            return {'ok':True, 'items':[{'id':key,'name':entry['name'],
                     'kind':entry['kind'], 'size':entry['size']}
                     for key,entry in self._queued.items()], 'max':100}

    def stage_files(self):
        """Somente seleciona arquivos: sem escrita no vault e sem chamadas à API."""
        if self._write_lock.locked():
            return {'ok':False,'message':'Aguarde o processamento atual terminar.'}
        if self._window is None:
            return {'ok':False,'message':'Janela de seleção indisponível.'}
        import webview
        dialog=getattr(webview,'OPEN_DIALOG',None) or webview.FileDialog.OPEN
        selected=self._window.create_file_dialog(dialog,allow_multiple=True)
        if not selected:
            return self.staged_items()
        from .auto_ingest import SUPPORTED, MAX_FILES
        errors=[];added=0
        with self._stage_guard:
            for raw in selected:
                path=Path(raw).expanduser()
                if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SUPPORTED:
                    errors.append(path.name[:90]+': formato ou arquivo inválido');continue
                if path.stat().st_size>60*1024*1024:
                    errors.append(path.name[:90]+': arquivo maior que 60 MB');continue
                ident=hashlib.sha256(str(path.resolve()).casefold().encode()).hexdigest()[:24]
                if ident in self._queued:continue
                if len(self._queued)>=MAX_FILES:
                    errors.append('Limite de 100 arquivos por processamento.');break
                self._queued[ident]={'name':path.name,'path':path.resolve(),
                                    'kind':'arquivo','size':path.stat().st_size}
                added+=1
        result=self.staged_items();result.update(added=added,errors=errors[:8]);return result

    def stage_clipboard_image(self, data_url):
        """Recebe PNG/JPEG colado via Ctrl+V no WebView; sem API e sem vault.

        Limite antes/depois de decodificar para evitar alocação excessiva.
        """
        if self._write_lock.locked():
            return {'ok':False,'message':'Aguarde o processamento atual terminar.'}
        if not isinstance(data_url,str) or len(data_url)>8_500_000:
            return {'ok':False,'message':'Print acima do limite de 6 MB.'}
        if data_url.startswith('data:image/png;base64,'):
            extension='.png';header='data:image/png;base64,';signature=b'\x89PNG\r\n\x1a\n'
        elif data_url.startswith('data:image/jpeg;base64,'):
            extension='.jpg';header='data:image/jpeg;base64,';signature=b'\xff\xd8\xff'
        else:
            return {'ok':False,'message':'Cole uma imagem PNG ou JPEG.'}
        try:
            binary=base64.b64decode(data_url[len(header):],validate=True)
        except (ValueError,binascii.Error):
            return {'ok':False,'message':'Print inválido.'}
        if not binary.startswith(signature) or not 0<len(binary)<=6*1024*1024:
            return {'ok':False,'message':'Print inválido ou acima de 6 MB.'}
        ident=hashlib.sha256(binary).hexdigest()[:24]
        with self._stage_guard:
            if ident in self._queued:return self.staged_items()
            if len(self._queued)>=100:
                return {'ok':False,'message':'Limite de 100 arquivos na fila.'}
            if self._temp_stage is None:
                self._temp_stage=tempfile.TemporaryDirectory(prefix='trama-prints-')
            path=Path(self._temp_stage.name)/('print-'+ident+extension)
            path.write_bytes(binary)
            self._queued[ident]={'name':'Print colado '+str(len(self._queued)+1)+extension,
                                'path':path,'kind':'print colado','size':len(binary)}
        result=self.staged_items();result['added']=1;return result

    def remove_staged(self,ident):
        if self._write_lock.locked():
            return {'ok':False,'message':'Aguarde o processamento atual terminar.'}
        with self._stage_guard:
            entry=self._queued.pop(ident,None)
            if entry and entry['kind']=='print colado':
                try:entry['path'].unlink(missing_ok=True)
                except OSError:pass
        return self.staged_items()

    def clear_staged(self):
        with self._stage_guard:
            self._queued.clear()
            if self._temp_stage is not None:
                self._temp_stage.cleanup();self._temp_stage=None
        return self.staged_items()

    def process_staged(self,links='',confirmed=False):
        """ÚNICO ponto de commit do lote. Antes disso, só staging local."""
        if confirmed is not True:
            return {'ok':False,'message':'Confirme o envio dos materiais à API gratuita.'}
        vault=self._vault()
        if not vault:return {'ok':False,'message':'Selecione o cofre do Obsidian em Ajustes.'}
        if not self._write_lock.acquire(blocking=False):
            return {'ok':False,'message':'Outro processamento já está em andamento.'}
        app=None
        try:
            with self._stage_guard:
                paths=[row['path'] for row in self._queued.values()]
            if not paths and not str(links).strip():
                return {'ok':False,'message':'Adicione prints, arquivos ou links antes de processar.'}
            for path in paths:
                if not path.is_file():
                    return {'ok':False,'message':'Um arquivo selecionado foi movido. Remova-o e selecione novamente.'}
            from .auto_ingest import AutoOrganizer
            app=self._make_application(vault,log=lambda _s:None)
            result=AutoOrganizer(app).run(paths,links,authorized=True)
            # Pendências ficam salvas no cofre para revisão; não mantemos
            # imagens do clipboard após um processamento bem-sucedido.
            if result.get('errors'):
                result['queue_retained']=True
            else:
                self.clear_staged()
                result['queue_retained']=False
            return {'ok':True,**result}
        except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:
            return {'ok':False,'message':str(exc)[:250]}
        except Exception:
            return {'ok':False,'message':'Falha no lote. A fila foi preservada para tentar novamente.'}
        finally:
            if app is not None:app.close()
            self._write_lock.release()

    def auto_import(self, links='', confirmed=False, pick_files=True):
        """Fluxo principal. Uma seleção de arquivos e links; sem formulário de contexto.

        Só envia materiais ao provedor externo quando o usuário autoriza.
        Não lê URLs remotas; GitHub público é indexado apenas se enviado.
        """
        if confirmed is not True:
            return {'ok':False,'message':'Autorize o envio dos materiais à IA externa antes de iniciar.'}
        vault=self._vault()
        if not vault:return {'ok':False,'message':'Selecione seu cofre do Obsidian em Ajustes.'}
        if not self._write_lock.acquire(blocking=False):
            return {'ok':False,'message':'Já há uma importação em andamento.'}
        app=None
        try:
            paths=[]
            if pick_files:
                if self._window is None:return {'ok':False,'message':'Janela não disponível.'}
                import webview
                dialog=getattr(webview,'OPEN_DIALOG',None) or webview.FileDialog.OPEN
                selected=self._window.create_file_dialog(dialog,allow_multiple=True)
                paths=[Path(p) for p in (selected or [])]
                if not paths and not str(links).strip():
                    return {'ok':False,'message':'Nenhum arquivo selecionado.'}
            app=self._make_application(vault,log=lambda _s:None)
            from .auto_ingest import AutoOrganizer
            result=AutoOrganizer(app).run(paths,links,authorized=True)
            return {'ok':True,**result}
        except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:
            return {'ok':False,'message':str(exc)[:250]}
        except Exception:
            return {'ok':False,'message':'Falha inesperada na importação. Os arquivos originais não foram apagados.'}
        finally:
            if app is not None:app.close()
            self._write_lock.release()

    def save_classroom_context(self, data):
        """Cadastro manual explícito; sem envio à IA nem alteração em arquivos pessoais."""
        vault = self._vault()
        if vault is None:
            return {"ok": False, "message": "Selecione o cofre do Obsidian primeiro."}
        if not self._write_lock.acquire(blocking=False):
            return {"ok": False, "message": "Outro processamento está em andamento."}
        app = None
        try:
            app = Application(vault, CONFIG_FILE, log=lambda _s: None)
            return app.register_classroom(data)
        except (ValueError, OSError, TypeError) as exc:
            return {"ok": False, "message": str(exc)[:190]}
        finally:
            if app is not None:
                app.close()
            self._write_lock.release()

    def import_classroom_materials(self, lesson):
        """Material selecionado manualmente e vinculado à aula; sem leitura OCR automática."""
        from .classroom import lesson_number
        vault = self._vault()
        if vault is None or not self._window:
            return {'ok':False,'message':'Selecione o cofre antes.'}
        try:
            lesson=lesson_number(lesson)
        except ValueError as exc:
            return {'ok':False,'message':str(exc)}
        import webview
        open_dialog=getattr(webview,'OPEN_DIALOG',None) or webview.FileDialog.OPEN
        selected=self._window.create_file_dialog(open_dialog,allow_multiple=True)
        if not selected:
            return {'ok':False,'message':'Nenhum arquivo selecionado.'}
        if not self._write_lock.acquire(blocking=False):
            return {'ok':False,'message':'Outro processamento está em andamento.'}
        app=None
        try:
            app=Application(vault,CONFIG_FILE,log=lambda _s:None)
            success=0
            errors=[]
            for raw in selected[:40]:
                try:
                    success+=int(app.attach_classroom_material(lesson,Path(raw)))
                except (ValueError,OSError) as exc:
                    errors.append(str(exc)[:140])
            app.publisher.rebuild()
            return {'ok':True,'count':success,'errors':errors[:10]}
        finally:
            if app is not None:app.close()
            self._write_lock.release()

    def _release_repo(self):
        """Canal incorporado ao instalador; nenhum repositório é inventado."""
        # The official channel is embedded at build time, not writable through user settings.
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
        try:
            channel = json.loads((base / 'release_channel.json').read_text(encoding='utf-8'))
            return channel.get('github_repo','') if isinstance(channel,dict) else ''
        except (OSError,ValueError):
            return ''

    def _preview_update_version(self):
        """Preview channel is embedded in its isolated binary, never user settings."""
        if not PREVIEW_BUNDLE:
            return ''
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
        try:
            metadata = json.loads((base / 'release_channel.json').read_text(encoding='utf-8'))
            if (not isinstance(metadata, dict) or metadata.get('channel') != 'preview'
                    or metadata.get('github_repo') != self._release_repo()):
                return ''
            version = metadata.get('version','')
            return version if preview_build_number(version) is not None else ''
        except (OSError, ValueError, TypeError):
            return ''

    def check_updates(self):
        """Consulta somente metadados GitHub do canal desta instalação."""
        if PREVIEW_BUNDLE:
            installed = self._preview_update_version()
            if not installed:
                return {'ok':False,'message':'Canal Preview não configurado neste instalador.'}
            return check_preview_release(self._release_repo(), installed)
        return check_release(self._release_repo())

    def prepare_update(self, confirmed=False):
        """Somente download verificado; não executa o instalador."""
        if not confirmed:
            return {'ok':False, 'message':'Confirme a atualização primeiro.'}
        if sys.platform != 'win32':
            return {'ok':False,'message':'O instalador está disponível somente no Windows.'}
        self._verified_installer=None
        if PREVIEW_BUNDLE:
            installed=self._preview_update_version()
            if not installed:
                return {'ok':False,'message':'Canal Preview não configurado neste instalador.'}
            result=download_verified_preview_installer(
                self._release_repo(),installed, DATA_HOME/'updates')
        else:
            result=download_verified_installer(self._release_repo(), DATA_HOME/'updates')
        if result.get('ok'):
            self._verified_installer=(result['path'], result['sha256'])
        return result

    def launch_update(self, path, confirmed=False):
        """Executa instalador local apenas após nova aprovação do usuário."""
        if not confirmed or sys.platform!='win32':
            return {'ok':False,'message':'Confirmação do Windows necessária.'}
        updates=(DATA_HOME/'updates').resolve()
        candidate=Path(str(path)).resolve()
        expected_name = (r'TRAMA_Preview_Setup_v2\.2\.0-preview\.[1-9][0-9]{0,7}\.exe'
                         if PREVIEW_BUNDLE and self._preview_update_version() else
                         r'TRAMA_Setup_v\d+\.\d+\.\d+\.exe' if not PREVIEW_BUNDLE else '')
        if (not candidate.is_file() or candidate.parent!=updates
                or not re.fullmatch(expected_name,candidate.name)
                or not self._verified_installer or str(candidate)!=self._verified_installer[0]):
            return {'ok':False,'message':'Instalador não reconhecido ou não verificado nesta sessão.'}
        try:
            with candidate.open('rb') as stream:
                digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if digest!=self._verified_installer[1]:
                self._verified_installer=None
                return {'ok':False,'message':'Arquivo alterado após o download. Atualização bloqueada.'}
            self._verified_installer=None
            os.startfile(str(candidate))  # Opens standard interactive Inno Setup prompt.
        except OSError:
            return {'ok':False,'message':'O Windows não conseguiu abrir o instalador.'}
        return {'ok':True,'message':'Instalador aberto. Confirme a atualização na janela do Windows.'}

    def open_update_page(self, address):
        """Abre a página oficial somente após escolha explícita do usuário."""
        from .update_service import version_tuple
        repo=self._release_repo()
        prefix=f'https://github.com/{repo}/releases/tag/' if repo else ''
        tag=address[len(prefix):] if prefix and isinstance(address,str) and address.startswith(prefix) else ''
        valid = (preview_build_number(tag) is not None and bool(self._preview_update_version())
                 if PREVIEW_BUNDLE else
                 bool(re.fullmatch(r'v?\d+\.\d+\.\d+',tag) and version_tuple(tag)))
        # Exact release route. The Preview never opens stable releases here.
        if not valid:
            return {'ok':False, 'message':'Página de atualização não reconhecida.'}
        webbrowser.open(address)
        return {'ok':True}

    def search_transcript(self, stored, query):
        """Local-only search in registered TXT transcripts; never call AI."""
        if (not isinstance(stored,str) or len(stored)>450 or
                not isinstance(query,str) or not 1<=len(query.strip())<=160):
            return {'ok':False,'message':'Escolha uma transcrição e informe um termo de busca.'}
        vault=self._vault()
        if not vault:return {'ok':False,'message':'Conecte o cofre do Obsidian primeiro.'}
        from .teacher_transcripts import _load_verified, _extract_timed_excerpt
        from .teacher import _terms
        db=vault/'.base-conhecimento'/'estado.sqlite3'
        if db.is_symlink() or db.parent.is_symlink() or not db.is_file():
            return {'ok':False,'message':'Catálogo de fontes indisponível.'}
        try:
            with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=2)) as con:
                row=con.execute(
                    "SELECT digest FROM sources WHERE kind='transcript' AND stored_path=? LIMIT 1",
                    (stored,)
                ).fetchone()
        except (sqlite3.Error,OSError):
            return {'ok':False,'message':'Não foi possível consultar as transcrições.'}
        if not row:
            return {'ok':False,'message':'Transcrição não cadastrada no cofre.'}
        raw=_load_verified(vault,stored,row[0])
        if raw is None:
            return {'ok':False,'message':'Fonte alterada, maior que 2 MB ou insegura. Confira o original.'}
        excerpt,times=_extract_timed_excerpt(raw,_terms(query),query)
        return {'ok':True,'excerpt':excerpt,'times':times[:12],
                'message':('Trechos encontrados na transcrição original.' if excerpt else
                           'Nenhum trecho com esse termo foi encontrado na transcrição.')}

    def teacher_ask(self, question, mode="explicar", code="", confirmed=False):
        """One consented request, read-only vault retrieval and short session memory."""
        if confirmed is not True:
            return {'ok': False, 'message': 'Autorize o envio dos trechos selecionados à API externa.'}
        if not isinstance(question, str) or not isinstance(code, str) or not isinstance(mode, str):
            return {'ok': False, 'message': 'Pergunta, modo ou código inválido.'}
        if not self._teacher_lock.acquire(blocking=False):
            return {'ok': False, 'message': 'O Professor já está respondendo outra pergunta.'}
        router = None
        try:
            vault = self._vault()
            if vault is None:
                return {'ok': False, 'message': 'Selecione o cofre do Obsidian em Ajustes.'}
            if self._teacher_vault != str(vault):
                self._teacher_history = []
                self._teacher_requests = 0
                self._teacher_vault = str(vault)
            if self._teacher_requests >= 24:
                return {'ok': False, 'message':
                        'Limite de 24 perguntas nesta sessão. Reabra o aplicativo para iniciar outra sessão.'}
            if not self.settings.get('confirmed_free'):
                return {'ok': False, 'message': 'Configure um provedor gratuito em Ajustes primeiro.'}
            env = self._key_vault.get_env()
            if not env:
                return {'ok': False, 'message': 'Nenhuma chave Free configurada. Abra Ajustes.'}
            env['FREE_TIER_CONFIRMED'] = 'YES'
            env['MAX_REQUESTS_PER_RUN'] = '3'
            router = FreeAIRouter(env)
            from .teacher import teacher_answer
            result = teacher_answer(vault, question, mode, code,
                                    self._teacher_history, router)
            if result.get('ok'):
                self._teacher_history.append(
                    {'question': question[:600], 'answer': result['answer'][:1000]})
                self._teacher_history = self._teacher_history[-5:]
            return result
        except (ValueError, TypeError, NoFreeProvider, AllProvidersFailed, BudgetStopped, ProviderError) as exc:
            return {'ok': False, 'message': redact_sensitive(str(exc)[:200])}
        except (OSError, RuntimeError):
            return {'ok': False, 'message': 'Falha local ao consultar as aulas. Tente novamente.'}
        except Exception:
            # No raw model output or user content in error messages.
            return {'ok': False, 'message': 'O Professor não conseguiu consultar as notas; tente novamente.'}
        finally:
            if router is not None:
                self._teacher_requests += router.attempts
            self._teacher_lock.release()

    def teacher_reset(self):
        """Clear only volatile conversation context; never touch the Obsidian."""
        if not self._teacher_lock.acquire(blocking=False):
            return {'ok': False, 'message': 'Aguarde a resposta em andamento.'}
        try:
            self._teacher_history = []
            return {'ok': True}
        finally:
            self._teacher_lock.release()

    def ai_status(self):
        return {"configured":self._key_vault.configured(),
                "confirmed_free":self.settings.get('confirmed_free',False),
                "processing_consent":self.settings.get('ai_processing_consent',False) is True,
                "request_limit":12,
                "disclaimer":"Ative apenas projetos sem faturamento e contas Free. O TRAMA não consegue garantir o tipo de conta externamente."}

    def set_ai_processing_consent(self, allowed):
        """Optional persisted consent; revocable without deleting keys or notes.

        The UI must still let users work locally without an API. This setting
        authorizes only API operations that the user explicitly starts.
        """
        if type(allowed) is not bool:
            return {'ok':False,'message':'Escolha ativar ou desativar a autorização.'}
        previous = self.settings.get('ai_processing_consent', None)
        self.settings['ai_processing_consent'] = allowed
        try:
            self._save()
        except OSError:
            # Do not authorize outbound operations in RAM after a failed save.
            if previous is None:
                self.settings.pop('ai_processing_consent', None)
            else:
                self.settings['ai_processing_consent'] = previous
            return {'ok':False,'message':'Não foi possível salvar a preferência no Windows.'}
        return {'ok':True,'processing_consent':allowed,
                'message':'Envio autorizado para operações iniciadas por você.' if allowed
                          else 'Autorização revogada. Suas notas e chaves foram preservadas.'}

    def save_ai_key(self,provider,key,free_confirmed=False):
        if provider not in PROVIDERS:
            return {'ok':False,'message':'Provedor indisponível'}
        if free_confirmed is not True:
            return {'ok':False,'message':'Confirme que a chave pertence a um projeto GRATUITO sem faturamento.'}
        try:
            self._key_vault.save(provider,key)
            self.settings['confirmed_free']=True
            self._save()
            return {'ok':True,'message':'Chave protegida para este usuário Windows.'}
        except (OSError,ValueError,RuntimeError) as exc:
            return {'ok':False,'message':str(exc)[:140]}

    def remove_ai_key(self,provider):
        try:
            self._key_vault.remove(provider)
            return {'ok':True}
        except (OSError,ValueError,RuntimeError) as exc:
            return {'ok':False,'message':str(exc)[:140]}

    def test_ai(self, provider, mode="demo", confirmed=False):
        """Opt-in diagnostic: max two calls, ONE configured free-tier provider, no notes modified."""
        if provider not in ALLOWED or mode not in ("demo", "real"):
            return {"ok":False,"message":"Provedor ou tipo de teste inválido."}
        if confirmed is not True:
            return {"ok":False,"message":"Confirme o envio do conteúdo à IA externa."}
        if not self.settings.get('confirmed_free'):
            return {"ok":False,"message":"Cadastre uma chave de projeto Free sem faturamento antes."}
        if not self._write_lock.acquire(blocking=False):
            return {"ok":False,"message":"Já existe um processamento em andamento."}
        try:
            secured = self._key_vault.get_env()
            variable = ALLOWED[provider][1]
            if variable not in secured:
                return {"ok":False,"message":"Cadastre uma chave para o provedor escolhido."}
            # No fallback to other providers, no billed model, only 2 requests.
            router = FreeAIRouter({variable: secured[variable],
                                   "FREE_PROVIDER_ORDER":provider,
                                   "FREE_TIER_CONFIRMED":"YES", "MAX_REQUESTS_PER_RUN":"2"})
            result = run_ai_diagnostic(router,mode,self._vault())
            path = DATA_HOME / 'diagnosticos' / 'RELATORIO_TESTE_IA.txt'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(format_diagnostic_report(result),encoding='utf-8')
            return {"ok":True,"provider":result['provider'],"model":result['model'],
                    "requests":result['requests'],"concepts":len(result['concepts']),
                    "relations":len(result['relations']),"corrections":len(result['suggested_corrections']),
                    "discarded":result['invalid_references_discarded'],
                    "report":str(path),"mode":mode,
                    "message":"Teste concluído. Confira o relatório antes de compartilhá-lo."}
        except (MissingTestSources,NoFreeProvider,AllProvidersFailed,BudgetStopped,ProviderError,ValueError,OSError,RuntimeError,TypeError) as exc:
            # Known errors contain no provider response body or user token.
            return {"ok":False,"message":str(exc)[:220]}
        except Exception:
            # Fail closed: never expose raw exceptions or credentials to the UI.
            return {"ok":False,"message":"Resposta inesperada da IA. O teste não alterou notas; tente novamente mais tarde."}
        finally:
            self._write_lock.release()

    def open_ai_test_report(self):
        """Open only the known local diagnostic report; no user-supplied paths."""
        path = DATA_HOME / 'diagnosticos' / 'RELATORIO_TESTE_IA.txt'
        if not path.is_file():
            return {"ok":False,"message":"Execute um teste de IA primeiro."}
        try:
            if sys.platform == 'win32':
                os.startfile(str(path))
            else:
                webbrowser.open(path.as_uri())
            return {"ok":True}
        except (OSError,RuntimeError):
            return {"ok":False,"message":"Não foi possível abrir o relatório."}

    def _make_application(self,vault,log):
        app=Application(vault,CONFIG_FILE,log=log)
        # GUI never uses credentials from environment/config.env, which may belong
        # to a billed project or an unrelated application. Only DPAPI GUI keys.
        env={k:v for k,v in app.env.items() if k not in PROVIDERS.values()}
        secure=self._key_vault.get_env() if self.settings.get('confirmed_free') else {}
        env.update(secure)
        env['FREE_TIER_CONFIRMED']='YES' if secure else 'NO'
        app.ai=FreeAIRouter(env)
        return app

    @staticmethod
    def _processing_feedback(remaining, logs):
        """Explain incomplete work without guessing that a provider quota failed.

        These log messages are already redacted by the bridge. Raw exceptions,
        HTTP responses and user-provided keys must never reach the frontend.
        """
        count=len(remaining)
        message=next((line.split("Pausado sem cobrança: ",1)[1]
                      for line in reversed(logs)
                      if line.startswith("Pausado sem cobrança: ")), "")
        lower=message.casefold()
        if "429" in lower or "limite gratuito atingido" in lower:
            reason="api_quota"
            why="A API respondeu com limite de uso (429). Verifique a cota gratuita do provedor."
        elif "limite de segurança" in lower or "limite de requisições" in lower or "chamadas atingido" in lower:
            reason="local_limit"
            why="O limite local de chamadas do TRAMA nesta execução foi atingido."
        elif "max_tokens" in lower or "resposta cortada" in lower or " (length)" in lower:
            reason="truncated_ai_response"
            why="A API interrompeu a resposta por limite de saída. O resumo incompleto não foi publicado."
        elif "prompt bloqueado" in lower or "geração interrompida" in lower:
            reason="blocked_ai_response"
            why="A API interrompeu ou bloqueou a geração. Confira as regras do provedor."
        elif "resposta estruturada inválida" in lower or "resposta sem texto" in lower:
            reason="invalid_ai_response"
            why="O provedor não devolveu uma resposta estruturada válida."
        elif "nenhum provedor" in lower or "configure" in lower or "chave" in lower:
            reason="not_configured"
            why="Nenhum provedor gratuito configurado respondeu. Confira a chave em Ajustes."
        elif "falha http" in lower or "conexão" in lower or "tempo esgotado" in lower:
            reason="connection"
            why="A chamada ao provedor falhou ou demorou demais."
        elif any(row["status"]=="NEEDS_REVIEW" for row in remaining):
            reason="analysis_error"
            why="A análise encontrou uma resposta inesperada; revise o diagnóstico da IA."
        else:
            reason="incomplete"
            why="O processamento ficou incompleto. Execute o diagnóstico em Ajustes para identificar a causa."
        return {
            "ok":False,
            "reason":reason,
            "pending":count,
            "message":why+" "+str(count)+" gravação(ões) ainda pendente(s). "+
                      "As transcrições e os trechos já analisados foram preservados.",
            "logs":logs[-6:],
        }

    def process(self,confirmed=False):
        if confirmed is not True:return {'ok':False,'message':'Confirme o envio de transcrições para IA gratuita.'}
        vault=self._vault()
        if not vault:return {'ok':False,'message':'Configure o cofre primeiro.'}
        if not self._write_lock.acquire(blocking=False):return {'ok':False,'message':'Já existe um processamento em andamento.'}
        logs=[]
        app=None
        try:
            app=self._make_application(vault,log=lambda text:logs.append(redact_sensitive(str(text))[:600]))
            app.process()
            remaining=[src for src in app.store.sources("transcript")
                       if src["status"]!="PUBLISHED"]
            if remaining:
                return self._processing_feedback(remaining,logs)
        except Exception:
            # Exceptions from files or network may contain local paths or tokens.
            return {'ok':False,'message':'Não foi possível processar os materiais. Consulte as fontes locais.'}
        finally:
            try:
                if app is not None:app.close()
            finally:
                self._write_lock.release()
        return {'ok':True,'logs':logs[-8:]}

    def process_lesson(self, lesson, confirmed=False, force=False):
        """Resume pending segments by default; explicit full refresh is optional."""
        if confirmed is not True:
            return {'ok':False,'message':'Confirme o envio dos trechos desta aula à API configurada.'}
        if not isinstance(lesson,str) or not re.fullmatch(r'Aula-\d{3,4}',lesson):
            return {'ok':False,'message':'Identificador de aula inválido.'}
        vault=self._vault()
        if not vault:
            return {'ok':False,'message':'Selecione o cofre do Obsidian primeiro.'}
        if not self.settings.get('confirmed_free') or not any(self._key_vault.configured().values()):
            return {'ok':False,'message':'Configure e confirme sua chave Free em Ajustes.'}
        if not self._write_lock.acquire(blocking=False):
            return {'ok':False,'message':'Outro processamento está em andamento.'}
        logs=[]
        app=None
        try:
            app=self._make_application(vault,log=lambda text:logs.append(redact_sensitive(str(text))[:600]))
            matches=[src for src in app.store.sources("transcript") if src["lesson"]==lesson]
            if not matches:
                return {'ok':False,'message':'Nenhuma transcrição cadastrada para esta aula.'}
            app.process(lesson_filter=lesson,force=force is True)
            remaining=[src for src in app.store.sources("transcript")
                       if src["lesson"]==lesson and src["status"]!="PUBLISHED"]
            if remaining:
                return self._processing_feedback(remaining,logs)
            from .store import Store
            db=Store(vault)
            try:
                count,code_locks=db.github_lesson_refs(lesson)
            finally:
                db.close()
            needs_freeze=count<0 or count>len(code_locks)
            message='Análise da aula concluída; notas do Obsidian atualizadas.'
            if needs_freeze:
                message+=' Código GitHub pendente: congele a versão desta aula.'
            return {'ok':True,'message':message,
                    'code_shas':[{'role':row['role'],'repository_id':row['repository_id'],
                                  'sha':row['commit_sha']} for row in code_locks],
                    'code_pending_freeze':needs_freeze,'logs':logs[-8:]}
        except Exception:
            return {'ok':False,'message':'Não foi possível reanalisar a aula. As transcrições originais foram preservadas.'}
        finally:
            try:
                if app is not None:app.close()
            finally:
                self._write_lock.release()

    def lesson_code_config(self, lesson=""):
        """Read-only registration status, with raw invalid record for explicit local review."""
        from .lesson_code_config import read_config, lesson_dates
        vault=self._vault()
        if vault is None:
            return {"ok":False,"message":"Selecione o cofre do Obsidian."}
        result=read_config(vault)
        data=result["aulas"]
        return {"ok":not result["fatal"],"fatal":result["fatal"],"erros":result["erros"],
                "aulas":data if not lesson else {lesson:data[lesson]} if lesson in data else {},
                "invalid":{lesson:result["invalid"][lesson]} if lesson and lesson in result.get("invalid",{}) else {},
                "datas":lesson_dates(vault),
                "github_token_configurado":bool(os.environ.get("TRAMA_GITHUB_TOKEN") or self._key_vault.github_configured()),
                "github_token_fonte":("ambiente" if os.environ.get("TRAMA_GITHUB_TOKEN") else
                                       "dpapi" if self._key_vault.github_configured() else "nenhuma")}

    def lesson_code_changes(self, lesson, data):
        """Read-only preview of which frozen SHA slots an edit would invalidate."""
        from .github_lesson_state import preview_invalidations
        vault=self._vault()
        if vault is None:
            return {"ok":False,"message":"Selecione o cofre do Obsidian."}
        try:
            return {"ok":True,"invalidated":preview_invalidations(vault,lesson,data)}
        except (ValueError,TypeError,OSError,sqlite3.Error) as exc:
            return {"ok":False,"message":str(exc)[:350]}

    def save_lesson_code(self, lesson, data, confirmed=False, replace_invalid=False,
                         expected_digest="", confirm_unfreeze=False):
        from .github_lesson_state import persist_codes
        vault=self._vault()
        if not vault:return {"ok":False,"message":"Selecione o cofre do Obsidian."}
        if confirmed is not True:return {"ok":False,"message":"Confirme o cadastro GitHub desta aula."}
        if not self._write_lock.acquire(blocking=False):
            return {"ok":False,"message":"Já existe uma gravação ou processamento em andamento."}
        try:
            replacements=({lesson:expected_digest} if replace_invalid is True and
                          isinstance(expected_digest,str) and len(expected_digest)==64 else None)
            saved=persist_codes(vault,updates={lesson:data},replacements=replacements,
                                confirm_unfreeze=confirm_unfreeze)
            return {**saved,"message":"Associações GitHub da aula salvas no cofre."}
        except (ValueError,TypeError,OSError,sqlite3.Error) as exc:
            return {"ok":False,"message":str(exc)[:700]}
        finally:
            self._write_lock.release()

    def save_github_token(self, token, confirmed=False):
        if confirmed is not True:
            return {"ok":False,"message":"Confirme o armazenamento seguro do token GitHub."}
        if not isinstance(token,str):
            return {"ok":False,"message":"Token GitHub inválido."}
        vault=self._vault()
        if vault and self._key_vault.path.resolve().is_relative_to(vault.resolve()):
            return {"ok":False,"message":"O armazenamento de credenciais deve ficar fora do cofre."}
        try:
            self._key_vault.save("github",token)
            return {"ok":True,"message":"Token GitHub protegido por DPAPI neste Windows."}
        except (OSError,ValueError,RuntimeError) as exc:
            return {"ok":False,"message":str(exc)[:140]}

    def remove_github_token(self, confirmed=False):
        if confirmed is not True:
            return {"ok":False,"message":"Confirme a remoção do token GitHub."}
        try:
            self._key_vault.remove("github")
            return {"ok":True,"message":"Token GitHub seguro apagado; variável de ambiente, se houver, permanece."}
        except (OSError,ValueError,RuntimeError) as exc:
            return {"ok":False,"message":str(exc)[:140]}

    def remove_lesson_code(self, lesson, confirmed=False, expected_digest=""):
        from .github_lesson_state import persist_codes
        if confirmed is not True:
            return {"ok":False,"message":"Confirme explicitamente a remoção do cadastro GitHub."}
        vault=self._vault()
        if vault is None:
            return {"ok":False,"message":"Selecione o cofre do Obsidian."}
        if not self._write_lock.acquire(blocking=False):
            return {"ok":False,"message":"Há uma operação em andamento."}
        try:
            return persist_codes(vault,removal=lesson,expected_digest=expected_digest)
        except (ValueError,TypeError,OSError,sqlite3.Error) as exc:
            return {"ok":False,"message":str(exc)[:350]}
        finally:
            self._write_lock.release()

    def freeze_lesson_code(self, lesson, role, repository_id, confirmed=False, previous=False):
        """Freeze a version only on explicit user consent; reprocessing never repins."""
        from .lesson_code_config import read_config, LESSON_RE
        from .github_mapping import GithubMapping, MappingError
        from .store import Store
        if confirmed is not True:
            return {"ok":False,"message":"Confirme o congelamento do SHA para esta aula."}
        if (not isinstance(lesson,str) or not LESSON_RE.fullmatch(lesson)
                or role not in ("professor","dupla") or not isinstance(repository_id,str)
                or type(previous) is not bool):
            return {"ok":False,"message":"Aula ou repositório inválido."}
        vault=self._vault()
        if vault is None:
            return {"ok":False,"message":"Selecione o cofre do Obsidian."}
        if not self._write_lock.acquire(blocking=False):
            return {"ok":False,"message":"Há uma operação em andamento."}
        db=None
        try:
            config=read_config(vault)
            if config["fatal"] or lesson not in config["aulas"]:
                return {"ok":False,"message":"Cadastro GitHub desta aula inválido ou não encontrado."}
            entry=next((row for row in config["aulas"][lesson].get(role,[])
                        if row["id"]==repository_id),None)
            if entry is None:
                return {"ok":False,"message":"Repositório não está cadastrado nesta aula."}
            spec=entry.get("anterior") if previous else entry
            if not spec:
                return {"ok":False,"message":"Nenhuma referência anterior foi cadastrada."}
            slot="previous" if previous else "current"
            db=Store(vault)
            previous_lock=db.github_ref(lesson,role,repository_id,slot)
            client=GithubMapping()
            if previous_lock and previous_lock["private"] is not None:
                private=bool(previous_lock["private"])
            else:
                metadata=client._get(entry["repo"],"")
                if not isinstance(metadata,dict) or type(metadata.get("private")) is not bool:
                    raise MappingError("GitHub não confirmou se o repositório é privado.")
                private=metadata["private"]
            sha=(previous_lock["commit_sha"] if previous_lock else
                 client.resolve_sha(entry["repo"],spec["ref_tipo"],spec["ref"]))
            locked=db.freeze_github_ref(lesson,role,repository_id,slot,
                entry["repo"],spec["ref_tipo"],spec["ref"],spec.get("pasta",""),sha,private=private)
            return {"ok":True,"sha":locked["sha"],"created":locked["created"],
                    "private":locked["private"],"slot":slot,
                    "message":"SHA e privacidade congelados no SQLite; reprocessamentos manterão esta referência."}
        except (ValueError,TypeError,OSError,sqlite3.Error,MappingError) as exc:
            return {"ok":False,"message":str(exc)[:350]}
        finally:
            if db is not None:db.close()
            self._write_lock.release()

    def unfreeze_lesson_code(self, lesson, role, repository_id, slot, confirmed=False):
        """Destructive operation only on explicit consent; does not touch JSON or notes."""
        from .store import Store
        if confirmed is not True:
            return {"ok": False, "message": "Confirme o descongelamento desta referência GitHub."}
        vault = self._vault()
        if vault is None:
            return {"ok": False, "message": "Selecione o cofre do Obsidian."}
        if not self._write_lock.acquire(blocking=False):
            return {"ok": False, "message": "Há uma operação em andamento."}
        db = None
        try:
            db = Store(vault)
            removed = db.unfreeze_github_ref(lesson, role, repository_id, slot)
            return {"ok": removed,
                    "message": ("SHA descongelado; a próxima versão precisará ser congelada explicitamente."
                                if removed else "Não existe SHA congelado para essa referência.")}
        except (ValueError, TypeError, OSError, sqlite3.Error) as exc:
            return {"ok": False, "message": str(exc)[:300]}
        finally:
            if db is not None:
                db.close()
            self._write_lock.release()

    def frozen_lesson_code(self, lesson):
        """Read-only snapshots for the UI; never resolves a branch automatically."""
        from .lesson_code_config import read_config, LESSON_RE
        from .store import Store
        vault=self._vault()
        if vault is None or not isinstance(lesson,str) or not LESSON_RE.fullmatch(lesson):
            return {"ok":False,"message":"Cofre ou aula inválido."}
        config=read_config(vault)
        if config["fatal"] or lesson not in config["aulas"]:
            return {"ok":False,"message":"Nenhum cadastro GitHub válido nesta aula."}
        db=Store(vault)
        try:
            rows=db.conn.execute("""SELECT role,repository_id,slot,repo_url,ref_kind,
                         ref_name,folder,commit_sha,private,frozen_at FROM github_lesson_refs
                         WHERE lesson=? ORDER BY role,repository_id,slot""",(lesson,))
            return {"ok":True,"refs":[dict(row) for row in rows]}
        finally:
            db.close()

    def _lesson_code_binding(self, lesson, role, repository_id, slot="current"):
        """Only resolve code access from a registered, immutable SQLite commit."""
        from .github_cache import GithubCache
        from .github_code import GithubCodeReader
        from .lesson_code_config import read_config, LESSON_RE, ID_RE
        if (not isinstance(lesson, str) or not LESSON_RE.fullmatch(lesson)
                or role not in ("professor", "dupla")
                or not isinstance(repository_id, str) or not ID_RE.fullmatch(repository_id)
                or slot not in ("current", "previous")):
            raise ValueError("Aula, repositório ou versão inválida.")
        vault=self._vault()
        if vault is None:
            raise ValueError("Selecione o cofre do Obsidian.")
        config=read_config(vault)
        if config["fatal"]:
            raise ValueError("Cadastro GitHub inválido; revise antes de consultar código.")
        entry=next((item for item in config["aulas"].get(lesson,{}).get(role,[])
                    if item["id"]==repository_id),None)
        if entry is None:
            raise ValueError("Repositório não cadastrado nesta aula.")
        spec=entry.get("anterior") if slot=="previous" else entry
        if spec is None:
            raise ValueError("Cadastre a referência anterior e congele a versão desta aula.")
        db_path=vault/".base-conhecimento"/"estado.sqlite3"
        if not db_path.is_file() or db_path.is_symlink():
            raise ValueError("congele a versão desta aula")
        try:
            with closing(sqlite3.connect(db_path.as_uri()+"?mode=ro",uri=True,timeout=3)) as conn:
                conn.row_factory=sqlite3.Row
                row=conn.execute(
                    "SELECT * FROM github_lesson_refs WHERE lesson=? AND role=? "
                    "AND repository_id=? AND slot=?",
                    (lesson,role,repository_id,slot)).fetchone()
                locked=dict(row) if row else None
        except sqlite3.Error:
            locked=None
        if locked is None:
            raise ValueError("congele a versão desta aula")
        expected=(entry["repo"],spec["ref_tipo"],spec["ref"],spec.get("pasta",""))
        current=tuple(locked[k] for k in ("repo_url","ref_kind","ref_name","folder"))
        if current!=expected:
            raise ValueError("Cadastro e SHA divergentes; congele a versão desta aula.")
        reader=GithubCodeReader(cache=GithubCache(vault=vault))
        if locked["private"] is not None:
            reader._privacy[locked["repo_url"]]=bool(locked["private"])
        return reader, locked["repo_url"], locked["commit_sha"], locked["folder"]

    def _code_response(self, action):
        from .github_mapping import MappingError
        try:
            return {"ok":True, **action()}
        except (MappingError, ValueError, TypeError) as exc:
            return {"ok":False, "message":str(exc)[:300]}
        except (OSError,sqlite3.Error,RuntimeError):
            return {"ok":False, "message":"Falha ao consultar código GitHub; nenhum SHA foi alterado."}

    def lesson_code_files(self, lesson, role, repository_id, slot="current", folder=""):
        def action():
            reader,repo,sha,root=self._lesson_code_binding(lesson,role,repository_id,slot)
            selected=folder or root
            if root and selected!=root and not selected.startswith(root+"/"):
                raise ValueError("A pasta solicitada não pertence ao cadastro congelado.")
            return reader.list_files(repo,sha,selected)
        return self._code_response(action)

    def lesson_code_read_file(self, lesson, role, repository_id, path, slot="current"):
        def action():
            reader,repo,sha,root=self._lesson_code_binding(lesson,role,repository_id,slot)
            if not isinstance(path,str) or (root and not path.startswith(root+"/")):
                raise ValueError("Arquivo fora da pasta congelada desta aula.")
            return reader.read_file(repo,sha,path)
        return self._code_response(action)

    @staticmethod
    def _limit_code_diffs(result):
        """Bound WebView payloads without misreporting partial patches as complete."""
        rows=result.get("files",[])
        compact=[]
        shortened=False
        for file in rows[:25]:
            row=dict(file)
            patch=row.get("patch","")
            if isinstance(patch,str) and len(patch)>12000:
                row["patch"]=patch[:12000]
                shortened=True
            compact.append(row)
        return {**result,"files":compact,
                "truncated":bool(result.get("truncated") or len(rows)>25 or shortened)}

    def lesson_code_compare(self, lesson, role, repository_id):
        """Compare previous and current frozen revisions, never moving branches."""
        def action():
            reader,repo,head,folder=self._lesson_code_binding(lesson,role,repository_id,"current")
            _,old_repo,base,old_folder=self._lesson_code_binding(lesson,role,repository_id,"previous")
            if repo!=old_repo:
                raise ValueError("Repositórios diferentes não podem ser comparados.")
            return self._limit_code_diffs(
                reader.compare_commits(repo,base,head,folder if folder==old_folder else ""))
        return self._code_response(action)

    def lesson_code_diff_folders(self, lesson, role, repository_id, before, after, slot="current"):
        """Local-only diff between folders inside exactly one frozen commit."""
        def action():
            reader,repo,sha,_=self._lesson_code_binding(lesson,role,repository_id,slot)
            return self._limit_code_diffs(reader.diff_folders(repo,sha,before,after))
        return self._code_response(action)

    def preview_lesson_mappings(self, repo, dates=None, branch=""):
        """REST suggestions only. No file/database writes and no Git checkout."""
        from .github_mapping import preview_mapping, MappingError
        vault=self._vault()
        if vault is None:return {"ok":False,"message":"Selecione o cofre do Obsidian."}
        if not isinstance(repo,str) or len(repo)>300:
            return {"ok":False,"message":"Informe uma URL GitHub válida."}
        if dates is not None and (not isinstance(dates,dict) or len(dates)>500 or
                                  any(not isinstance(k,str) or not isinstance(v,str)
                                      or len(v)>10 for k,v in dates.items())):
            return {"ok":False,"message":"Datas inválidas para o mapeamento."}
        if not self._write_lock.acquire(blocking=False):
            return {"ok":False,"message":"Há um processamento em andamento."}
        try:
            self._mapping_preview=None
            result=preview_mapping(vault,repo,dates,branch)
            self._mapping_preview=result
            return {"ok":True,**result}
        except (MappingError,ValueError,OSError) as exc:
            return {"ok":False,"message":str(exc)[:350]}
        finally:
            self._write_lock.release()

    def suggest_lesson_mappings(self, dates):
        """Recalculate preview suggestions in Python; no network or persistent writes."""
        from .github_mapping import GithubMapping
        from datetime import date
        preview=self._mapping_preview
        if not preview:
            return {"ok":False,"message":"Consulte o repositório antes de alterar datas."}
        lessons={row["aula"] for row in preview["aulas"]}
        if not isinstance(dates,dict) or not 1<=len(dates)<=500:
            return {"ok":False,"message":"Informe as aulas e datas para sugerir."}
        for name, value in dates.items():
            if name not in lessons or not isinstance(value,str) or len(value)>10:
                return {"ok":False,"message":"Aula ou data não pertence ao mapeamento."}
            if value:
                try:date.fromisoformat(value)
                except ValueError:return {"ok":False,"message":f"{name}: data inválida."}
        return {"ok":True,"aulas":GithubMapping.suggestions(preview,preview["aulas"],dates)}

    def apply_lesson_mappings(self, selections, confirmed=False):
        """Only accept selections contained in the most recent read-only preview."""
        from .lesson_code_config import read_config, save_lessons, LESSON_RE
        import hashlib
        if confirmed is not True:return {"ok":False,"message":"Confirme as sugestões selecionadas."}
        vault=self._vault()
        if vault is None:return {"ok":False,"message":"Selecione o cofre do Obsidian."}
        if not isinstance(selections,list) or not 1<=len(selections)<=500:
            return {"ok":False,"message":"Selecione de 1 a 500 associações."}
        if not self._write_lock.acquire(blocking=False):
            return {"ok":False,"message":"Há um processamento em andamento."}
        try:
            preview=self._mapping_preview
            if not preview:return {"ok":False,"message":"Consulte as sugestões antes de confirmar."}
            candidates={item["id"]:item for item in preview["candidatos"]}
            lessons={item["aula"] for item in preview["aulas"]}
            current=read_config(vault)
            if current["fatal"]:
                return {"ok":False,"message":"Corrija o JSON inválido antes de salvar."}
            repo=preview["repo"]
            name=repo.split("/")[-1]
            source_key=repo+("\n"+preview["branch"] if preview.get("branch") else "")
            mapping_id="map-"+hashlib.sha256(source_key.encode()).hexdigest()[:16]
            updates={}
            used=set()
            for row in selections:
                if not isinstance(row,dict):
                    raise ValueError("Seleção inválida.")
                lesson=row.get("aula")
                ident=row.get("candidato_id")
                if (not isinstance(lesson,str) or not LESSON_RE.fullmatch(lesson) or
                        lesson not in lessons or lesson in used or ident not in candidates):
                    raise ValueError(f"Seleção inválida ou repetida: {lesson}")
                used.add(lesson)
                chosen=candidates[ident]
                if lesson in current["document"]["aulas"] and lesson not in current["aulas"]:
                    raise ValueError(f"{lesson}: cadastro existente inválido; corrija antes do mapeamento.")
                linked=current["aulas"].get(lesson) or {"professor":[],"dupla":[]}
                teachers=[item for item in linked.get("professor",[]) if item.get("id")!=mapping_id]
                item={"id":mapping_id,"rotulo":"Professor — "+name[:70],
                      "repo":repo,"ref_tipo":chosen["ref_tipo"],
                      "ref":chosen["ref"],"pasta":chosen["pasta"]}
                if row.get("confirmar_anterior") is True and chosen.get("sugestao_anterior"):
                    item["anterior"]=chosen["sugestao_anterior"]
                teachers.append(item)
                updates[lesson]={"professor":teachers,"dupla":linked.get("dupla",[])}
            from .github_lesson_state import persist_codes
            saved=persist_codes(vault,updates=updates,confirm_unfreeze=True)
            self._mapping_preview=None
            return {**saved,"message":f"{len(updates)} aula(s) confirmada(s); sugestões não selecionadas não foram gravadas."}
        except (ValueError,OSError,TypeError) as exc:
            return {"ok":False,"message":str(exc)[:700]}
        finally:
            self._write_lock.release()

    def add_repo(self,url):
        if not self._vault():return {'ok':False,'message':'Configure o cofre primeiro.'}
        if not isinstance(url,str) or not url.strip() or len(url)>1000:return {'ok':False,'message':'URL inválida'}
        if not self._write_lock.acquire(blocking=False):return {'ok':False,'message':'Já existe um processamento em andamento.'}
        app=None
        try:
            app=Application(self._vault(),CONFIG_FILE,log=lambda _s:None)
            app.add_repo(url.strip())
            automatic=app.assign_github_versions()
            app.publisher.rebuild()
            return {'ok':True,'automatic_versions':automatic.get('mapped',0),
                    'pending':automatic.get('pending',[])}
        except Exception:
            return {'ok':False,'message':'Não foi possível adicionar o repositório. Confira o endereço e tente novamente.'}
        finally:
            try:
                if app is not None:app.close()
            finally:
                self._write_lock.release()

    def recalculate_github_versions(self, repo, confirmed=False):
        """Re-evaluate automatic locks only, with explicit confirmation."""
        if confirmed is not True:
            return {'ok':False,'message':'Confirme o recálculo das versões automáticas.'}
        if not isinstance(repo,str) or len(repo)>300:
            return {'ok':False,'message':'URL do GitHub inválida.'}
        vault=self._vault()
        if not vault:
            return {'ok':False,'message':'Selecione o cofre do Obsidian.'}
        if not self._write_lock.acquire(blocking=False):
            return {'ok':False,'message':'Outro processamento está em andamento.'}
        app=None
        try:
            app=self._make_application(vault,log=lambda _s:None)
            result=app.recalculate_github_versions(repo)
            return {'ok':True,**result}
        except (ValueError,OSError,RuntimeError) as exc:
            return {'ok':False,'message':str(exc)[:250]}
        finally:
            if app is not None:app.close()
            self._write_lock.release()

    def toggle_favorite(self, note_id):
        idx=self._index()
        if not idx or not isinstance(note_id,str):
            return {'ok':False,'message':'Nota inválida'}
        selected=idx.by_relative.get(note_id.casefold())
        if selected is None:
            return {'ok':False,'message':'Nota não encontrada neste cofre.'}
        canonical=selected.relative
        previous=list(self.settings.get('favorites',[]))
        favorites={p for p in previous if isinstance(p,str)}
        old={p for p in favorites if p.casefold()==canonical.casefold()}
        if old:
            favorites.difference_update(old)
        else:
            favorites.add(canonical)
        self.settings['favorites']=sorted(favorites)[:200]
        try:
            self._save()
        except OSError:
            self.settings['favorites']=previous
            return {'ok':False,'message':'Não foi possível salvar o favorito no Windows.'}
        return {'ok':True,'favorites':self.settings['favorites']}

    def compare_proposal(self, proposal_id):
        """Read-only diff between one protected .PROPOSTA and its original note."""
        if not isinstance(proposal_id,str) or len(proposal_id)>500:
            return {'ok':False,'message':'Escolha uma proposta válida.'}
        idx=self._index()
        if idx is None:
            return {'ok':False,'message':'Conecte o Obsidian primeiro.'}
        proposal=idx.by_relative.get(proposal_id.casefold())
        if proposal is None:
            return {'ok':False,'message':'Proposta não encontrada.'}
        name=Path(proposal.relative).name
        match=re.fullmatch(r'(.+)\.PROPOSTA(?:-\d+)?\.md',name,re.I)
        if not match:
            return {'ok':False,'message':'Este arquivo não é uma proposta de atualização.'}
        original_rel=(Path(proposal.relative).parent/(match.group(1)+'.md')).as_posix()
        original=idx.by_relative.get(original_rel.casefold())
        if original is None:
            return {'ok':False,'message':'A nota original desta proposta não foi encontrada.'}
        from difflib import unified_diff
        from itertools import islice
        lines=unified_diff(original.content.splitlines(),proposal.content.splitlines(),
                           fromfile=original.relative,tofile=proposal.relative,lineterm='')
        bounded=list(islice(lines,501))
        return {'ok':True,'original':original.relative,'proposal':proposal.relative,
                'diff':'\n'.join(bounded[:500])[:28000],
                'truncated':len(bounded)>500}

    def copy_note_link(self, note_id):
        """Copy an indexed Obsidian wiki link using the native Windows clipboard.

        WebView clipboard APIs often fail when the application uses bundled
        offline HTML. No console, shell, subprocess or external network.
        """
        if not isinstance(note_id,str) or len(note_id)>500:
            return {'ok':False,'message':'Selecione uma nota válida.'}
        idx=self._index()
        note=idx.by_relative.get(note_id.casefold()) if idx else None
        if note is None or not note.relative.endswith('.md') or ']]' in note.relative:
            return {'ok':False,'message':'A nota não pertence ao cofre selecionado.'}
        wikilink='[['+note.relative[:-3]+']]'
        if sys.platform!='win32':
            return {'ok':False,'message':'A cópia nativa está disponível no Windows.',
                    'text':wikilink}
        import ctypes
        import time
        from ctypes import wintypes
        try:
            user32=ctypes.WinDLL('user32',use_last_error=True)
            kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
            user32.OpenClipboard.argtypes=[wintypes.HWND]
            user32.OpenClipboard.restype=wintypes.BOOL
            user32.EmptyClipboard.argtypes=[]
            user32.EmptyClipboard.restype=wintypes.BOOL
            user32.SetClipboardData.argtypes=[wintypes.UINT,wintypes.HANDLE]
            user32.SetClipboardData.restype=wintypes.HANDLE
            kernel32.GlobalAlloc.argtypes=[wintypes.UINT,ctypes.c_size_t]
            kernel32.GlobalAlloc.restype=wintypes.HANDLE
            kernel32.GlobalLock.argtypes=[wintypes.HANDLE]
            kernel32.GlobalLock.restype=ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes=[wintypes.HANDLE]
            kernel32.GlobalUnlock.restype=wintypes.BOOL
            kernel32.GlobalFree.argtypes=[wintypes.HANDLE]
            kernel32.GlobalFree.restype=wintypes.HANDLE
            opened=False
            for _ in range(4):
                if user32.OpenClipboard(None):
                    opened=True
                    break
                time.sleep(0.035)
            if not opened:
                return {'ok':False,'message':'A área de transferência está ocupada.',
                        'text':wikilink}
            # On success Windows owns the HGLOBAL, so never free it manually.
            handle=None
            try:
                buffer=ctypes.create_unicode_buffer(wikilink)
                handle=kernel32.GlobalAlloc(0x0002,ctypes.sizeof(buffer))
                if not handle:
                    raise OSError('GlobalAlloc failed')
                target=kernel32.GlobalLock(handle)
                if not target:
                    raise OSError('GlobalLock failed')
                ctypes.memmove(target,ctypes.addressof(buffer),ctypes.sizeof(buffer))
                kernel32.GlobalUnlock(handle)
                if not user32.EmptyClipboard():
                    raise OSError('EmptyClipboard failed')
                if not user32.SetClipboardData(13,handle):
                    raise OSError('SetClipboardData failed')
                handle=None
                return {'ok':True,'message':'Link interno copiado.'}
            finally:
                if handle:
                    kernel32.GlobalFree(handle)
                user32.CloseClipboard()
        except (OSError,AttributeError,ValueError):
            return {'ok':False,'message':'Não foi possível copiar automaticamente.',
                    'text':wikilink}

    def reveal_note(self,note_id):
        idx=self._index()
        if not idx or not isinstance(note_id,str):return {'ok':False}
        note=idx.by_relative.get(note_id.lower())
        if not note:return {'ok':False}
        try:
            import subprocess
            if sys.platform=='win32':subprocess.Popen(['explorer.exe','/select,',str(note.path)])
            elif sys.platform=='darwin':subprocess.Popen(['open','-R',str(note.path)])
            else:subprocess.Popen(['xdg-open',str(note.path.parent)])
            return {'ok':True}
        except OSError:return {'ok':False}

    def open_note(self,note_id):
        idx=self._index()
        if not idx or not isinstance(note_id,str):return {'ok':False}
        note=idx.by_relative.get(note_id.lower())
        if not note:return {'ok':False}
        uri='obsidian://open?vault='+quote(idx.vault.name)+'&file='+quote(note.relative.removesuffix('.md'))
        webbrowser.open(uri)
        return {'ok':True}

    def open_obsidian(self):
        path=self._vault()
        if not path:return {'ok':False}
        webbrowser.open('obsidian://open?vault='+quote(path.name))
        return {'ok':True}

    @staticmethod
    def _valid_video_url(url):
        from urllib.parse import urlsplit
        if (not isinstance(url,str) or len(url)>1700 or
                any(ord(c)<32 or ord(c)==127 for c in url) or
                any(c.isspace() for c in url) or
                any(c in url for c in ('<','>','\\'))):
            return False
        try:
            parts=urlsplit(url)
            # hostname and port properties can throw for malformed URLs.
            port=parts.port
            return (parts.scheme in ('http','https') and bool(parts.hostname) and
                    parts.username is None and parts.password is None and
                    (port is None or port>0))
        except ValueError:
            return False

    def open_video_link(self,url):
        """Apenas URLs cadastradas pelo usuário; não aceita protocolos arbitrários."""
        vault=self._vault()
        if vault is None or not self._valid_video_url(url):
            return {'ok':False,'message':'Link de vídeo inválido.'}
        db=vault/'.base-conhecimento'/'estado.sqlite3'
        if not db.is_file():
            return {'ok':False,'message':'Link não registrado no cofre.'}
        allowed=False
        try:
            with closing(sqlite3.connect(db.as_uri() + '?mode=ro',uri=True,timeout=2)) as con:
                for (stored,) in con.execute("SELECT stored_path FROM sources WHERE kind='classroom'"):
                    record=self._safe_classroom_record(vault,stored)
                    rows=record.get('videos',[]) if record else []
                    if isinstance(rows,list) and any(
                            isinstance(row,dict) and row.get('url') == url
                            for row in rows[:30]):
                        allowed=True
                        break
        except (OSError,sqlite3.Error):
            return {'ok':False,'message':'Não foi possível verificar o link do vídeo.'}
        if not allowed:
            return {'ok':False,'message':'Link não registrado no cofre.'}
        return {'ok':bool(webbrowser.open(url))}

    def open_code_link(self, address):
        """Open only an indexed GitHub file at its verified commit and line.

        Markdown from a transcript or model must not turn the desktop bridge
        into an arbitrary browser opener. Only known repository evidence is
        eligible; arbitrary https URLs are not accepted.
        """
        from urllib.parse import urlsplit, unquote
        vault = self._vault()
        if (vault is None or not isinstance(address, str) or len(address) > 1250 or
                any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in address)):
            return {'ok': False, 'message': 'Referência GitHub inválida.'}
        try:
            url = urlsplit(address)
            if (url.scheme != "https" or url.hostname != "github.com" or
                    url.username is not None or url.password is not None or
                    url.port not in (None, 443) or url.query):
                return {'ok': False, 'message': 'Apenas links GitHub verificados são permitidos.'}
        except ValueError:
            return {'ok': False, 'message': 'Link GitHub inválido.'}
        parts = url.path.split("/")
        if len(parts) < 6 or parts[3] != "blob":
            return {'ok': False, 'message': 'O link precisa apontar para um arquivo GitHub.'}
        owner, name, sha = parts[1], parts[2], parts[4]
        if (not all(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", x) for x in (owner,name)) or
                not re.fullmatch(r"[a-fA-F0-9]{40}", sha)):
            return {'ok': False, 'message': 'Revisão GitHub inválida.'}
        path = unquote("/".join(parts[5:]))
        if (not path or "\\" in path or ":" in path or
                any(x in (".", "..", "") for x in path.split("/")) or
                any(ord(c) < 32 or ord(c) == 127 for c in path)):
            return {'ok': False, 'message': 'Caminho de código inválido.'}
        match = re.fullmatch(r"L([1-9][0-9]{0,7})", url.fragment)
        if not match:
            return {'ok': False, 'message': 'Informe uma linha verificada do código.'}
        lineno = int(match.group(1))
        db = vault / ".base-conhecimento" / "estado.sqlite3"
        if not db.is_file():
            return {'ok': False, 'message': 'Nenhum repositório indexado neste cofre.'}
        repo_url = f"https://github.com/{owner}/{name}"
        try:
            with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
                found = conn.execute(
                    "SELECT payload FROM repositories WHERE url=? AND sha=? LIMIT 1",
                    (repo_url, sha)
                ).fetchone()
            if not found:
                return {'ok': False, 'message': 'Este commit não está indexado no TRAMA.'}
            payload=json.loads(found[0])
            evidence=payload.get("evidence",[])
            symbols=payload.get("symbols",[])
            if not isinstance(evidence,list) or not isinstance(symbols,list) or not any(
                    isinstance(e,dict) and e.get('path') == path and e.get('line') == lineno
                    for e in [*evidence[:160],*symbols[:240]]):
                return {'ok': False, 'message': 'Essa linha não foi verificada no índice de código.'}
        except (OSError, ValueError, TypeError, sqlite3.Error):
            return {'ok': False, 'message': 'Não foi possível conferir o índice GitHub.'}
        safe = f"{repo_url}/blob/{sha}/{quote(path, safe='/')}#L{lineno}"
        return {'ok': bool(webbrowser.open(safe)),
                'message': 'Referência aberta no navegador.'}

    def open_attachment(self,stored):
        """Open only media imported into this vault's SQLite catalog.

        The JS bridge must never become an arbitrary local file opener.
        """
        vault=self._vault()
        if (vault is None or not isinstance(stored,str) or not stored or
                len(stored)>700 or '\\' in stored or
                any(p in ('.','..') for p in stored.split('/'))):
            return {'ok':False}
        path=(vault/stored).resolve()
        if (not path.is_relative_to(vault) or not path.is_file() or
                path.suffix.lower() not in ALLOWED_ATTACHMENTS):
            return {'ok':False}
        db=vault/'.base-conhecimento'/'estado.sqlite3'
        if not db.is_file():
            return {'ok':False}
        try:
            with closing(sqlite3.connect(
                    db.as_uri() + '?mode=ro',uri=True,timeout=2)) as con:
                registered=con.execute(
                    "SELECT 1 FROM sources WHERE stored_path=? "
                    "AND kind IN ('video','transcript','material') LIMIT 1",
                    (stored,)).fetchone()
            if not registered:
                return {'ok':False}
        except (sqlite3.Error,OSError,ValueError):
            return {'ok':False}
        try:
            if sys.platform=='win32':os.startfile(str(path))
            else:
                import subprocess
                subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',str(path)])
            return {'ok':True}
        except OSError:
            return {'ok':False}



    def window_action(self, action):
        if not self._window or action not in ('minimize','maximize','fullscreen','close'):
            return {'ok':False}
        if action=='minimize':self._window.minimize()
        elif action=='maximize':
            if self._is_maximized:self._window.restore()
            else:self._window.maximize()
            self._is_maximized=not self._is_maximized
        elif action=='fullscreen':
            self._window.toggle_fullscreen()
            self._is_fullscreen=not self._is_fullscreen
        elif action=='close':self._window.destroy()
        return {'ok':True}

class PublicApi:
    """Small explicit JS API; avoids exposing native WebView/GUI objects.

    pywebview introspects the whole js_api object, including public attributes.
    Exposing a `Bridge.window` native Window here can recursively traverse its
    event/GUI object graph and cause a recursion-depth crash on Windows.
    The actual Window is kept private inside Bridge; only primitive-returning
    actions below are visible to JavaScript.
    """
    __slots__ = ("_bridge",)

    def __init__(self, bridge: Bridge):
        self._bridge = bridge

    def snapshot(self):
        return self._bridge.snapshot()

    def vault_disk_usage(self):
        return self._bridge.vault_disk_usage()

    def note(self, note_id):
        return self._bridge.note(note_id)

    def graph(self):
        return self._bridge.graph()

    def search_notes(self, query, limit=80):
        return self._bridge.search_notes(query, limit)

    def audit_note(self, note_id):
        return self._bridge.audit_note(note_id)

    def organize_library(self, confirmed=False):
        return self._bridge.organize_library(confirmed)

    def backup_vault(self, confirmed=False):
        return self._bridge.backup_vault(confirmed)

    def restore_vault(self, confirmed=False):
        return self._bridge.restore_vault(confirmed)

    def select_vault(self):
        return self._bridge.select_vault()

    def import_materials(self):
        return self._bridge.import_materials()

    def staged_items(self):
        return self._bridge.staged_items()

    def stage_files(self):
        return self._bridge.stage_files()

    def stage_clipboard_image(self, data_url):
        return self._bridge.stage_clipboard_image(data_url)

    def remove_staged(self, ident):
        return self._bridge.remove_staged(ident)

    def clear_staged(self):
        return self._bridge.clear_staged()

    def process_staged(self, links='', confirmed=False):
        return self._bridge.process_staged(links,confirmed)

    def auto_import(self, links='', confirmed=False, pick_files=True):
        return self._bridge.auto_import(links,confirmed,pick_files)

    def process(self, confirmed=False):
        return self._bridge.process(confirmed)

    def process_lesson(self, lesson, confirmed=False, force=False):
        return self._bridge.process_lesson(lesson, confirmed, force)

    def lesson_code_config(self, lesson=""):
        return self._bridge.lesson_code_config(lesson)

    def save_lesson_code(self, lesson, data, confirmed=False, replace_invalid=False,
                         expected_digest="", confirm_unfreeze=False):
        return self._bridge.save_lesson_code(lesson,data,confirmed,replace_invalid,
                                             expected_digest,confirm_unfreeze)

    def lesson_code_changes(self, lesson, data):
        return self._bridge.lesson_code_changes(lesson,data)

    def save_github_token(self, token, confirmed=False):
        return self._bridge.save_github_token(token,confirmed)

    def remove_github_token(self, confirmed=False):
        return self._bridge.remove_github_token(confirmed)

    def remove_lesson_code(self, lesson, confirmed=False, expected_digest=""):
        return self._bridge.remove_lesson_code(lesson,confirmed,expected_digest)

    def freeze_lesson_code(self, lesson, role, repository_id, confirmed=False, previous=False):
        return self._bridge.freeze_lesson_code(lesson,role,repository_id,confirmed,previous)

    def frozen_lesson_code(self, lesson):
        return self._bridge.frozen_lesson_code(lesson)

    def unfreeze_lesson_code(self, lesson, role, repository_id, slot, confirmed=False):
        return self._bridge.unfreeze_lesson_code(lesson,role,repository_id,slot,confirmed)

    def lesson_code_files(self, lesson, role, repository_id, slot="current", folder=""):
        return self._bridge.lesson_code_files(lesson,role,repository_id,slot,folder)

    def lesson_code_read_file(self, lesson, role, repository_id, path, slot="current"):
        return self._bridge.lesson_code_read_file(lesson,role,repository_id,path,slot)

    def lesson_code_compare(self, lesson, role, repository_id):
        return self._bridge.lesson_code_compare(lesson,role,repository_id)

    def lesson_code_diff_folders(self, lesson, role, repository_id, before, after, slot="current"):
        return self._bridge.lesson_code_diff_folders(lesson,role,repository_id,before,after,slot)

    def preview_lesson_mappings(self, repo, dates=None, branch=""):
        return self._bridge.preview_lesson_mappings(repo,dates,branch)

    def suggest_lesson_mappings(self, dates):
        return self._bridge.suggest_lesson_mappings(dates)

    def apply_lesson_mappings(self, selections, confirmed=False):
        return self._bridge.apply_lesson_mappings(selections,confirmed)

    def add_repo(self, url):
        return self._bridge.add_repo(url)

    def recalculate_github_versions(self, repo, confirmed=False):
        return self._bridge.recalculate_github_versions(repo,confirmed)

    def toggle_favorite(self, note_id):
        return self._bridge.toggle_favorite(note_id)

    def reveal_note(self, note_id):
        return self._bridge.reveal_note(note_id)

    def copy_note_link(self, note_id):
        return self._bridge.copy_note_link(note_id)

    def compare_proposal(self, proposal_id):
        return self._bridge.compare_proposal(proposal_id)

    def open_note(self, note_id):
        return self._bridge.open_note(note_id)

    def open_obsidian(self):
        return self._bridge.open_obsidian()

    def open_attachment(self, stored):
        return self._bridge.open_attachment(stored)

    def open_video_link(self, url):
        return self._bridge.open_video_link(url)

    def open_code_link(self, url):
        return self._bridge.open_code_link(url)

    def window_action(self, action):
        return self._bridge.window_action(action)

    def save_classroom_context(self, data):
        return self._bridge.save_classroom_context(data)

    def import_classroom_materials(self, lesson):
        return self._bridge.import_classroom_materials(lesson)

    def check_updates(self):
        return self._bridge.check_updates()

    def prepare_update(self, confirmed=False):
        return self._bridge.prepare_update(confirmed)

    def launch_update(self, path, confirmed=False):
        return self._bridge.launch_update(path, confirmed)

    def open_update_page(self, address):
        return self._bridge.open_update_page(address)

    def search_transcript(self, stored, query):
        return self._bridge.search_transcript(stored, query)

    def teacher_ask(self, question, mode="explicar", code="", confirmed=False):
        return self._bridge.teacher_ask(question, mode, code, confirmed)

    def teacher_reset(self):
        return self._bridge.teacher_reset()

    def ai_status(self):
        return self._bridge.ai_status()

    def set_ai_processing_consent(self, allowed):
        return self._bridge.set_ai_processing_consent(allowed)

    def save_ai_key(self, provider, key, free_confirmed=False):
        return self._bridge.save_ai_key(provider,key,free_confirmed)

    def remove_ai_key(self, provider):
        return self._bridge.remove_ai_key(provider)

    def test_ai(self, provider, mode="demo", confirmed=False):
        return self._bridge.test_ai(provider,mode,confirmed)

    def open_ai_test_report(self):
        return self._bridge.open_ai_test_report()


def load_local_ui():
    """Create the same self-contained, offline HTML used by the Windows window."""
    base=Path(__file__).resolve().parent/'ui'
    html=(base/'index.html').read_text(encoding='utf-8')
    substitutions=(('style.css','style.css'),('library.css','library.css'),
                   ('classic.css','classic.css'),('faithful.css','faithful.css'),
                   ('graph.css','graph.css'))
    # The packaged window requires inline local assets. Keep a strict CSP
    # with exact SHA-256 hashes of the bundled CSS and JS, instead of removing
    # the policy and allowing any injected script to execute.
    html=re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', '', html)
    styles=[];scripts=[]
    def content_hash(source):
        digest=hashlib.sha256(source.encode('utf-8')).digest()
        return "'sha256-" + base64.b64encode(digest).decode('ascii') + "'"
    for href,filename in substitutions:
        css=(base/filename).read_text(encoding='utf-8')
        styles.append(content_hash(css))
        html=html.replace(f'<link rel="stylesheet" href="{href}">','<style>'+css+'</style>')
    for script in ('library.js','graph.js','app.js','lesson_code.js','teacher.js'):
        js=(base/script).read_text(encoding='utf-8')
        scripts.append(content_hash(js))
        html=html.replace(f'<script src="{script}"></script>','<script>'+js+'</script>')
    csp=("default-src 'none'; style-src " + " ".join(styles) +
         "; script-src " + " ".join(scripts) +
         "; img-src data:; connect-src 'none'; font-src 'none'; " +
         "base-uri 'none'; form-action 'none'")
    html=html.replace('</head>', '<meta http-equiv="Content-Security-Policy" content="' +
                      csp + '">\n</head>')
    return html

def start_webview():
    """Janela nativa WebView2, HTML/CSS/JS empacotados, sem servidor de aplicação."""
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError('Instale a dependência gratuita: py -m pip install pywebview') from exc
    api=Bridge()
    html=load_local_ui()
    window=webview.create_window('TRAMA',html=html,
                                 js_api=PublicApi(api),width=1280,height=820,min_size=(850,560),resizable=True,frameless=False,easy_drag=False,shadow=True,background_color='#f2f3f0')
    api._window=window
    # Keep the classic restore/maximize button in sync when the user uses the
    # native Windows titlebar or the Windows keyboard shortcuts instead.
    try:
        window.events.maximized += lambda *args: setattr(api, '_is_maximized', True)
        window.events.restored += lambda *args: setattr(api, '_is_maximized', False)
    except (AttributeError, TypeError):
        # A minimal/mocked GUI implementation may not expose window events.
        pass
    webview.start(debug=False)
