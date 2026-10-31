"""TRAMA desktop 0.7 — interface fiel ao conceito aprovado.

Visual clássico de quatro regiões. Continua lendo as notas do MESMO cofre do
Obsidian: esta interface não cria uma base paralela e não executa Markdown/código.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk

from .gui import TramaDesktop, PAL, FONT, text, action, line, clickable_label

PAL.update({
    'frame':'#f7f8f5', 'title':'#f9faf8','sidebar':'#fbfcfa',
    'toolbar':'#f1f3ef','line':'#d6ded6','text':'#202924',
    'secondary':'#626f68','faint':'#84928a','accent':'#3d7958',
    'accent_dark':'#255b40','accent_soft':'#dcece0',
    'badge':'#edf5ee','card':'#f4f7f3', 'blue':'#367fbd',
})


def small_label(parent, content, size=9, bold=False, color=None, bg=None, wrap=None, **kwargs):
    return text(parent,content,size,bold,color,bg,wrap,**kwargs)


def framed(parent, bgcolor='#ffffff', border='#dbe2db', padx=0, pady=0):
    outer = tk.Frame(parent,bg=border,padx=1,pady=1)
    inner = tk.Frame(outer,bg=bgcolor,padx=padx,pady=pady)
    inner.pack(fill='both',expand=True)
    return outer, inner


class ReferenceDesktop(TramaDesktop):
    """Keeps the tested import/index/graph engine, replacing visual composition."""

    def _shell(self):
        self.root.title('TRAMA — Seu conhecimento, organizado.')
        self.root.geometry('1390x930')
        self.root.minsize(1070,670)
        self.root.configure(bg=PAL['frame'])
        try:
            asset=Path(__file__).resolve().parent.parent/'assets'/'trama-logo-64.png'
            img=tk.PhotoImage(file=str(asset))
            self._app_icon=img
            self.root.iconphoto(True,img)
        except (tk.TclError,OSError): pass

        # Classic application header, with identity instead of a web-dashboard hero.
        header=tk.Frame(self.root,bg='#f9faf8',height=72)
        header.pack(fill='x'); header.pack_propagate(False)
        identity=tk.Frame(header,bg='#f9faf8')
        identity.pack(side='left',padx=19,pady=10)
        if hasattr(self,'_app_icon'):
            logo=tk.Label(identity,image=self._app_icon,bg='#f9faf8')
            logo.pack(side='left',padx=(0,10))
        else:self._logo(identity,44).pack(side='left',padx=(0,10))
        names=tk.Frame(identity,bg='#f9faf8');names.pack(side='left')
        small_label(names,'TRAMA',16,True).pack(anchor='w')
        small_label(names,'Seu conhecimento, organizado.',8,color=PAL['secondary']).pack(anchor='w')
        self.connection=small_label(header,'○  Obsidian não configurado',9,color=PAL['secondary'])
        self.connection.pack(side='right',padx=24)
        line(self.root).pack(fill='x')

        toolbar=tk.Frame(self.root,bg='#f0f3f0',height=57)
        toolbar.pack(fill='x'); toolbar.pack_propagate(False)
        for title,fn,ic in [
            ('Importar Aulas',self._pick_files,'✚'),
            ('Gerar Resumos',self._process,'▤'),
            ('Abrir Obsidian',self._open_obsidian,'◈'),
        ]:
            self._classic_button(toolbar,title,fn,ic).pack(side='left',padx=(15 if title=='Importar Aulas' else 0,7),pady=9)
        self._classic_button(toolbar,'⚙',lambda:self.navigate('config')).pack(side='right',padx=(5,15),pady=9)
        self.search_var=tk.StringVar()
        se=tk.Entry(toolbar,textvariable=self.search_var,relief='solid',bd=1,
                    highlightthickness=0,bg='#ffffff',fg=PAL['text'],font=(FONT,10))
        se.pack(side='left',fill='x',expand=True,ipady=7,padx=(17,10),pady=10)
        se.insert(0,'')
        se.bind('<Return>',lambda _e:self._search())
        se.bind('<Escape>',lambda _e:(self.search_var.set(''),self._search()))
        self._classic_button(toolbar,'Buscar',self._search).pack(side='left',padx=(0,11),pady=9)
        line(self.root).pack(fill='x')

        frame=tk.Frame(self.root,bg=PAL['frame']);frame.pack(fill='both',expand=True)
        sidebar=tk.Frame(frame,bg=PAL['sidebar'],width=157)
        sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        self.nav={}
        tabs=[('inicio','Início','⌂'),('aulas','Aulas','▣'),
              ('conhecimento','Conhecimento','♧'),('projetos','Projetos','▱'),
              ('biblioteca','Biblioteca','▤'),('grafo','Grafo','◎'),('config','Ajustes','⚙')]
        for idx,(key,title,icon) in enumerate(tabs):
            if key=='config':
                line(sidebar).pack(fill='x',padx=14,pady=(16,12))
            item=tk.Frame(sidebar,bg=PAL['sidebar'],height=49)
            item.pack(fill='x',padx=8,pady=3); item.pack_propagate(False)
            glyph=small_label(item,icon,16,color=PAL['secondary'])
            glyph.pack(side='left',padx=(12,10))
            label=small_label(item,title,9,color=PAL['secondary'])
            label.pack(side='left',fill='both',expand=True)
            self.nav[key]=(item,glyph,label)
            for w in (item,glyph,label):
                w.config(cursor='hand2')
                w.bind('<Button-1>',lambda _e,k=key:self.navigate(k))
        tk.Frame(sidebar,bg=PAL['sidebar']).pack(fill='both',expand=True)
        small_label(sidebar,'ARQUIVOS NO SEU COMPUTADOR',7,True,color=PAL['accent']).pack(anchor='w',padx=13,pady=(0,5))
        small_label(sidebar,'Biblioteca compartilhada com o Obsidian.',8,color=PAL['secondary'],wrap=132).pack(
            anchor='w',padx=13,pady=(0,22))
        line(frame,True).pack(side='left',fill='y')
        self.workspace=tk.Frame(frame,bg=PAL['frame']);self.workspace.pack(side='left',fill='both',expand=True)

        line(self.root).pack(fill='x')
        foot=tk.Frame(self.root,bg='#f1f3f0',height=31)
        foot.pack(fill='x');foot.pack_propagate(False)
        self.footer_label=small_label(foot,'Pronto',8,color=PAL['secondary'])
        self.footer_label.pack(side='left',padx=15,pady=7)
        self.footer_count=small_label(foot,'',8,color=PAL['secondary'])
        self.footer_count.pack(side='right',padx=16,pady=7)
        self.root.bind('<Control-r>',lambda _e:self.navigate(self.current))

    def _classic_button(self,parent,label,command,icon=''):
        return tk.Button(parent,text=(icon+'  ' if icon else '')+label,command=command,
                         bg='#fbfcfa',fg='#253b30',activebackground='#dfebe1',
                         activeforeground='#1e5536',bd=1,relief='raised',
                         cursor='hand2',font=(FONT,9,'bold'),padx=12,pady=6)

    def _index(self):
        super()._index()
        self.footer_count.configure(text=self.footer_count.cget('text').replace('v0.6','v0.7'))
        if self.index and self.index.vault.is_dir():
            self.connection.configure(text='●  Obsidian conectado',fg=PAL['accent_dark'])

    def _notes_page(self,category):
        notes=self.index.filter(category,self.search_var.get() if category=='biblioteca' else '')
        selected=self.index.by_relative.get((self.selected_rel or '').lower())
        if selected not in notes:
            selected=self.index.by_relative.get('00-inicio/meu_contexto.md') if category in ('biblioteca','conhecimento') else None
            if selected not in notes:selected=notes[0] if notes else None
        self.selected_rel=selected.relative if selected else None
        left=tk.Frame(self.workspace,bg='#ffffff',width=279)
        left.pack(side='left',fill='y');left.pack_propagate(False)
        self._reference_left(left,category,notes,selected)
        line(self.workspace,True).pack(side='left',fill='y')
        right=tk.Frame(self.workspace,bg='#f8faf7',width=302)
        right.pack(side='right',fill='y');right.pack_propagate(False)
        self._reference_right(right,category,selected)
        line(self.workspace,True).pack(side='right',fill='y')
        center=tk.Frame(self.workspace,bg='#ffffff')
        center.pack(side='left',fill='both',expand=True)
        self._reference_center(center,category,selected)

    def _reference_left(self,parent,category,notes,selected):
        title={'aulas':'Minhas Aulas','biblioteca':'Biblioteca do Obsidian',
               'projetos':'Meus Projetos','conhecimento':'Meu Conhecimento'}[category]
        cap=tk.Frame(parent,bg='#ffffff',padx=14,pady=14)
        cap.pack(fill='x')
        small_label(cap,title,13,True).pack(side='left',fill='x',expand=True)
        plus=self._classic_button(cap,'+',self._repo_prompt if category=='projetos' else self._pick_files)
        plus.pack(side='right')
        if category=='biblioteca' and not self.search_var.get().strip():
            small_label(parent,'Explore as mesmas pastas e notas do Obsidian.',8,
                        color=PAL['secondary']).pack(anchor='w',padx=14,pady=(0,12))
            self._folder_tree(parent,selected)
            return
        filterbar=tk.Frame(parent,bg='#ffffff',padx=12)
        filterbar.pack(fill='x')
        for label in ('Todas','Recentes','Favoritas'):
            isactive=label=='Todas'
            button=tk.Label(filterbar,text=label,bg='#528967' if isactive else '#f5f6f3',
                            fg='white' if isactive else PAL['secondary'],
                            font=(FONT,8,'bold' if isactive else 'normal'),
                            padx=11,pady=8,relief='solid',bd=1)
            button.pack(side='left',fill='x',expand=True)
            # Future filter options disabled until matching persistence is implemented.
            if not isactive:button.configure(fg='#9aa49e')
        searchrow=tk.Frame(parent,bg='#ffffff',padx=12,pady=10)
        searchrow.pack(fill='x')
        search=tk.Entry(searchrow,font=(FONT,9),bg='#fff',relief='solid',bd=1)
        search.pack(fill='x',ipady=7)
        search.insert(0,'Buscar aulas...' if category=='aulas' else 'Buscar notas...')
        def search_on(event):
            value=search.get().strip()
            if value in ('Buscar aulas...','Buscar notas...'):value=''
            self.search_var.set(value)
            self.navigate(category if category=='biblioteca' else 'biblioteca')
        search.bind('<Return>',search_on)
        search.bind('<FocusIn>',lambda _e:search.delete(0,'end') if search.get().startswith('Buscar ') else None)
        if not notes:
            small_label(parent,'Nenhum material ainda. Importe suas primeiras aulas.',9,
                        color=PAL['secondary'],wrap=235).pack(anchor='w',padx=16,pady=18)
            return
        hold=tk.Frame(parent,bg='#ffffff');hold.pack(fill='both',expand=True)
        canvas=tk.Canvas(hold,bg='#ffffff',highlightthickness=0,bd=0)
        scr=ttk.Scrollbar(hold,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scr.set)
        scr.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        content=tk.Frame(canvas,bg='#ffffff')
        cid=canvas.create_window((0,0),window=content,anchor='nw')
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(cid,width=e.width))
        content.bind('<Configure>',lambda _e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120),'units'))
        for i,note in enumerate(notes[:750]):
            # Grouping is derived from local file modification, not imaginary course dates.
            if i==0:small_label(content,'NOTAS DISPONÍVEIS',8,True,color=PAL['secondary']).pack(anchor='w',padx=15,pady=(7,7))
            active=selected is not None and note.relative==selected.relative
            bg='#e0f0e4' if active else '#ffffff'
            entry=tk.Frame(content,bg=bg,padx=10,pady=12)
            entry.pack(fill='x',padx=9,pady=2)
            title=note.metadata.get('aula') if category=='aulas' else note.title
            if category=='aulas':
                headline=title or note.title
                subtitle=note.title.replace((title or '')+' — ','') if title else note.title
                subtitle=subtitle.replace('-',' ')[:66]
            else:headline=note.title[:34];subtitle=note.relative.split('/',1)[-1][:57]
            head=small_label(entry,headline,9,True,bg=bg,color=PAL['text'])
            head.pack(anchor='w')
            desc=small_label(entry,subtitle,9,bg=bg,color=PAL['secondary'],wrap=220)
            desc.pack(anchor='w',pady=(4,3))
            stamp=datetime.fromtimestamp(note.path.stat().st_mtime).strftime('%d/%m/%Y')
            date=small_label(entry,'Arquivo: '+stamp,8,bg=bg,color=PAL['secondary'])
            date.pack(anchor='w')
            for el in (entry,head,desc,date):
                el.config(cursor='hand2')
                el.bind('<Button-1>',lambda _e,ref=note.relative:self._select_note(ref,category))
            if not active:line(content).pack(fill='x',padx=17)

    @staticmethod
    def _section_body(raw, heading):
        match=re.search(r'(?mi)^##\s+'+re.escape(heading)+r'\s*\n(.*?)(?=^##\s+|\Z)',raw,re.S|re.M)
        return match.group(1).strip() if match else ''

    def _reference_center(self,parent,category,note):
        if not note:
            self._empty(parent,'A biblioteca está pronta para receber suas aulas',
                        'Importe vídeos e transcrições para começar. O Obsidian continuará sendo o armazenamento principal.')
            return
        intro=tk.Frame(parent,bg='#ffffff',padx=20,pady=14)
        intro.pack(fill='x')
        parent_label={'aulas':'AP 2026 [Fullstack]', 'conhecimento':'Meu Conhecimento',
                      'projetos':'Meus Projetos','biblioteca':'Obsidian'}[category]
        small_label(intro,f'⌂  {parent_label}   ›   {note.metadata.get("aula",note.stem)[:32]}',
                    9,color=PAL['secondary']).pack(anchor='w')
        headline=note.title
        if category=='aulas' and note.metadata.get('aula'):
            # Do not render a duplicate lesson number in generated titles.
            headline=note.title.replace(note.metadata['aula']+' — ','',1)
            headline=f'{note.metadata["aula"]} — {headline}'
        small_label(intro,headline,16,True,wrap=560).pack(anchor='w',fill='x',pady=(16,12))
        subtitle=tk.Frame(intro,bg='#ffffff');subtitle.pack(fill='x')
        updated=datetime.fromtimestamp(note.path.stat().st_mtime).strftime('%d/%m/%Y')
        small_label(subtitle,'▦  Arquivo atualizado em '+updated,9,color=PAL['secondary']).pack(side='left')
        badges=tk.Frame(intro,bg='#ffffff');badges.pack(fill='x',pady=(16,0))
        state=note.metadata.get('estado','').replace('_',' ')
        small_label(badges,'✓  '+(state if state else 'Nota do Obsidian'),8,True,
                    color=PAL['accent_dark'],bg='#e3f2e7',padx=9,pady=6).pack(side='left',padx=(0,5))
        small_label(badges,'◈  '+note.metadata.get('tipo','Markdown'),8,
                    color='#48667e',bg='#eef3f6',padx=8,pady=6).pack(side='left',padx=3)
        line(parent).pack(fill='x')
        tabs=tk.Frame(parent,bg='#f9faf8',height=44)
        tabs.pack(fill='x');tabs.pack_propagate(False)
        video_count=len(self._media_for_lesson(note,'video')) if category=='aulas' else 0
        opts=['Resumo','Conteúdo',f'Vídeos ({video_count})','Transcrição','Relacionados'] if category=='aulas' else ['Resumo','Conteúdo','Relacionados']
        for opt in opts:
            mode='Vídeos' if opt.startswith('Vídeos') else opt
            active=(self.lesson_tab if category=='aulas' else getattr(self,'note_tab','Resumo'))==mode
            lab=small_label(tabs,opt,9,active,color=PAL['accent_dark'] if active else PAL['secondary'],
                            bg='#ffffff' if active else '#f9faf8',padx=11,pady=13)
            lab.pack(side='left',fill='y')
            if active:
                lab.configure(relief='ridge',bd=1)
            lab.configure(cursor='hand2')
            lab.bind('<Button-1>',lambda _e,m=mode,c=category:self._change_tab(m,c))
        line(parent).pack(fill='x')
        tab=self.lesson_tab if category=='aulas' else getattr(self,'note_tab','Resumo')
        if tab=='Vídeos':self._media_tab(parent,note,'video');return
        if tab=='Transcrição':self._media_tab(parent,note,'transcript');return
        if tab=='Relacionados':self._links_tab(parent,note);return
        if tab=='Conteúdo':self._markdown_reader(parent,note.content,note);return
        self._structured_summary(parent,note,category)

    def _change_tab(self,tab,category):
        if category=='aulas':self.lesson_tab=tab
        else:self.note_tab=tab
        self.navigate(category)

    def _structured_summary(self,parent,note,category):
        holder=tk.Frame(parent,bg='#ffffff');holder.pack(fill='both',expand=True)
        can=tk.Canvas(holder,bg='#ffffff',highlightthickness=0,bd=0)
        scroll=ttk.Scrollbar(holder,orient='vertical',command=can.yview)
        can.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');can.pack(side='left',fill='both',expand=True)
        inside=tk.Frame(can,bg='#ffffff',padx=16,pady=15)
        win=can.create_window((0,0),window=inside,anchor='nw')
        can.bind('<Configure>',lambda e:can.itemconfigure(win,width=e.width))
        inside.bind('<Configure>',lambda _e:can.configure(scrollregion=can.bbox('all')))
        can.bind('<MouseWheel>',lambda e:can.yview_scroll(-int(e.delta/120),'units'))
        raw=note.content
        summary=(self._section_body(raw,'Resumo da aula') or self._section_body(raw,'Resumo') or '')
        if not summary:
            paragraphs=[x.strip() for x in raw.split('\n\n') if x.strip() and not x.lstrip().startswith(('#','---'))]
            summary=paragraphs[0] if paragraphs else 'Não há resumo gerado para este material.'
        # Keep source state explicit; never pass extractive/transcription fragments as completed AI summary.
        self._summary_card(inside,'▤','Resumo da aula' if category=='aulas' else 'Resumo',summary,'#edf5ed')
        concepts=(self._section_body(raw,'Conceitos ensinados (extraídos pela IA)') or
                  self._section_body(raw,'Conceitos principais') or
                  self._section_body(raw,'Principais conceitos'))
        if concepts:
            self._summary_card(inside,'✧','Principais conceitos',concepts,'#f5f7f5')
        elif category=='aulas':
            self._summary_card(inside,'✧','Principais conceitos','Aguardando a análise da transcrição por uma IA gratuita.', '#f5f7f5')
        examples=self._section_body(raw,'Exemplos mencionados')
        if examples and examples.strip('- '):
            self._summary_card(inside,'⌘','Exemplos da aula',examples,'#fafaf7')
        refs=self._section_body(raw,'Fontes originais')
        videos=self._media_for_lesson(note,'video') if category=='aulas' else []
        transcript=self._media_for_lesson(note,'transcript') if category=='aulas' else []
        card=tk.Frame(inside,bg='#f7f9f7',padx=13,pady=13,highlightbackground=PAL['line'],highlightthickness=1)
        card.pack(fill='x',pady=(3,14))
        small_label(card,'⌁  Materiais e links',11,True,bg='#f7f9f7').pack(anchor='w',pady=(0,11))
        if transcript:
            self._resource(card,'▤','Transcrição original',transcript[0]['label'],
                           'Abrir',lambda:self._set_lesson_tab('Transcrição'))
        for item in videos[:5]:
            self._resource(card,'▶',item['label'][:52],'Vídeo local','Assistir',
                           lambda item=item:self._open_attachment(item['stored_path']))
        if refs:
            for s in refs.splitlines()[:5]:
                if s.strip() and not s.strip().startswith('!'):
                    small_label(card,s.strip()[:150],8,color=PAL['secondary'],bg='#f7f9f7',wrap=510).pack(anchor='w',pady=2)
        if not transcript and not videos and not refs:
            small_label(card,'Nenhum arquivo associado por enquanto.',9,color=PAL['secondary'],bg='#f7f9f7').pack(anchor='w')

    def _summary_card(self,parent,icon,heading,body,bg):
        card=tk.Frame(parent,bg=bg,padx=14,pady=14,highlightthickness=1,
                      highlightbackground='#e6ece5')
        card.pack(fill='x',pady=(0,13))
        small_label(card,f'{icon}  {heading}',11,True,bg=bg).pack(anchor='w',pady=(0,9))
        # A quick, readable markdown-like presentation with native label wrapping.
        for piece in body.splitlines()[:60]:
            piece=piece.strip()
            if not piece:continue
            piece=re.sub(r'\[\[([^]|]+)\|([^]]+)\]\]',r'\2',piece)
            piece=re.sub(r'\*\*(.*?)\*\*',r'\1',piece)
            piece=re.sub(r'`([^`]+)`',r'\1',piece)
            small_label(card,piece,9,color=PAL['text'],bg=bg,wrap=565).pack(anchor='w',fill='x',pady=2)

    def _resource(self,parent,icon,title,detail,cta,fn):
        row=tk.Frame(parent,bg='#ffffff',padx=10,pady=8,highlightthickness=1,
                     highlightbackground='#e6eae5')
        row.pack(fill='x',pady=3)
        small_label(row,icon,14,color=PAL['accent'],bg='#ffffff').pack(side='left',padx=(0,10))
        inner=tk.Frame(row,bg='#ffffff');inner.pack(side='left',fill='x',expand=True)
        small_label(inner,title,9,True,bg='#ffffff',wrap=330).pack(anchor='w')
        small_label(inner,detail[:72],8,color=PAL['secondary'],bg='#ffffff').pack(anchor='w',pady=(2,0))
        self._classic_button(row,cta,fn).pack(side='right')

    def _reference_right(self,parent,category,note):
        # Only real attachments, links and repository data are shown. Missing content is omitted.
        holder=tk.Frame(parent,bg='#f9faf8',padx=8,pady=8)
        holder.pack(fill='both',expand=True)
        if not note:
            small_label(holder,'Conecte um cofre e selecione uma nota.',9,color=PAL['secondary'],wrap=260).pack(anchor='w',padx=10,pady=12)
            return
        if category=='aulas':
            block,area=framed(holder,padx=13,pady=13)
            block.pack(fill='x',pady=(0,9))
            small_label(area,'▤  Conteúdo da Aula',10,True).pack(anchor='w',pady=(0,8))
            vids=self._media_for_lesson(note,'video');trs=self._media_for_lesson(note,'transcript')
            for item in vids[:5]:
                self._side_row(area,'▶',item['label'][:32],lambda r=item:self._open_attachment(r['stored_path']))
            for item in trs[:1]:
                self._side_row(area,'▤','Transcrição completa',lambda:self._set_lesson_tab('Transcrição'))
            if not vids and not trs:
                small_label(area,'Nenhum anexo importado.',9,color=PAL['secondary']).pack(anchor='w',pady=5)
        else:
            block,area=framed(holder,padx=13,pady=13)
            block.pack(fill='x',pady=(0,9))
            small_label(area,'◈  Ligação com Obsidian',10,True).pack(anchor='w',pady=(0,9))
            for lbl,val in [('Vault','Conectado'),('Notas',str(len(self.index.notes))),
                            ('Origem','Cofre local')]:
                row=tk.Frame(area,bg='#ffffff');row.pack(fill='x',pady=5)
                small_label(row,lbl,9,color=PAL['secondary']).pack(side='left')
                small_label(row,val,9,True,color=PAL['accent']).pack(side='right')
        rel=self.index.related(note,12) if self.index else []
        concepts=[n for n in rel if n.section=='01-Meu-Conhecimento']
        projects=[n for n in rel if n.section=='03-Meus-Projetos']
        others=[n for n in rel if n.section=='02-Minhas-Aulas']
        for title,data,ic in [('Meu Conhecimento',concepts,'♧'),('Projetos relacionados',projects,'▱'),('Aulas relacionadas',others,'▤')]:
            block,area=framed(holder,padx=12,pady=11)
            block.pack(fill='x',pady=(0,9))
            small_label(area,ic+'  '+title,10,True).pack(anchor='w',pady=(0,8))
            if data:
                for node in data[:5]:
                    self._side_row(area,'↗',node.title[:36],lambda ref=node.relative:self._open_note(ref))
            else:
                small_label(area,'Sem vínculos confirmados ainda.',8,color=PAL['secondary']).pack(anchor='w',pady=4)
        block,area=framed(holder,padx=12,pady=11)
        block.pack(fill='x',pady=(0,9))
        small_label(area,'Ações',10,True).pack(anchor='w',pady=(0,9))
        self._classic_button(area,'Abrir nota no Obsidian',lambda:self._open_obsidian(note),'↗').pack(fill='x',pady=3)
        self._classic_button(area,'Revelar no Explorer',lambda:self._reveal_note(note),'▱').pack(fill='x',pady=3)

    def _side_row(self,parent,icon,label,callback):
        row=tk.Frame(parent,bg='#ffffff')
        row.pack(fill='x',pady=5)
        small_label(row,icon,10,color='#3c81bc').pack(side='left',padx=(0,7))
        item=small_label(row,label,9,wrap=215)
        item.pack(side='left',fill='x',expand=True)
        for w in (row,item):
            w.configure(cursor='hand2')
            w.bind('<Button-1>',lambda _e:callback())


def start_gui():
    root=tk.Tk()
    ReferenceDesktop(root)
    root.mainloop()
