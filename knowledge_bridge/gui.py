"""TRAMA — janela desktop clássica, conectada ao mesmo cofre do Obsidian.

A interface é uma visualização SOMENTE LEITURA das notas Markdown. O motor
incremental continua em pipeline.py/publishing.py; não há banco paralelo para
biblioteca, scripts remotos, navegador embutido ou dependências de interface.
"""
from __future__ import annotations
from contextlib import closing

from collections import defaultdict
from datetime import datetime
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import urllib.parse
import webbrowser

from .gui_legacy import TramaApp as BaseApp, FONT, MONO, CONFIG_FILE, read_env, ALLOWED
from .vault_index import VaultIndex, VaultNote, WIKI_RE

PAL = {
    'frame': '#f4f6f3', 'title': '#f9faf8', 'white': '#ffffff',
    'sidebar': '#edf1ed', 'toolbar': '#f7f9f6', 'line': '#dce4dc',
    'text': '#24312b', 'secondary': '#5f7067', 'faint': '#88978f',
    'accent': '#3e7958', 'accent_dark': '#2b6044', 'accent_soft': '#e7f2e9',
    'border_light': '#e9eee9', 'badge': '#edf4ed',
    'blue': '#647e9b', 'purple': '#81719f', 'orange': '#a87d51',
}


def text(parent, string, size=9, bold=False, color=None, bg=None, wrap=None, **kw):
    return tk.Label(parent, text=string, bg=bg or parent.cget('bg'),
                    fg=color or PAL['text'], anchor='w', justify='left',
                    font=(FONT, size, 'bold' if bold else 'normal'),
                    wraplength=wrap or 0, **kw)


def line(parent, vertical=False):
    return tk.Frame(parent, bg=PAL['line'], width=1 if vertical else 0,
                    height=0 if vertical else 1)


def action(parent, caption, command, main=False, small=False, icon=''):
    b = tk.Button(parent, text=f'{icon}  {caption}' if icon else caption, command=command,
                  bg=PAL['accent'] if main else PAL['white'],
                  fg='#ffffff' if main else PAL['text'],
                  activebackground=PAL['accent_dark'] if main else PAL['accent_soft'],
                  activeforeground='#ffffff' if main else PAL['accent_dark'],
                  relief='solid', bd=1, highlightthickness=0,
                  highlightbackground=PAL['accent'] if main else PAL['line'],
                  cursor='hand2', padx=12 if not small else 8,
                  pady=6 if not small else 4, font=(FONT, 9, 'bold' if main else 'normal'))
    return b


def clickable_label(parent, caption, callback, color=None, size=9):
    w = text(parent, caption, size=size, color=color or PAL['accent'])
    w.configure(cursor='hand2')
    w.bind('<Button-1>', lambda _e: callback())
    return w


class TramaDesktop(BaseApp):
    """Um leitor do cofre real + importador, com visual de utilitário Windows."""
    def __init__(self, root):
        self.selected_rel = None
        self.selected_graph = None
        self.index: VaultIndex | None = None
        self.graph_zoom = 1.0
        self.graph_offset = (0.0, 0.0)
        self.graph_positions = []
        self.lesson_tab = 'Resumo'
        super().__init__(root)
        # Abrir na tela semelhante à prévia aprovada.
        self.navigate('aulas')

    def _logo(self, parent, size=32):
        can = tk.Canvas(parent, width=size, height=size, bg=parent.cget('bg'),
                        highlightthickness=0, bd=0)
        s = size / 36
        coords = [(6, 11), (17, 6), (29, 15), (17, 29), (6, 24)]
        can.create_line(*[v * s for point in coords for v in point],
                        fill=PAL['accent'], width=2.2*s, smooth=False,
                        joinstyle=tk.ROUND)
        can.create_line(6*s, 11*s, 17*s, 29*s, 29*s, 15*s, 6*s, 24*s,
                        fill='#8cab99', width=1.7*s)
        for x, y in coords:
            can.create_oval((x-3)*s, (y-3)*s, (x+3)*s, (y+3)*s,
                            outline='#ffffff', width=1*s, fill=PAL['accent'])
        return can

    def _shell(self):
        self.root.title('TRAMA — Seu conhecimento, organizado')
        self.root.geometry('1430x860')
        self.root.minsize(1040, 655)
        self.root.configure(bg=PAL['frame'])
        # 1. Marca e barra de título própria DENTRO da janela nativa do Windows.
        banner = tk.Frame(self.root, bg=PAL['title'], height=62)
        banner.pack(fill='x'); banner.pack_propagate(False)
        brand = tk.Frame(banner, bg=PAL['title'])
        brand.pack(side='left', padx=(19,0), pady=10)
        self._logo(brand, 38).pack(side='left', padx=(0,10))
        bt = tk.Frame(brand, bg=PAL['title']); bt.pack(side='left')
        text(bt, 'TRAMA', 15, True).pack(anchor='w')
        text(bt, 'Seu conhecimento, organizado.', 8, color=PAL['secondary']).pack(anchor='w')
        self.connection = text(banner, '●  Selecione seu cofre do Obsidian', 9,
                               color=PAL['secondary'])
        self.connection.pack(side='right', padx=24)
        line(self.root).pack(fill='x')

        # 2. Barra de ferramentas — ações com comportamento real.
        tools = tk.Frame(self.root, bg=PAL['toolbar'], height=53)
        tools.pack(fill='x'); tools.pack_propagate(False)
        action(tools,'Importar aulas',self._pick_files,True,icon='+').pack(side='left',padx=(18,7),pady=8)
        action(tools,'Gerar resumos',self._process,icon='▤').pack(side='left',padx=(0,7),pady=8)
        action(tools,'Abrir Obsidian',self._open_obsidian,icon='◇').pack(side='left',padx=(0,7),pady=8)
        action(tools,'GitHub',self._repo_prompt,icon='⌘').pack(side='left',padx=(0,7),pady=8)
        action(tools,'Atualizar',lambda:self.navigate(self.current),small=True).pack(side='left',padx=(0,3),pady=9)
        self.root.bind('<Control-r>',lambda _e:self.navigate(self.current))
        self.search_var = tk.StringVar()
        search_wrap = tk.Frame(tools, bg=PAL['line'], padx=1, pady=1)
        search_wrap.pack(side='left',fill='x',expand=True,padx=(20,5),pady=10)
        entry=tk.Entry(search_wrap,textvariable=self.search_var,relief='flat',bd=0,
                       bg=PAL['white'],fg=PAL['text'],insertbackground=PAL['text'],font=(FONT,9))
        entry.pack(fill='both',expand=True,ipady=6,padx=9)
        entry.bind('<Return>',lambda _e: self._search())
        action(tools,'Buscar',self._search,small=True).pack(side='left',padx=(0,14),pady=10)
        line(self.root).pack(fill='x')

        # 3. Conteúdo principal: barra lateral + painéis configuráveis.
        window = tk.Frame(self.root, bg=PAL['frame'])
        window.pack(fill='both',expand=True)
        sidebar=tk.Frame(window,bg=PAL['sidebar'],width=184)
        sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        self.nav={}
        for key,cap,glyph in [
            ('inicio','Início','⌂'),('aulas','Aulas','▣'),('conhecimento','Conhecimento','◈'),
            ('projetos','Projetos','▱'),('biblioteca','Biblioteca','▤'),
            ('grafo','Grafo de conexões','◎'),('config','Ajustes','⚙')]:
            if key in ('conhecimento','config'):
                line(sidebar).pack(fill='x',padx=18,pady=(9,8))
            item=tk.Frame(sidebar,bg=PAL['sidebar'],height=43)
            item.pack(fill='x',padx=9,pady=1);item.pack_propagate(False)
            glyphlabel=text(item,glyph,14,color=PAL['secondary'])
            glyphlabel.pack(side='left',padx=(12,11))
            lab=text(item,cap,9,color=PAL['secondary'])
            lab.pack(side='left',fill='both',expand=True)
            self.nav[key]=(item,glyphlabel,lab)
            for w in (item,glyphlabel,lab):
                w.configure(cursor='hand2')
                w.bind('<Button-1>',lambda _e,k=key: self.navigate(k))
        tk.Frame(sidebar,bg=PAL['sidebar']).pack(fill='both',expand=True)
        text(sidebar,'ARQUIVOS LOCAIS',8,True,color=PAL['accent']).pack(anchor='w',padx=19)
        text(sidebar,'As notas continuam no Obsidian.',8,color=PAL['secondary'],wrap=150).pack(
            anchor='w',padx=19,pady=(6,18))
        line(window,True).pack(side='left',fill='y')
        self.workspace=tk.Frame(window,bg=PAL['frame'])
        self.workspace.pack(side='left',fill='both',expand=True)
        # Rodapé discreto, com estatísticas reais e status de execução.
        line(self.root).pack(fill='x')
        bottom=tk.Frame(self.root,bg=PAL['title'],height=32)
        bottom.pack(fill='x');bottom.pack_propagate(False)
        self.footer_label=text(bottom,self.status.get(),8,color=PAL['secondary'])
        self.footer_label.pack(side='left',padx=17,pady=8)
        self.footer_count=text(bottom,'',8,color=PAL['secondary'])
        self.footer_count.pack(side='right',padx=18,pady=8)

    def _index(self):
        path=Path(self.vault.get()).expanduser()
        try:
            self.index=VaultIndex(path)
        except (PermissionError,OSError):
            self.index=VaultIndex(Path('__cofre_indisponivel__'))
        valid=path.is_dir()
        self.connection.configure(
            text=('●  Biblioteca do Obsidian vinculada' if valid else '○  Configure a pasta do Obsidian'),
            fg=PAL['accent'] if valid else PAL['secondary'])
        counts=self._counts()
        self.footer_count.configure(text=(
            f"{counts['transcript']} transcrições   ·   {counts['video']} vídeos   ·   "
            f"{counts['repo']} projetos   ·   {len(self.index.notes)} notas  |  v0.6"))

    def navigate(self,page):
        if page not in self.nav:
            page='inicio'
        self.current=page
        self._index()
        for key,(frame,ic,lab) in self.nav.items():
            selected=page==key
            bg=PAL['accent_soft'] if selected else PAL['sidebar']
            frame.configure(bg=bg)
            ic.configure(bg=bg,fg=PAL['accent_dark'] if selected else PAL['secondary'])
            lab.configure(bg=bg,fg=PAL['accent_dark'] if selected else PAL['secondary'],
                          font=(FONT,9,'bold' if selected else 'normal'))
        for w in self.workspace.winfo_children():
            w.destroy()
        {
            'inicio': self._home,
            'aulas': lambda:self._notes_page('aulas'),
            'conhecimento': lambda:self._notes_page('conhecimento'),
            'projetos': lambda:self._notes_page('projetos'),
            'biblioteca': lambda:self._notes_page('biblioteca'),
            'grafo':self._graph_page,
            'config':self._config,
        }[page]()

    def _set_status(self,message):
        self.status.set(message)
        self.footer_label.configure(text=message)

    def _search(self):
        q=self.search_var.get().strip()
        if not q:
            self.navigate('biblioteca');return
        self.navigate('biblioteca')

    def _subhead(self,parent,heading,subtitle=''):
        bar=tk.Frame(parent,bg=PAL['white'],height=73)
        bar.pack(fill='x');bar.pack_propagate(False)
        t=tk.Frame(bar,bg=PAL['white'])
        t.pack(side='left',fill='x',expand=True,padx=18,pady=13)
        text(t,heading,12,True).pack(anchor='w')
        if subtitle:
            text(t,subtitle,8,color=PAL['secondary']).pack(anchor='w',pady=(4,0))
        line(parent).pack(fill='x')
        return bar

    def _pane(self,parent,width=None):
        p=tk.Frame(parent,bg=PAL['white'],width=width)
        if width:
            p.pack_propagate(False)
        return p

    def _pill(self,parent,value,color=None):
        return text(parent,value,8,False,color or PAL['accent_dark'],bg=PAL['badge'],padx=8,pady=4)

    def _list_notes(self,parent,notes,category,selected):
        """Lista rolável de notas reais, sem dados de exemplo inventados."""
        body=tk.Frame(parent,bg=PAL['white'])
        body.pack(fill='both',expand=True)
        canvas=tk.Canvas(body,bg=PAL['white'],highlightthickness=0,bd=0)
        bar=ttk.Scrollbar(body,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        inside=tk.Frame(canvas,bg=PAL['white'])
        inside_id=canvas.create_window((0,0),window=inside,anchor='nw')
        inside.bind('<Configure>',lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfig(inside_id,width=e.width))
        canvas.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120),'units'))
        if not notes:
            text(inside,'Nenhuma nota encontrada.',9,color=PAL['secondary'],wrap=200).pack(
                anchor='w',padx=15,pady=19)
            return
        if len(notes)>800:
            notes=notes[:800]
        for note in notes:
            is_selected=selected and note.relative==selected.relative
            bg=PAL['accent_soft'] if is_selected else PAL['white']
            row=tk.Frame(inside,bg=bg,padx=13,pady=10)
            row.pack(fill='x',padx=7,pady=2)
            first=note.title
            if len(first)>53:
                first=first[:50]+'…'
            caption=text(row,first,9,True,color=PAL['accent_dark'] if is_selected else PAL['text'],bg=bg,wrap=225)
            caption.pack(anchor='w',fill='x')
            subtitle=note.relative.split('/',1)[-1]
            if len(subtitle)>51:
                subtitle=subtitle[:48]+'…'
            text(row,subtitle,8,color=PAL['secondary'],bg=bg).pack(anchor='w',pady=(4,0))
            for widget in (row,caption):
                widget.configure(cursor='hand2')
                widget.bind('<Button-1>',lambda _e,ref=note.relative:self._select_note(ref,category))

    def _folder_tree(self,parent,selected):
        """Espelho de diretórios: mesmas pastas e arquivos do cofre, não cópias."""
        style=ttk.Style(self.root)
        style.configure('Trama.Treeview',font=(FONT,9),rowheight=27,
                        background=PAL['white'],foreground=PAL['text'],
                        fieldbackground=PAL['white'],borderwidth=0)
        style.map('Trama.Treeview',background=[('selected',PAL['accent_soft'])],
                  foreground=[('selected',PAL['accent_dark'])])
        holder=tk.Frame(parent,bg=PAL['white'])
        holder.pack(fill='both',expand=True)
        tree=ttk.Treeview(holder,show='tree',selectmode='browse',style='Trama.Treeview')
        bar=ttk.Scrollbar(holder,orient='vertical',command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');tree.pack(side='left',fill='both',expand=True)
        folders={}
        ordered=sorted(self.index.notes,key=lambda n:n.relative.casefold())
        selected_id=None
        for note in ordered:
            parts=note.relative.split('/')
            parent_id=''
            for i,segment in enumerate(parts[:-1]):
                dirname='/'.join(parts[:i+1])
                if dirname not in folders:
                    folders[dirname]=tree.insert(parent_id,'end',text='▸  '+segment.replace('-', ' '),open=i<2,values=())
                parent_id=folders[dirname]
            nid=tree.insert(parent_id,'end',text='▤  '+note.stem.replace('-', ' '),values=(note.relative,))
            if selected and selected.relative==note.relative:
                selected_id=nid
        if selected_id:
            tree.selection_set(selected_id)
            tree.see(selected_id)
        def on_selected(_event):
            items=tree.selection()
            if not items:return
            values=tree.item(items[0],'values')
            if values and values[0].lower() in self.index.by_relative and values[0]!=self.selected_rel:
                self._select_note(values[0],'biblioteca')
        tree.bind('<<TreeviewSelect>>',on_selected)

    def _select_note(self,relative,category):
        self.selected_rel=relative
        self.navigate(category)

    def _notes_page(self,category):
        assert self.index is not None
        headings={
            'aulas':('Minhas aulas','Vídeos, transcrições e resumos'),
            'conhecimento':('Meu conhecimento','Conceitos, matérias e seu contexto para IA'),
            'projetos':('Meus projetos','Repositórios e evidências de código'),
            'biblioteca':('Biblioteca do Obsidian','Navegue pelas notas salvas no seu cofre'),
        }
        notes=self.index.filter(category,self.search_var.get() if category=='biblioteca' else '')
        selected=self.index.by_relative.get((self.selected_rel or '').lower())
        if selected not in notes:
            preferred = '00-Inicio/MEU_CONTEXTO.md' if category in ('biblioteca','conhecimento') else None
            selected = self.index.by_relative.get(preferred.lower()) if preferred else None
            if selected not in notes:
                selected=notes[0] if notes else None
        self.selected_rel=selected.relative if selected else None
        # painéis separados por divisórias finas (como no visual aprovado).
        left=self._pane(self.workspace,270)
        left.pack(side='left',fill='y')
        self._subhead(left,*headings[category])
        if category=='biblioteca' and not self.search_var.get().strip():
            self._folder_tree(left,selected)
        else:
            self._list_notes(left,notes,category,selected)
        line(self.workspace,True).pack(side='left',fill='y')
        right=self._pane(self.workspace,262)
        right.pack(side='right',fill='y')
        line(self.workspace,True).pack(side='right',fill='y')
        center=self._pane(self.workspace)
        center.pack(side='left',fill='both',expand=True)
        self._note_center(center,selected,category)
        self._details_panel(right,selected,category)

    def _empty(self,parent,headline,description):
        space=tk.Frame(parent,bg=PAL['white']);space.pack(fill='both',expand=True)
        text(space,headline,16,True).pack(anchor='w',padx=30,pady=(43,9))
        text(space,description,10,color=PAL['secondary'],wrap=490).pack(anchor='w',padx=30)
        row=tk.Frame(space,bg=PAL['white']);row.pack(anchor='w',padx=30,pady=23)
        action(row,'Adicionar materiais',self._pick_files,True).pack(side='left')
        action(row,'Configurar Obsidian',lambda:self.navigate('config')).pack(side='left',padx=9)

    def _note_center(self,parent,note,category):
        if not note:
            self._empty(parent,'Sua biblioteca começa aqui',
                'Selecione um cofre do Obsidian ou importe suas primeiras transcrições. '\
                'As notas criadas aparecerão aqui e também no Obsidian.')
            return
        bar=tk.Frame(parent,bg=PAL['white'],padx=21,pady=14)
        bar.pack(fill='x')
        text(bar,note.relative.replace('/','   ›   '),8,color=PAL['accent']).pack(anchor='w')
        title=text(bar,note.title,15,True,wrap=580)
        title.pack(anchor='w',fill='x',pady=(10,7))
        info=tk.Frame(bar,bg=PAL['white']);info.pack(fill='x')
        self._pill(info,'◈  Nota do Obsidian').pack(side='left',padx=(0,7))
        if note.metadata.get('estado'):
            self._pill(info,note.metadata['estado'].replace('_',' ')).pack(side='left')
        line(parent).pack(fill='x')
        if category=='aulas':
            tabs=tk.Frame(parent,bg=PAL['white'])
            tabs.pack(fill='x')
            for tab in ['Resumo','Vídeos','Transcrição','Relacionados']:
                active=self.lesson_tab==tab
                l=text(tabs,tab,9,active,color=PAL['accent_dark'] if active else PAL['secondary'],
                       bg=PAL['white'],padx=12,pady=9)
                l.pack(side='left',padx=(7,0))
                l.configure(cursor='hand2')
                l.bind('<Button-1>',lambda _e,t=tab: self._set_lesson_tab(t))
            line(parent).pack(fill='x')
            if self.lesson_tab=='Vídeos':
                self._media_tab(parent,note,'video');return
            if self.lesson_tab=='Transcrição':
                self._media_tab(parent,note,'transcript');return
            if self.lesson_tab=='Relacionados':
                self._links_tab(parent,note);return
        self._markdown_reader(parent,note.content,note)

    def _set_lesson_tab(self,tab):
        self.lesson_tab=tab
        self.navigate('aulas')

    def _reader(self,parent):
        area=tk.Frame(parent,bg=PAL['white'])
        area.pack(fill='both',expand=True)
        widget=tk.Text(area,wrap='word',bg=PAL['white'],fg=PAL['text'],
                       font=(FONT,10),relief='flat',bd=0,padx=25,pady=20,
                       highlightthickness=0,spacing1=3,spacing3=5,cursor='arrow')
        scroll=ttk.Scrollbar(area,command=widget.yview)
        widget.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        widget.pack(side='left',fill='both',expand=True)
        widget.tag_configure('h1',font=(FONT,16,'bold'),foreground=PAL['text'],spacing1=18,spacing3=11)
        widget.tag_configure('h2',font=(FONT,12,'bold'),foreground=PAL['accent_dark'],spacing1=16,spacing3=8)
        widget.tag_configure('h3',font=(FONT,10,'bold'),foreground=PAL['text'],spacing1=13,spacing3=6)
        widget.tag_configure('code',font=(MONO,9),background='#f0f3ee',foreground='#385746',lmargin1=14,lmargin2=14)
        widget.tag_configure('quote',foreground=PAL['secondary'],lmargin1=15,lmargin2=15)
        widget.tag_configure('strong',font=(FONT,10,'bold'))
        widget.tag_configure('link',foreground=PAL['accent'],underline=True)
        widget.tag_configure('soft',foreground=PAL['secondary'])
        return widget

    def _markdown_reader(self,parent,raw,note=None):
        reader=self._reader(parent)
        in_fence=False
        links=[]
        for line_text in raw.splitlines():
            trimmed=line_text.strip()
            if trimmed.startswith('```'):
                in_fence=not in_fence
                continue
            if in_fence:
                reader.insert('end',line_text+'\n','code');continue
            heading=re.match(r'^(#{1,3})\s+(.+)',line_text)
            if heading:
                reader.insert('end',heading.group(2)+'\n','h'+str(len(heading.group(1))))
                continue
            if line_text.startswith('>'):
                reader.insert('end',line_text[1:].strip()+'\n','quote');continue
            chunks=re.split(r'(\[\[[^\]\n]+\]\]|\*\*[^*\n]+\*\*)',line_text)
            for piece in chunks:
                if piece.startswith('[[') and piece.endswith(']]'):
                    target=piece[2:-2].split('|',1)[0].split('#',1)[0]
                    visible=piece[2:-2].split('|',1)[-1]
                    if note and self.index:
                        found=self.index.resolve(target,note)
                        if found:
                            tag=f'wikilink_{len(links)}'
                            reader.insert('end',visible,('link',tag))
                            reader.tag_bind(tag,'<Button-1>',lambda _e,ref=found.relative:self._open_note(ref))
                            reader.tag_bind(tag,'<Enter>',lambda _e:reader.configure(cursor='hand2'))
                            reader.tag_bind(tag,'<Leave>',lambda _e:reader.configure(cursor='arrow'))
                            links.append(tag);continue
                    reader.insert('end',visible,'soft')
                elif piece.startswith('**') and piece.endswith('**'):
                    reader.insert('end',piece[2:-2],'strong')
                else:
                    reader.insert('end',piece)
            reader.insert('end','\n')
        reader.configure(state='disabled')

    def _open_note(self,relative):
        self.selected_rel=relative
        self.navigate('biblioteca')

    def _media_for_lesson(self,note,kind):
        vault=Path(self.vault.get()).expanduser().resolve()
        db=vault/'.base-conhecimento'/'estado.sqlite3'
        if not db.is_file():return []
        try:
            with closing(sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True,timeout=2)) as conn:
                conn.row_factory=sqlite3.Row
                lesson=note.metadata.get('aula') or ''
                video=note.metadata.get('gravacao') or ''
                rows=conn.execute('SELECT * FROM sources WHERE kind=? AND lesson=? ORDER BY label',(kind,lesson)).fetchall()
                return [row for row in rows if kind=='transcript' or not video or row['video']==video or not row['video']]
        except (sqlite3.Error,OSError):
            return []

    def _media_tab(self,parent,note,kind):
        rows=self._media_for_lesson(note,kind)
        pane=tk.Frame(parent,bg=PAL['white'],padx=26,pady=21)
        pane.pack(fill='both',expand=True)
        title='Gravações da aula' if kind=='video' else 'Transcrições originais'
        text(pane,title,12,True).pack(anchor='w',pady=(0,9))
        if not rows:
            text(pane,'Nenhum material correspondente foi importado.',9,
                 color=PAL['secondary']).pack(anchor='w')
            return
        for row in rows:
            item=tk.Frame(pane,bg=PAL['toolbar'],padx=12,pady=10)
            item.pack(fill='x',pady=5)
            name=Path(row['stored_path']).name
            text(item,name[:56],9,True,bg=PAL['toolbar']).pack(side='left',fill='x',expand=True)
            action(item,'Abrir arquivo',lambda r=row:self._open_attachment(r['stored_path']),small=True).pack(side='right')
        if kind=='transcript':
            location=Path(self.vault.get()).expanduser().resolve()/rows[0]['stored_path']
            try:
                raw=location.read_text(encoding='utf-8-sig',errors='replace')
                view=self._reader(pane)
                view.insert('end',raw[:450000]);view.configure(state='disabled')
            except OSError:
                text(pane,'Não foi possível ler o arquivo.',9,color=PAL['secondary']).pack(anchor='w')

    def _links_tab(self,parent,note):
        pane=tk.Frame(parent,bg=PAL['white'],padx=27,pady=21)
        pane.pack(fill='both',expand=True)
        text(pane,'Conhecimentos relacionados',12,True).pack(anchor='w',pady=(0,15))
        relations=self.index.related(note) if self.index else []
        if not relations:
            text(pane,'Nenhum link entre notas encontrado ainda.',9,
                 color=PAL['secondary']).pack(anchor='w')
        for other in relations:
            clickable_label(pane,'↗  '+other.title,lambda rel=other.relative:self._open_note(rel)).pack(
                anchor='w',pady=7)

    def _right_block(self,parent,heading):
        block=tk.Frame(parent,bg=PAL['white'],padx=15,pady=13)
        block.pack(fill='x')
        text(block,heading,10,True).pack(anchor='w',pady=(0,12))
        return block

    def _details_panel(self,parent,note,category):
        if not note:
            text(parent,'Biblioteca desconectada',10,True).pack(anchor='w',padx=17,pady=20)
            return
        count=self._media_for_lesson(note,'video') if category=='aulas' else []
        trans=self._media_for_lesson(note,'transcript') if category=='aulas' else []
        info=self._right_block(parent,'Conteúdo da aula' if category=='aulas' else 'Nota selecionada')
        if category=='aulas':
            for caption,value in [('Gravações',len(count)),('Transcrições',len(trans))]:
                row=tk.Frame(info,bg=PAL['white']);row.pack(fill='x',pady=4)
                text(row,caption,9,color=PAL['secondary']).pack(side='left')
                text(row,str(value),9,True,color=PAL['accent']).pack(side='right')
        if category=='aulas':
            for row in count[:4]:
                clickable_label(info,'▶ '+row['label'][:30],
                                lambda r=row:self._open_attachment(r['stored_path']),size=8).pack(anchor='w',pady=(5,0))
            for row in trans[:1]:
                clickable_label(info,'▤  Ver transcrição original',
                                lambda:self._set_lesson_tab('Transcrição'),size=8).pack(anchor='w',pady=(8,2))
        text(info,'Origem: Obsidian Vault',8,color=PAL['secondary']).pack(anchor='w',pady=(7,2))
        line(parent).pack(fill='x',padx=14)
        actions=self._right_block(parent,'Ações')
        action(actions,'Abrir no Obsidian',lambda:self._open_obsidian(note)).pack(fill='x',pady=(0,7))
        action(actions,'Revelar no Explorer',lambda:self._reveal_note(note),small=True).pack(fill='x')
        line(parent).pack(fill='x',padx=14)
        block=self._right_block(parent,'Conhecimentos relacionados')
        rel=self.index.related(note,6) if self.index else []
        if not rel:
            text(block,'As conexões aparecerão conforme as notas forem criadas.',8,
                 color=PAL['secondary'],wrap=220).pack(anchor='w')
        for r in rel:
            short=r.title[:37]+'…' if len(r.title)>38 else r.title
            clickable_label(block,'↗  '+short,lambda ref=r.relative:self._open_note(ref),size=8).pack(
                anchor='w',pady=(0,8))
        if note.metadata.get('tipo'):
            line(parent).pack(fill='x',padx=14)
            s=self._right_block(parent,'Detalhes')
            text(s,'Tipo: '+note.metadata['tipo'],8,color=PAL['secondary'],wrap=200).pack(anchor='w')
            if note.metadata.get('aula'):
                text(s,'Aula: '+note.metadata['aula'],8,color=PAL['secondary']).pack(anchor='w',pady=6)
        tk.Frame(parent,bg=PAL['white']).pack(fill='both',expand=True)

    def _open_attachment(self,stored_path):
        vault=Path(self.vault.get()).expanduser().resolve()
        candidate=(vault/stored_path).resolve()
        if not candidate.is_relative_to(vault) or not candidate.is_file():
            messagebox.showerror('Arquivo indisponível','Não foi possível localizar o arquivo dentro do cofre.')
            return
        if candidate.suffix.lower() not in ('.txt','.md','.mp4','.mkv','.mov','.webm'):
            messagebox.showwarning('Arquivo bloqueado','Este tipo de arquivo não pode ser aberto pelo TRAMA.')
            return
        self._open_local(candidate)

    def _open_local(self,path):
        try:
            if sys.platform=='win32':
                os.startfile(str(path))
            else:
                import subprocess
                subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',str(path)])
        except OSError as exc:
            messagebox.showerror('Não foi possível abrir',str(exc))

    def _reveal_note(self,note):
        if note and note.path.exists():
            self._open_local(note.path.parent)

    def _open_obsidian(self,note=None):
        vault=Path(self.vault.get()).expanduser().resolve()
        if not vault.is_dir():
            messagebox.showinfo('Configurar Obsidian','Escolha a pasta do seu cofre em Ajustes.')
            self.navigate('config');return
        # URI oficial: Obsidian abre o mesmo cofre (não há espelhamento ou cópia).
        params={'vault':vault.name}
        if note:
            params['file']=note.relative.removesuffix('.md')
        uri='obsidian://open?'+urllib.parse.urlencode(params,quote_via=urllib.parse.quote)
        try:
            opened=webbrowser.open(uri)
            if not opened:
                messagebox.showinfo('Abrir Obsidian',
                    'Não foi possível solicitar a abertura. Instale o Obsidian e abra o cofre selecionado.\n'
                    'Se necessário, use o botão Revelar no Explorer.')
        except Exception:
            messagebox.showinfo('Abrir Obsidian',
                'Não foi possível abrir o protocolo do Obsidian neste computador.')

    def _repo_prompt(self):
        popup=tk.Toplevel(self.root);popup.title('Adicionar repositório GitHub')
        popup.geometry('525x185');popup.resizable(False,False);popup.configure(bg=PAL['white'])
        popup.transient(self.root);popup.grab_set()
        text(popup,'Adicionar projeto',13,True).pack(anchor='w',padx=22,pady=(18,8))
        text(popup,'Cole o link público do GitHub ou selecione uma pasta Git local.',9,
             color=PAL['secondary']).pack(anchor='w',padx=22)
        row=tk.Frame(popup,bg=PAL['white']);row.pack(fill='x',padx=22,pady=12)
        entry=tk.Entry(row,textvariable=self.github,font=(FONT,10),bd=1,relief='solid')
        entry.pack(side='left',fill='x',expand=True,ipady=6,padx=(0,9))
        def add():
            popup.destroy();self._repo_url()
        action(row,'Adicionar',add,True).pack(side='right')
        clickable_label(popup,'Escolher pasta Git local',lambda:(popup.destroy(),self._repo_local())).pack(
            anchor='w',padx=22)
        entry.focus_set()

    def _home(self):
        container=tk.Frame(self.workspace,bg=PAL['frame'],padx=26,pady=24)
        container.pack(fill='both',expand=True)
        text(container,'Sua biblioteca pessoal',17,True,bg=PAL['frame']).pack(anchor='w')
        text(container,'Um só lugar para organizar aulas, conhecimento e projetos.',10,
             color=PAL['secondary'],bg=PAL['frame']).pack(anchor='w',pady=(8,20))
        counts=self._counts()
        stats=tk.Frame(container,bg=PAL['white'],padx=18,pady=18,
                       highlightthickness=1,highlightbackground=PAL['line'])
        stats.pack(fill='x')
        for name,value in [('Transcrições',counts['transcript']),('Vídeos',counts['video']),
                           ('Projetos',counts['repo']),('Notas',len(self.index.notes) if self.index else 0)]:
            part=tk.Frame(stats,bg=PAL['white']);part.pack(side='left',fill='x',expand=True)
            text(part,str(value),18,True,color=PAL['accent']).pack(anchor='w')
            text(part,name,9,color=PAL['secondary']).pack(anchor='w',pady=(2,0))
        actions=tk.Frame(container,bg=PAL['frame']);actions.pack(fill='x',pady=21)
        action(actions,'Importar aulas',self._pick_files,True,icon='+').pack(side='left',padx=(0,8))
        action(actions,'Ver biblioteca',lambda:self.navigate('biblioteca')).pack(side='left',padx=(0,8))
        action(actions,'Visualizar conexões',lambda:self.navigate('grafo')).pack(side='left')
        tk.Frame(container,height=1,bg=PAL['line']).pack(fill='x',pady=(0,17))
        text(container,'Acesse suas três áreas',11,True,bg=PAL['frame']).pack(anchor='w',pady=(0,14))
        for caption,desc,key in [
            ('Meu conhecimento','Resumos consolidados e contexto para IA','conhecimento'),
            ('Minhas aulas','Gravações, transcrições e explicações por aula','aulas'),
            ('Meus projetos','Repositórios, código e evidências','projetos')]:
            row=tk.Frame(container,bg=PAL['white'],padx=15,pady=12,
                         highlightthickness=1,highlightbackground=PAL['line'])
            row.pack(fill='x',pady=4)
            text(row,caption,10,True).pack(anchor='w')
            text(row,desc,9,color=PAL['secondary']).pack(anchor='w',pady=(3,0))
            clickable_label(row,'Abrir  ↗',lambda k=key:self.navigate(k)).pack(side='right')

    def _config(self):
        main=tk.Frame(self.workspace,bg=PAL['white'],padx=30,pady=23)
        main.pack(fill='both',expand=True)
        text(main,'Ajustes',17,True).pack(anchor='w')
        text(main,'Tudo permanece no cofre que você escolher.',10,color=PAL['secondary']).pack(
            anchor='w',pady=(7,23))
        for title,var,description in [
            ('Cofre do Obsidian',self.vault,'Esta é a pasta original do seu Obsidian, não uma cópia.'),
            ('Pasta de entrada',self.inbox,'Local dos vídeos e transcrições que deseja importar.')]:
            text(main,title,11,True).pack(anchor='w',pady=(0,5))
            text(main,description,9,color=PAL['secondary']).pack(anchor='w',pady=(0,7))
            row=tk.Frame(main,bg=PAL['white']);row.pack(fill='x',pady=(0,23))
            e=tk.Entry(row,textvariable=var,font=(FONT,10),bg=PAL['white'],bd=1,
                       relief='solid',fg=PAL['text'])
            e.pack(side='left',fill='x',expand=True,ipady=7,padx=(0,9))
            action(row,'Escolher',lambda v=var:self._choose_folder(v,'Selecionar pasta')).pack(side='right')
        line(main).pack(fill='x',pady=(0,22))
        env=read_env(CONFIG_FILE)
        active=sum(bool(env.get(key)) for _,key in ALLOWED.values())
        text(main,'IA para gerar resumos',11,True).pack(anchor='w')
        text(main,f'{active} provedor(es) configurado(s). Use somente contas com faturamento desativado.',
             9,color=PAL['secondary'],wrap=660).pack(anchor='w',pady=(6,11))
        action(main,'Configurar IAs gratuitas',self._settings_dialog).pack(anchor='w')
        line(main).pack(fill='x',pady=(23,20))
        text(main,'Atualizar biblioteca',11,True).pack(anchor='w',pady=(0,10))
        buttons=tk.Frame(main,bg=PAL['white']);buttons.pack(anchor='w')
        action(buttons,'Recriar índices',lambda:self._run('rebuild')).pack(side='left',padx=(0,9))
        action(buttons,'Abrir pasta do cofre',lambda:self._open_folder('')).pack(side='left')
        action(main,'Salvar caminhos',self._save_settings).pack(anchor='w',pady=(15,0))
        text(main,'Os links e o grafo são calculados lendo seus arquivos Markdown. O TRAMA não altera suas notas pessoais.',
             9,color=PAL['secondary'],wrap=670).pack(anchor='w',pady=(20,0))

    # ── Grafo offline ─────────────────────────────────────────────────────
    def _graph_page(self):
        graph_nodes,graph_edges=self.index.graph(cap=500) if self.index else ([],[])
        self.graph_nodes,self.graph_edges=graph_nodes,graph_edges
        self.graph_zoom=1.18
        self.graph_offset=(0,0)
        header=self._subhead(self.workspace,'Grafo de conhecimento',
                             f'{len(graph_nodes)} notas e {len(graph_edges)} conexões reais entre arquivos Markdown')
        action(header,'–',lambda:self._zoom(0.8),small=True).pack(side='right',pady=18,padx=(0,16))
        action(header,'+',lambda:self._zoom(1.25),small=True).pack(side='right',pady=18,padx=(0,6))
        info=self._pane(self.workspace,256)
        info.pack(side='right',fill='y')
        line(self.workspace,True).pack(side='right',fill='y')
        field=tk.Frame(self.workspace,bg='#f8faf7')
        field.pack(side='left',fill='both',expand=True)
        self.graph_canvas=tk.Canvas(field,bg='#f8faf7',highlightthickness=0,bd=0,
                                    cursor='hand2' if graph_nodes else 'arrow')
        self.graph_canvas.pack(fill='both',expand=True)
        self.graph_canvas.bind('<Configure>',lambda _e:self._draw_graph())
        self.graph_canvas.bind('<Button-1>',self._graph_click)
        self.graph_canvas.bind('<Double-Button-1>',self._graph_double)
        self.graph_canvas.bind('<MouseWheel>',lambda e:self._zoom(1.15 if e.delta>0 else 1/1.15))
        self.graph_info=info
        self.graph_positions=self._layout_graph(graph_nodes,graph_edges)
        self.selected_graph=0 if graph_nodes else None
        self._show_graph_info()
        self._draw_graph()

    @staticmethod
    def _layout_graph(nodes,edges):
        if not nodes:return []
        # Layout determinístico com clusters por seção, sem bibliotecas externas.
        n=len(nodes)
        centers={'01-Meu-Conhecimento':(-0.45,-0.22),'02-Minhas-Aulas':(0.45,-0.15),
                 '03-Meus-Projetos':(0.0,0.49),'00-Inicio':(0.0,-0.55)}
        positions=[]
        counts=defaultdict(int)
        for i,node in enumerate(nodes):
            j=counts[node.section];counts[node.section]+=1
            center=centers.get(node.section,(-0.12,0.25))
            angle=j*2.39996
            radius=0.11+0.055*math.sqrt(j)
            positions.append([center[0]+math.cos(angle)*radius,center[1]+math.sin(angle)*radius])
        adjacency=[[] for _ in nodes]
        for a,b in edges:
            adjacency[a].append(b);adjacency[b].append(a)
        for _ in range(55 if n<=170 else 0):
            motion=[[0.0,0.0] for _ in nodes]
            for i in range(n):
                x,y=positions[i]
                # Repulsão entre nós próximos.
                for j in range(i+1,n):
                    dx=x-positions[j][0];dy=y-positions[j][1]
                    dist=max(0.003,dx*dx+dy*dy)
                    force=min(0.015,0.00065/dist)
                    motion[i][0]+=dx*force;motion[i][1]+=dy*force
                    motion[j][0]-=dx*force;motion[j][1]-=dy*force
            for a,b in edges:
                dx=positions[b][0]-positions[a][0]
                dy=positions[b][1]-positions[a][1]
                d=math.sqrt(dx*dx+dy*dy)+1e-6
                attractive=(d-0.12)*0.017
                motion[a][0]+=dx/d*attractive;motion[a][1]+=dy/d*attractive
                motion[b][0]-=dx/d*attractive;motion[b][1]-=dy/d*attractive
            for i in range(n):
                positions[i][0]=max(-1.1,min(1.1,positions[i][0]+motion[i][0]*0.5))
                positions[i][1]=max(-1.1,min(1.1,positions[i][1]+motion[i][1]*0.5))
        return positions

    def _graph_coords(self):
        can=self.graph_canvas
        width=max(400,can.winfo_width());height=max(300,can.winfo_height())
        ratio=min(width,height)*0.54*self.graph_zoom
        dx,dy=self.graph_offset
        return [(width/2+x*ratio+dx,height/2+y*ratio+dy) for x,y in self.graph_positions]

    def _draw_graph(self):
        if not hasattr(self,'graph_canvas') or not self.graph_canvas.winfo_exists():return
        can=self.graph_canvas
        can.delete('all')
        if not self.graph_nodes:
            can.create_text(max(300,can.winfo_width())/2,max(240,can.winfo_height())/2,
                            text='O grafo aparecerá quando existirem notas no seu Obsidian.',
                            fill=PAL['secondary'],font=(FONT,11))
            return
        coords=self._graph_coords()
        for a,b in self.graph_edges:
            ax,ay=coords[a];bx,by=coords[b]
            can.create_line(ax,ay,bx,by,fill='#bad0bf',width=1.3)
        degrees=defaultdict(int)
        for a,b in self.graph_edges:
            degrees[a]+=1;degrees[b]+=1
        palette={'01-Meu-Conhecimento':'#47845d','02-Minhas-Aulas':'#708da4',
                 '03-Meus-Projetos':'#b69364','00-Inicio':'#9179a2'}
        labeled=sorted(range(len(coords)),key=lambda i:degrees[i],reverse=True)[:min(23,len(coords))]
        for i,(x,y) in enumerate(coords):
            active=i==self.selected_graph
            radius=9 if active else 5.5 if degrees[i] else 4.5
            color=palette.get(self.graph_nodes[i].section,'#96a69c')
            if active:
                can.create_oval(x-13,y-13,x+13,y+13,fill='#e0eee2',outline=color,width=1)
            can.create_oval(x-radius,y-radius,x+radius,y+radius,
                            fill=color,outline='#ffffff',width=1.2)
            if i in labeled or active:
                title=self.graph_nodes[i].title
                if len(title)>28:title=title[:25]+'…'
                can.create_text(x+9,y-10,text=title,fill=PAL['text'] if active else PAL['secondary'],
                                anchor='w',font=(FONT,9,'bold' if active else 'normal'))

    def _graph_click(self,event):
        if not self.graph_nodes:return
        coords=self._graph_coords()
        distances=[(x-event.x)**2+(y-event.y)**2 for x,y in coords]
        best=min(range(len(distances)),key=distances.__getitem__)
        if distances[best]<=(20*self.graph_zoom)**2:
            self.selected_graph=best
            self._draw_graph();self._show_graph_info()

    def _graph_double(self,event):
        self._graph_click(event)
        if self.selected_graph is not None:
            self._open_note(self.graph_nodes[self.selected_graph].relative)

    def _zoom(self,factor):
        self.graph_zoom=max(.4,min(3.5,self.graph_zoom*factor))
        self._draw_graph()

    def _show_graph_info(self):
        info=self.graph_info
        for child in info.winfo_children():child.destroy()
        block=self._right_block(info,'Conexões reais do Obsidian')
        text(block,'Cada ponto é uma nota; as linhas são links [[...]] entre elas.',
             9,color=PAL['secondary'],wrap=220).pack(anchor='w')
        if self.selected_graph is None:return
        node=self.graph_nodes[self.selected_graph]
        line(info).pack(fill='x',padx=14,pady=12)
        current=self._right_block(info,'Nota selecionada')
        text(current,node.title,10,True,wrap=220).pack(anchor='w',pady=(0,10))
        text(current,node.relative,8,color=PAL['secondary'],wrap=210).pack(anchor='w',pady=(0,15))
        action(current,'Ler nota',lambda:self._open_note(node.relative)).pack(fill='x',pady=(0,8))
        action(current,'Abrir no Obsidian',lambda:self._open_obsidian(node),small=True).pack(fill='x')
        line(info).pack(fill='x',padx=14,pady=12)
        relations=self._right_block(info,'Notas relacionadas')
        related=self.index.related(node,8) if self.index else []
        if not related:
            text(relations,'Esta nota ainda não possui links.',9,
                 color=PAL['secondary']).pack(anchor='w')
        for ref in related:
            clickable_label(relations,'↗ '+ref.title[:30],lambda r=ref.relative:self._open_note(r),size=8).pack(
                anchor='w',pady=(0,10))


def start_gui():
    root=tk.Tk()
    TramaDesktop(root)
    root.mainloop()
