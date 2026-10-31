"""TRAMA — interface desktop local para uma biblioteca de aprendizado incremental.

Sem fontes remotas ao iniciar. Os únicos acessos externos possíveis são ações
explícitas para importar um GitHub público e para processar notas usando IA.
"""
from __future__ import annotations
from contextlib import closing

import json
import os
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from .ai import ALLOWED, read_env
from .pipeline import Application

APP_ROOT = Path(__file__).resolve().parent.parent
ASSETS = APP_ROOT / "assets"
DATA_HOME = (Path(os.environ["LOCALAPPDATA"]) / "TRAMA" if os.environ.get("LOCALAPPDATA") else Path.home() / ".trama")
OLD_DATA_HOME = (Path(os.environ["LOCALAPPDATA"]) / "NEXO" if os.environ.get("LOCALAPPDATA") else Path.home() / ".nexo")
SETTINGS_FILE = DATA_HOME / "settings.json"
CONFIG_FILE = DATA_HOME / "config.env"

# Paleta editorial: papel, tinta escura e verde mineral. Sem aparência de template SaaS.
C = {
    "bg":"#F5F6F2", "side":"#FFFFFF", "panel":"#FFFFFF", "panel2":"#F7F8F5",
    "border":"#E1E7E0", "subtle":"#E9EEEA", "text":"#17271F",
    "muted":"#64766C", "dim":"#84948A", "accent":"#1B6B50",
    "accentdark":"#10503B", "soft":"#ECF5EF", "hero":"#173B30",
    "lime":"#D3E8A3", "cyan":"#4A9A86", "green":"#1B8562",
    "orange":"#C17B46", "red":"#BC574D", "warm":"#F5EDE1",
}
FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
DISPLAY = "Georgia" if sys.platform == "win32" else "DejaVu Serif"
MONO = "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono"


def label(parent,text,size=10,color=None,weight="normal",family=None,**kw):
    return tk.Label(parent,text=text,bg=parent.cget("bg"),fg=color or C["text"],
       font=(family or FONT,size,weight),anchor="w",justify="left",**kw)


def spacer(parent,h=12):
    tk.Frame(parent,height=h,bg=parent.cget("bg")).pack(fill="x")


def panel(parent,bg=None,pad=18,border=True):
    bg = bg or C["panel"]
    w = tk.Frame(parent,bg=C["border"] if border else bg,padx=int(border),pady=int(border))
    b = tk.Frame(w,bg=bg,padx=pad,pady=pad)
    b.pack(fill="both",expand=True)
    return w,b


class ActionButton(tk.Canvas):
    def __init__(self,parent,text,command,kind="primary",width=160,height=42,icon="",enabled=True):
        self.bg=parent.cget("bg")
        super().__init__(parent,bg=self.bg,height=height,width=width,highlightthickness=0,
                         cursor="hand2" if enabled else "arrow",bd=0)
        self.command,self.kind,self.enabled=command,kind,enabled
        self.txt,self.icon,self.w,self.h=text,icon,width,height
        self._draw(False)
        self.bind("<Enter>",lambda e:self._draw(True))
        self.bind("<Leave>",lambda e:self._draw(False))
        self.bind("<Button-1>",lambda e:self.enabled and self.command())

    def _draw(self,hover):
        self.delete("all")
        schemes = {
            "primary":(C["accent"],C["accentdark"],"#FFFFFF"),
            "light":(C["lime"],"#E5F4C6",C["hero"]),
            "outline":(C["panel2"],C["soft"],C["accentdark"]),
            "quiet":("#FFFFFF","#F0F4ED",C["accentdark"]),
            "subtle":(C["soft"],"#DFEFE5",C["accentdark"]),
        }
        base,over,fg=schemes.get(self.kind,schemes["outline"])
        if not self.enabled: base,over,fg=C["subtle"],C["subtle"],C["dim"]
        fill=over if hover and self.enabled else base
        x1,y1,x2,y2=0,0,self.w,self.h
        r=10
        self.create_arc(x1,y1,x1+2*r,y1+2*r,start=90,extent=90,fill=fill,outline=fill)
        self.create_arc(x2-2*r,y1,x2,y1+2*r,start=0,extent=90,fill=fill,outline=fill)
        self.create_arc(x1,y2-2*r,x1+2*r,y2,start=180,extent=90,fill=fill,outline=fill)
        self.create_arc(x2-2*r,y2-2*r,x2,y2,start=270,extent=90,fill=fill,outline=fill)
        self.create_rectangle(r,0,self.w-r,self.h,fill=fill,outline=fill)
        self.create_rectangle(0,r,self.w,self.h-r,fill=fill,outline=fill)
        self.create_text(self.w//2,self.h//2,text=(self.icon+"  " if self.icon else "")+self.txt,
                         fill=fg,font=(FONT,10,"bold"))


def logo(canvas_bg,side=42):
    z=tk.Canvas(canvas_bg,bg=canvas_bg.cget('bg'),width=side,height=side,highlightthickness=0,bd=0)
    s=side/44
    # Três pontos conectados por um caminho contínuo em forma de livro aberto.
    z.create_line(9*s,13*s,22*s,24*s,35*s,12*s,fill=C['accent'],width=3.7*s,
                  capstyle=tk.ROUND,joinstyle=tk.ROUND)
    z.create_line(9*s,13*s,9*s,33*s,22*s,39*s,35*s,33*s,35*s,12*s,
                  fill=C['accent'],width=3.7*s,capstyle=tk.ROUND,joinstyle=tk.ROUND)
    for x,y in ((9,13),(22,24),(35,12)):
        r=3.3*s
        z.create_oval(x*s-r,y*s-r,x*s+r,y*s+r,fill=C['accent'],outline=canvas_bg.cget('bg'),width=1)
    return z


class TramaApp:
    def __init__(self,root:tk.Tk):
        self.root=root
        self.root.title('TRAMA  |  Seu conhecimento conectado')
        self.root.geometry('1260x815')
        self.root.minsize(1000,710)
        self.root.configure(bg=C['bg'])
        try:
            img=tk.PhotoImage(file=str(ASSETS/'trama-icon.png'))
            self.root.iconphoto(True,img); self._icon=img
            if sys.platform=='win32':
                self.root.iconbitmap(str(ASSETS/'trama.ico'))
        except (tk.TclError,OSError):
            pass
        self.messages=queue.Queue()
        self.working=False
        self.current='inicio'
        self.history=[]
        self.state=self._load_settings()
        self.vault=tk.StringVar(value=self.state.get('vault',str(Path.home()/'Documents'/'Meu Conhecimento')))
        self.inbox=tk.StringVar(value=self.state.get('inbox',str(Path.home()/'Documents'/'Aulas para importar')))
        self.github=tk.StringVar()
        self.status=tk.StringVar(value='Pronto para organizar seus materiais')
        self.nav={}
        self._shell()
        self.navigate('inicio')
        self.root.after(160,self._poll)

    @staticmethod
    def _load_settings():
        for f in (SETTINGS_FILE,OLD_DATA_HOME/'settings.json'):
            try:
                if f.exists():
                    result=json.loads(f.read_text(encoding='utf-8'))
                    if isinstance(result,dict):return result
            except (OSError,ValueError): pass
        old=APP_ROOT/'.ultimo-cofre'
        if old.is_file():
            try: return {'vault':old.read_text(encoding='utf-8').strip()}
            except OSError: pass
        return {}

    def _save_settings(self):
        DATA_HOME.mkdir(parents=True,exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps({'vault':self.vault.get(),'inbox':self.inbox.get()},ensure_ascii=False,indent=2),encoding='utf-8')

    def _shell(self):
        self.shell=tk.Frame(self.root,bg=C['bg'])
        self.shell.pack(fill='both',expand=True)
        self.sidebar=tk.Frame(self.shell,bg=C['side'],width=246)
        self.sidebar.pack(side='left',fill='y')
        self.sidebar.pack_propagate(False)
        brand=tk.Frame(self.sidebar,bg=C['side'],padx=23,pady=25)
        brand.pack(fill='x')
        logo(brand,43).pack(side='left',padx=(0,10))
        text=tk.Frame(brand,bg=C['side']); text.pack(side='left',anchor='w')
        label(text,'trama.',20,C['text'],'bold').pack(anchor='w')
        label(text,'SEU ACERVO PESSOAL',7,C['dim'],'bold').pack(anchor='w',pady=(0,0))
        tk.Frame(self.sidebar,height=1,bg=C['border']).pack(fill='x',padx=22,pady=(0,28))
        label(self.sidebar,'EXPLORAR',8,C['dim'],'bold').pack(anchor='w',padx=28,pady=(0,10))
        items=[('inicio','◫','Visão geral'),('aulas','▣','Minhas aulas'),('projetos','⌘','Projetos e código'),
               ('biblioteca','▤','Meu conhecimento')]
        for key,glyph,title in items:
            row=tk.Frame(self.sidebar,bg=C['side'],height=48)
            row.pack(fill='x',padx=12,pady=2)
            row.pack_propagate(False)
            stripe=tk.Frame(row,bg=C['side'],width=3); stripe.pack(side='left',fill='y',padx=(0,12))
            tx=label(row,f'{glyph}    {title}',10,C['muted'],'bold')
            tx.pack(side='left',fill='both',expand=True)
            for w in (row,stripe,tx):
                w.bind('<Button-1>',lambda ev,k=key:self.navigate(k)); w.configure(cursor='hand2')
            self.nav[key]=(row,tx,stripe)
        spacer(self.sidebar,22)
        label(self.sidebar,'SISTEMA',8,C['dim'],'bold').pack(anchor='w',padx=28,pady=(0,10))
        key='config';row=tk.Frame(self.sidebar,bg=C['side'],height=48)
        row.pack(fill='x',padx=12,pady=2);row.pack_propagate(False)
        stripe=tk.Frame(row,bg=C['side'],width=3);stripe.pack(side='left',fill='y',padx=(0,12))
        tx=label(row,'⚙    Configurações',10,C['muted'],'bold');tx.pack(side='left',fill='both',expand=True)
        for w in (row,stripe,tx):
            w.bind('<Button-1>',lambda ev:self.navigate('config'));w.configure(cursor='hand2')
        self.nav[key]=(row,tx,stripe)
        tk.Frame(self.sidebar,bg=C['side']).pack(fill='both',expand=True)
        # Rodapé da marca: privacidade sem promessas exageradas.
        p=tk.Frame(self.sidebar,bg=C['soft'],padx=16,pady=14)
        p.pack(fill='x',padx=14,pady=(0,20))
        label(p,'●  ARQUIVOS LOCAIS',8,C['accent'],'bold').pack(anchor='w')
        label(p,'Seus materiais ficam na pasta\nque você escolher.',9,C['muted']).pack(anchor='w',pady=(7,0))
        self.right=tk.Frame(self.shell,bg=C['bg']);self.right.pack(side='left',fill='both',expand=True)
        top=tk.Frame(self.right,bg=C['bg'],height=70);top.pack(fill='x',padx=35);top.pack_propagate(False)
        label(top,'TRAMA    /    BIBLIOTECA PESSOAL',8,C['dim'],'bold').pack(side='left',pady=26)
        status=tk.Frame(top,bg=C['soft'],padx=12,pady=8);status.pack(side='right',pady=18)
        label(status,'●   NO SEU COMPUTADOR',8,C['accent'],'bold').pack()
        tk.Frame(self.right,height=1,bg=C['border']).pack(fill='x')
        self.scroll=tk.Canvas(self.right,bg=C['bg'],highlightthickness=0,bd=0)
        self.scroll.pack(side='top',fill='both',expand=True)
        self.content=tk.Frame(self.scroll,bg=C['bg'])
        self.content_win=self.scroll.create_window((0,0),window=self.content,anchor='nw')
        self.scroll.bind('<Configure>',lambda e:self.scroll.itemconfig(self.content_win,width=e.width))
        self.content.bind('<Configure>',lambda e:self.scroll.configure(scrollregion=self.scroll.bbox('all')))
        self.root.bind_all('<MouseWheel>',self._wheel)
        self.root.bind_all('<Button-4>',lambda e:self.scroll.yview_scroll(-3,'units'))
        self.root.bind_all('<Button-5>',lambda e:self.scroll.yview_scroll(3,'units'))
        footer=tk.Frame(self.right,bg=C['side'],height=36);footer.pack(fill='x',side='bottom')
        self.footer_label=label(footer,'●  '+self.status.get(),9,C['muted'])
        self.footer_label.pack(side='left',padx=34,pady=8)
        label(footer,'TRAMA  /  0.3',8,C['dim'],'bold').pack(side='right',padx=24)

    def _wheel(self,event):
        if isinstance(event.widget,tk.Text):return
        self.scroll.yview_scroll(-int(event.delta/120),'units')

    def navigate(self,page):
        self.current=page
        for key,(row,tx,stripe) in self.nav.items():
            selected=key==page
            col=C['soft'] if selected else C['side']
            row.configure(bg=col)
            tx.configure(bg=col,fg=C['accentdark'] if selected else C['muted'])
            stripe.configure(bg=C['accent'] if selected else col)
        for w in self.content.winfo_children():w.destroy()
        self.scroll.yview_moveto(0)
        {'inicio':self._home,'aulas':self._lessons,'projetos':self._projects,
         'biblioteca':self._library,'config':self._config}[page]()

    def _page(self,eyebrow,title,desc):
        p=tk.Frame(self.content,bg=C['bg'],padx=36,pady=24)
        p.pack(fill='both',expand=True)
        label(p,eyebrow,8,C['accent'],'bold').pack(anchor='w',pady=(0,11))
        label(p,title,27,C['text'],'bold',family=DISPLAY,wraplength=800).pack(anchor='w')
        label(p,desc,10,C['muted'],wraplength=800).pack(anchor='w',pady=(9,22))
        return p

    def _counts(self):
        vault=Path(self.vault.get()).expanduser()
        db=vault/'.base-conhecimento'/'estado.sqlite3'
        if not db.is_file():return {'transcript':0,'video':0,'repo':0,'published':0,'pending':0,'recent':[]}
        import sqlite3
        try:
            with closing(sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True,timeout=2)) as conn:
                rows=conn.execute('SELECT kind,status,label,lesson FROM sources ORDER BY updated_at DESC LIMIT 9').fetchall()
                counts=dict(conn.execute('SELECT kind,COUNT(*) FROM sources GROUP BY kind').fetchall())
                pub=conn.execute("SELECT COUNT(*) FROM sources WHERE status='PUBLISHED'").fetchone()[0]
                repos=conn.execute('SELECT COUNT(*) FROM repositories').fetchone()[0]
        except (OSError,sqlite3.Error):return {'transcript':0,'video':0,'repo':0,'published':0,'pending':0,'recent':[]}
        return {'transcript':counts.get('transcript',0),'video':counts.get('video',0),'repo':repos,
                'published':pub,'pending':max(0,counts.get('transcript',0)-pub),'recent':rows}

    def _home(self):
        p=self._page('SEU ESPAÇO  /  VISÃO GERAL','Conhecimento não precisa ficar espalhado.',
             'Aulas, experiências e código em uma biblioteca que cresce junto com você.')
        # Faixa principal editorial: produto, ação central e relações.
        hero=tk.Frame(p,bg=C['hero'],height=238)
        hero.pack(fill='x');hero.pack_propagate(False)
        left=tk.Frame(hero,bg=C['hero'],padx=26,pady=22);left.pack(side='left',fill='both',expand=True)
        label(left,'COMECE PELO QUE VOCÊ JÁ APRENDEU',8,C['lime'],'bold').pack(anchor='w')
        label(left,'Seu repertório.\nAgora conectado.',22,'#FFFFFF','bold',family=DISPLAY).pack(anchor='w',pady=(9,7))
        label(left,'Importe uma aula. O resto da história vem com o tempo.',9,'#C2D8CE').pack(anchor='w')
        buttons=tk.Frame(left,bg=C['hero']);buttons.pack(anchor='w',pady=(14,0))
        ActionButton(buttons,'Adicionar aulas',lambda:self.navigate('aulas'),kind='light',width=156,height=38).pack(side='left')
        ActionButton(buttons,'Ver biblioteca',lambda:self.navigate('biblioteca'),kind='quiet',width=151,height=38).pack(side='left',padx=(9,0))
        art=tk.Canvas(hero,bg=C['hero'],width=270,height=238,highlightthickness=0)
        art.pack(side='right',padx=(0,22))
        # Linha causal: aula -> conceito -> projeto. Identidade abstrata, não ilustração genérica.
        art.create_line(37,111,110,62,188,111,fill='#719D87',width=2,smooth=True)
        art.create_line(37,111,110,154,188,111,fill='#719D87',width=2,smooth=True)
        art.create_line(110,62,188,111,110,154,fill='#719D87',width=2,smooth=True)
        for x,y,ring,dot,title in [(37,111,'#679E88','#E2F2C4','AULAS'),(110,62,'#679E88','#F2E6C8','IDEIAS'),
                                    (188,111,'#90BA98','#D3E8A3','VOCÊ'),(110,154,'#679E88','#C5DED4','CÓDIGO')]:
            r=17 if title=='VOCÊ' else 13
            art.create_oval(x-r,y-r,x+r,y+r,outline=ring,width=2)
            art.create_oval(x-5,y-5,x+5,y+5,fill=dot,outline='')
            art.create_text(x,y+26,text=title,fill='#BCD7C8',font=(FONT,7,'bold'))
        spacer(p,22)
        counts=self._counts()
        stats=tk.Frame(p,bg=C['bg']);stats.pack(fill='x')
        values=[('AULAS',counts['transcript'],'Transcrições',C['accent']),
                ('GRAVAÇÕES',counts['video'],'Vídeos guardados',C['text']),
                ('PROJETOS',counts['repo'],'Repositórios',C['text']),
                ('DOCUMENTADAS',counts['published'],'Resumos prontos',C['accent'])]
        for i,(name,num,sub,col) in enumerate(values):
            stats.grid_columnconfigure(i,weight=1,uniform='metric')
            w,b=panel(stats,pad=14)
            w.grid(row=0,column=i,sticky='nsew',padx=(0,10) if i<3 else 0)
            label(b,name,8,C['dim'],'bold').pack(anchor='w')
            r=tk.Frame(b,bg=C['panel']);r.pack(anchor='w',fill='x',pady=(4,0))
            label(r,str(num),22,col,'bold').pack(anchor='w',side='left')
            label(r,sub,8,C['muted']).pack(anchor='w',side='left',padx=(11,0),pady=(8,0))
        spacer(p,24)
        hd=tk.Frame(p,bg=C['bg']);hd.pack(fill='x',pady=(0,11))
        label(hd,'Três partes. Uma só história.',16,C['text'],'bold',family=DISPLAY).pack(side='left')
        label(hd,'Tudo se relaciona',9,C['accent']).pack(side='right',pady=(5,0))
        parts=tk.Frame(p,bg=C['bg']);parts.pack(fill='x')
        for i,(num,head,desc,page) in enumerate([
            ('01','Seu conhecimento','Resumos gerais por assunto.','biblioteca'),
            ('02','Suas aulas','Vídeos, transcrições e momentos.','aulas'),
            ('03','Seu código','Repositórios e decisões técnicas.','projetos')]):
            parts.grid_columnconfigure(i,weight=1,uniform='part')
            wrap,body=panel(parts,pad=17)
            wrap.grid(row=0,column=i,sticky='nsew',padx=(0,11) if i<2 else 0)
            row=tk.Frame(body,bg=C['panel']);row.pack(fill='x')
            label(row,num,9,C['accent'],'bold').pack(side='left')
            label(row,'↗',13,C['dim']).pack(side='right')
            label(body,head,12,C['text'],'bold').pack(anchor='w',pady=(12,4))
            label(body,desc,9,C['muted'],wraplength=200).pack(anchor='w')
            ActionButton(body,'Explorar',lambda pg=page:self.navigate(pg),kind='subtle',width=95,height=31).pack(anchor='w',pady=(15,0))
        self._recent_block(p,counts)

    def _recent_block(self,p,counts):
        spacer(p,24)
        label(p,'Atividade recente',15,C['text'],'bold',family=DISPLAY).pack(anchor='w',pady=(0,12))
        w,b=panel(p,pad=18);w.pack(fill='x')
        if not counts['recent']:
            label(b,'Seu acervo começa com a primeira aula.',11,C['text'],'bold').pack(anchor='w')
            label(b,'Importe uma transcrição para acompanhar os materiais aqui.',9,C['muted']).pack(anchor='w',pady=(6,0))
            return
        for i,(kind,status,name,lesson) in enumerate(counts['recent'][:5]):
            line=tk.Frame(b,bg=C['panel']);line.pack(fill='x',pady=7)
            label(line,'▣' if kind=='transcript' else '▷',12,C['accent']).pack(side='left',padx=(0,10))
            label(line,name[:74]+('…' if len(name)>74 else ''),10,C['text'],'bold').pack(side='left')
            label(line,{'READY':'Pendente','PUBLISHED':'Concluído','WAITING_FOR_PROVIDER':'Sem IA',
                        'STORED':'Guardado'}.get(status,status),9,C['muted']).pack(side='right')
            if i<min(len(counts['recent']),5)-1: tk.Frame(b,bg=C['border'],height=1).pack(fill='x')

    def _entry(self,parent,var,show=None):
        w=tk.Frame(parent,bg=C['border'],padx=1,pady=1)
        entry=tk.Entry(w,textvariable=var,bg='#FAFCFA',fg=C['text'],insertbackground=C['text'],
                       relief='flat',highlightthickness=0,font=(FONT,10),show=show)
        entry.pack(fill='x',ipady=12,ipadx=13)
        return w

    def _choose_folder(self,var,title):
        loc=Path(var.get()).expanduser()
        directory=loc.parent if loc.parent.exists() else Path.home()
        path=filedialog.askdirectory(title=title,initialdir=str(directory))
        if path:var.set(path);self._save_settings()

    def _lessons(self):
        p=self._page('FONTES  /  TRANSCRIÇÕES E VÍDEOS','Sua próxima aula começa aqui.',
            'Escolha os arquivos. A TRAMA guarda os originais e prepara as notas para o Obsidian.')
        w,b=panel(p,pad=24);w.pack(fill='x')
        label(b,'01  ·  PASTA DE ENTRADA',8,C['accent'],'bold').pack(anchor='w')
        label(b,'Selecione os materiais',17,C['text'],'bold',family=DISPLAY).pack(anchor='w',pady=(8,6))
        label(b,'O aplicativo só lê o que você selecionar. Os arquivos não são executados.',9,C['muted']).pack(anchor='w',pady=(0,16))
        r=tk.Frame(b,bg=C['panel']);r.pack(fill='x')
        self._entry(r,self.inbox).pack(side='left',fill='x',expand=True,padx=(0,10))
        ActionButton(r,'Escolher pasta',lambda:self._choose_folder(self.inbox,'Pasta das aulas'),kind='outline',width=142).pack(side='right')
        spacer(b,15)
        actions=tk.Frame(b,bg=C['panel']);actions.pack(anchor='w')
        ActionButton(actions,'Importar pasta',self._scan_folder,width=155).pack(side='left')
        ActionButton(actions,'Selecionar arquivos',self._pick_files,kind='outline',width=172).pack(side='left',padx=(10,0))
        spacer(p,17)
        info=tk.Frame(p,bg=C['soft'],padx=20,pady=18);info.pack(fill='x')
        label(info,'COMO NOMEAR',8,C['accent'],'bold').pack(anchor='w')
        label(info,'Aula-168-V01.txt  +  Aula-168-V01.mp4',11,C['text'],'bold',family=MONO).pack(anchor='w',pady=(7,5))
        label(info,'Usando o mesmo nome-base, a gravação e a transcrição podem ser relacionadas.',9,C['muted']).pack(anchor='w')
        spacer(p,18)
        cards=tk.Frame(p,bg=C['bg']);cards.pack(fill='x')
        for idx,(symbol,title,subtitle) in enumerate([
            ('▤','Transcrições','Arquivos .txt e .md'),('▷','Gravações','Arquivos .mp4, .mkv, .mov e .webm')]):
            cards.grid_columnconfigure(idx,weight=1,uniform='formats')
            wr,bd=panel(cards,pad=20)
            wr.grid(row=0,column=idx,sticky='nsew',padx=(0,12) if idx==0 else 0)
            label(bd,symbol,22,C['accent']).pack(anchor='w')
            label(bd,title,12,C['text'],'bold').pack(anchor='w',pady=(8,4))
            label(bd,subtitle,9,C['muted']).pack(anchor='w')
        spacer(p,22);self._action_area(p)

    def _projects(self):
        p=self._page('FONTES  /  GITHUB','Código também é conhecimento.',
            'Adicione projetos agora ou depois. A TRAMA registra a origem sem executar o código importado.')
        w,b=panel(p,pad=24);w.pack(fill='x')
        label(b,'01  ·  REPOSITÓRIOS',8,C['accent'],'bold').pack(anchor='w')
        label(b,'Cole a URL de um projeto público',17,C['text'],'bold',family=DISPLAY).pack(anchor='w',pady=(9,14))
        self._entry(b,self.github).pack(fill='x')
        r=tk.Frame(b,bg=C['panel']);r.pack(anchor='w',pady=(15,0))
        ActionButton(r,'Importar do GitHub',self._repo_url,width=179).pack(side='left')
        ActionButton(r,'Selecionar pasta Git',self._repo_local,kind='outline',width=180).pack(side='left',padx=(10,0))
        spacer(p,17)
        info=tk.Frame(p,bg=C['soft'],padx=20,pady=18);info.pack(fill='x')
        label(info,'LEITURA, NÃO EXECUÇÃO',8,C['accent'],'bold').pack(anchor='w')
        label(info,'O projeto é catalogado como fonte de estudo. O programa não instala dependências nem executa o repositório.',9,C['muted'],wraplength=740).pack(anchor='w',pady=(7,0))
        spacer(p,22);self._action_area(p)

    def _library(self):
        p=self._page('SEU ACERVO  /  OBSIDIAN','Uma biblioteca. Três perspectivas.',
            'Seu conhecimento, as aulas originais e o código se complementam sem se misturar.')
        pieces=[('01','Meu conhecimento','Sínteses e conceitos consolidados.','01-Meu-Conhecimento'),
                ('02','Minhas aulas','Transcrições, vídeos e referência temporal.','02-Minhas-Aulas'),
                ('03','Meus projetos','Arquivos de código e histórico de Git.','03-Meus-Projetos')]
        for num,head,subtitle,d in pieces:
            wr,b=panel(p,pad=19);wr.pack(fill='x',pady=(0,11))
            row=tk.Frame(b,bg=C['panel']);row.pack(fill='x')
            lab=tk.Frame(row,bg=C['soft'],width=45,height=45);lab.pack(side='left',padx=(0,17));lab.pack_propagate(False)
            label(lab,num,12,C['accent'],'bold').pack(expand=True)
            descr=tk.Frame(row,bg=C['panel']);descr.pack(side='left',fill='x',expand=True)
            label(descr,head,12,C['text'],'bold').pack(anchor='w')
            label(descr,subtitle,9,C['muted']).pack(anchor='w',pady=(4,0))
            ActionButton(row,'Abrir pasta',lambda rel=d:self._open_folder(rel),kind='outline',width=121,height=37).pack(side='right')
        spacer(p,8)
        highlight=tk.Frame(p,bg=C['hero'],padx=23,pady=22);highlight.pack(fill='x')
        label(highlight,'PARA SUAS FUTURAS IAS',8,C['lime'],'bold').pack(anchor='w')
        label(highlight,'MEU_CONTEXTO.md',17,'#FFFFFF','bold',family=MONO).pack(anchor='w',pady=(9,6))
        label(highlight,'Um mapa do que foi ensinado e praticado. O domínio real exige validação.',9,'#C2D8CE').pack(anchor='w')
        actions=tk.Frame(highlight,bg=C['hero']);actions.pack(anchor='w',pady=(16,0))
        ActionButton(actions,'Abrir cofre',lambda:self._open_folder(''),kind='light',width=139,height=37).pack(side='left')
        ActionButton(actions,'Atualizar índices',lambda:self._run('rebuild'),kind='quiet',width=160,height=37).pack(side='left',padx=(10,0))
        spacer(p,22);self._action_area(p)

    def _config(self):
        p=self._page('SISTEMA  /  PREFERÊNCIAS','Tudo sob seu controle.',
            'Escolha o cofre e, se quiser, configure um provedor de IA realmente gratuito.')
        w,b=panel(p,pad=23);w.pack(fill='x')
        label(b,'LOCALIZAÇÃO DO OBSIDIAN',8,C['accent'],'bold').pack(anchor='w')
        label(b,'Seu cofre pessoal',16,C['text'],'bold',family=DISPLAY).pack(anchor='w',pady=(9,13))
        r=tk.Frame(b,bg=C['panel']);r.pack(fill='x')
        self._entry(r,self.vault).pack(side='left',fill='x',expand=True,padx=(0,10))
        ActionButton(r,'Escolher',lambda:self._choose_folder(self.vault,'Cofre Obsidian'),kind='outline',width=100).pack(side='right')
        label(b,'Use uma pasta exclusiva ou selecione seu cofre já existente.',9,C['muted']).pack(anchor='w',pady=(11,0))
        spacer(p,17)
        w,b=panel(p,pad=23);w.pack(fill='x')
        label(b,'PROVEDORES DE INTELIGÊNCIA ARTIFICIAL',8,C['accent'],'bold').pack(anchor='w')
        label(b,'Gerar resumos automaticamente',16,C['text'],'bold',family=DISPLAY).pack(anchor='w',pady=(9,7))
        label(b,'Você pode importar aulas sem IA. O envio a serviços externos só ocorre após sua confirmação.',9,C['muted'],wraplength=730).pack(anchor='w',pady=(0,12))
        env=read_env(CONFIG_FILE)
        for name,key in [('Gemini','GEMINI_API_KEY'),('GroqCloud','GROQ_API_KEY'),('OpenRouter','OPENROUTER_API_KEY')]:
            row=tk.Frame(b,bg=C['panel']);row.pack(fill='x',pady=5)
            label(row,name,10,C['text'],'bold').pack(side='left')
            label(row,'●  Configurado' if env.get(key) else '○  Não configurado',9,C['green'] if env.get(key) else C['dim']).pack(side='right')
        spacer(b,14)
        row=tk.Frame(b,bg=C['panel']);row.pack(anchor='w')
        ActionButton(row,'Configurar IA',self._settings_dialog,width=148).pack(side='left')
        ActionButton(row,'Gerar resumos',self._process,kind='outline',width=155).pack(side='left',padx=(10,0))
        spacer(p,17)
        warn=tk.Frame(p,bg=C['warm'],padx=20,pady=16);warn.pack(fill='x')
        label(warn,'CUSTO ADICIONAL ZERO É UMA RESTRIÇÃO',8,C['orange'],'bold').pack(anchor='w')
        label(warn,'Não use uma chave de API que tenha faturamento ou recarga automática. O aplicativo não consegue bloquear cobranças na conta externa.',9,C['text'],wraplength=750).pack(anchor='w',pady=(6,0))
        spacer(p,22);self._action_area(p)

    def _action_area(self,p):
        label(p,'Registro de atividade',15,C['text'],'bold',family=DISPLAY).pack(anchor='w',pady=(0,12))
        wrap,b=panel(p,pad=14);wrap.pack(fill='x')
        out=tk.Text(b,height=5,bg=C['panel'],fg=C['muted'],font=(MONO,9),
                    relief='flat',highlightthickness=0,wrap='word',insertbackground=C['text'])
        out.pack(fill='x')
        out.insert('end','\n'.join(self.history[-25:]) if self.history else 'Nenhuma operação realizada nesta sessão.\nO processamento só começa quando você solicitar.')
        out.configure(state='disabled');self.log_widget=out

    def _log(self,message):
        self.messages.put(('log',datetime.now().strftime('%H:%M')+'  '+message))

    def _validate_paths(self):
        raw=self.vault.get().strip()
        if not raw or not Path(raw).expanduser().is_absolute():
            raise ValueError("Escolha uma pasta absoluta para o cofre do Obsidian.")
        chosen = Path(raw).expanduser().resolve()
        home = Path.home().resolve()
        if chosen in {Path(chosen.anchor), home, home.parent}:
            raise ValueError("Crie uma pasta dedicada ao Obsidian. Não use a raiz do disco nem a pasta inteira do usuário.")
        if os.name == "nt":
            forbidden = {"windows", "program files", "program files (x86)"}
            if len(chosen.parts) > 1 and chosen.parts[1].casefold() in forbidden:
                raise ValueError("Não use pastas do sistema Windows como cofre.")
        self._save_settings()
        return chosen

    def _run(self,action,paths=None,source=None):
        if self.working:
            messagebox.showinfo("Operação em andamento","Aguarde a operação atual terminar.")
            return
        try:
            vault=self._validate_paths()
        except Exception as exc:
            messagebox.showerror("Caminho inválido",str(exc))
            return
        inbox_path = self.inbox.get()
        self.working=True
        self._set_status("Processando... você pode acompanhar a atividade")
        self._log("Iniciando operação: "+action)
        def worker():
            app=None
            try:
                app=Application(vault,config=CONFIG_FILE,log=self._log)
                if action=="scan": app.scan(Path(inbox_path))
                elif action=="files":
                    for path in paths:
                        app.add_file(Path(path))
                    app.publisher.rebuild()
                elif action=="repo": app.add_repo(source)
                elif action=="process": app.process()
                elif action=="rebuild": app.publisher.rebuild()
                summary="Operação concluída. Biblioteca atualizada."
                if action == "process":
                    statuses = app.stats()
                    if statuses.get("WAITING_FOR_PROVIDER"):
                        summary="IA pausada: provedor indisponível ou cota. Suas notas foram preservadas."
                    elif statuses.get("NEEDS_REVIEW"):
                        summary="Alguns resumos precisam de revisão. Veja a atividade."
                self.messages.put(("done",summary))
            except Exception as exc:
                self.messages.put(("error",f"{type(exc).__name__}: {exc}"))
            finally:
                if app:
                    app.close()
        threading.Thread(target=worker,daemon=True,name="TRAMA-worker").start()

    def _scan_folder(self):
        if not Path(self.inbox.get()).is_dir():
            messagebox.showinfo("Selecionar pasta","Escolha uma pasta existente com transcrições e vídeos.")
            return
        self._run("scan")

    def _pick_files(self):
        paths=filedialog.askopenfilenames(title="Selecionar transcrições e vídeos",filetypes=[
            ("Materiais compatíveis","*.txt *.md *.mp4 *.mkv *.mov *.webm"),
            ("Todos os arquivos","*.*")])
        if paths:
            self._run("files",paths=paths)

    def _repo_url(self):
        source=self.github.get().strip()
        if not source:
            messagebox.showinfo("Repositório","Cole a URL de um repositório público GitHub.")
            return
        if not messagebox.askyesno("Importar código público","A TRAMA vai se conectar ao GitHub para obter este repositório público.\n\nNão executará o código baixado. Continuar?"):
            return
        self._run("repo",source=source)

    def _repo_local(self):
        source=filedialog.askdirectory(title="Escolher pasta de repositório Git")
        if source:
            self.github.set(source)
            self._run("repo",source=source)

    def _process(self):
        env=read_env(CONFIG_FILE)
        usable=env.get("FREE_TIER_CONFIRMED")=="YES" and any(env.get(key) for _,key in ALLOWED.values())
        if not usable:
            messagebox.showinfo("IA não configurada","Você já pode importar e organizar aulas sem IA.\n\nPara gerar resumos automáticos, vá em Configurações e cadastre uma chave de um projeto realmente gratuito, sem faturamento.")
            self.navigate("config")
            return
        if not messagebox.askyesno("Autorizar envio de transcrições",
          "A IA externa receberá trechos das transcrições para criar resumos.\n\nConfirme que você tem permissão para compartilhar esse conteúdo e que o projeto de API NÃO possui faturamento nem recarga automática.\n\nDeseja iniciar?"):
            return
        self._run("process")

    def _open_folder(self,rel):
        path=(Path(self.vault.get()).expanduser()/rel).resolve()
        vault=Path(self.vault.get()).expanduser().resolve()
        if not path.is_relative_to(vault):
            return
        if not path.exists():
            messagebox.showinfo("Pasta ainda não existe","Importe uma aula para criar essa parte da biblioteca.")
            return
        try:
            if sys.platform=="win32":
                os.startfile(str(path))  # Abre no Explorador de Arquivos, não executa o conteúdo.
            elif sys.platform=="darwin":
                import subprocess
                subprocess.Popen(["open",str(path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open",str(path)])
        except OSError as exc:
            messagebox.showerror("Erro ao abrir pasta",str(exc))

    def _settings_dialog(self):
        dialog=tk.Toplevel(self.root)
        dialog.title("TRAMA · Provedores de IA")
        dialog.geometry("640x605")
        dialog.resizable(False,False)
        dialog.configure(bg=C["side"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0,weight=1)
        content=tk.Frame(dialog,bg=C["side"],padx=30,pady=26)
        content.pack(fill="both",expand=True)
        label(content,"Configure sua IA",21,C["text"],"bold").pack(anchor="w")
        label(content,"Deixe em branco qualquer serviço que não queira usar.",10,C["muted"]).pack(anchor="w",pady=(8,18))
        stored=read_env(CONFIG_FILE)
        secret_vars={}
        for name,key in [("Gemini (Google)","GEMINI_API_KEY"),("GroqCloud","GROQ_API_KEY"),("OpenRouter","OPENROUTER_API_KEY")]:
            label(content,name,10,C["text"],"bold").pack(anchor="w",pady=(9,5))
            var=tk.StringVar(value=stored.get(key,""))
            self._entry(content,var,show="●").pack(fill="x")
            secret_vars[key]=var
        spacer(content,15)
        agree=tk.BooleanVar(value=stored.get("FREE_TIER_CONFIRMED")=="YES")
        chk=tk.Checkbutton(content,variable=agree,text="Confirmei que estas contas NÃO têm faturamento nem recarga automática.",
                           bg=C["side"],fg=C["text"],activebackground=C["side"],activeforeground=C["text"],
                           selectcolor=C["panel2"],font=(FONT,9),anchor="w",wraplength=530)
        chk.pack(anchor="w")
        label(content,"As chaves ficam em arquivo local (não criptografado). Não compartilhe a pasta de configuração.",9,C["orange"],wraplength=545).pack(anchor="w",pady=(11,16))
        def save():
            if any(v.get().strip() for v in secret_vars.values()) and not agree.get():
                messagebox.showwarning("Confirmar plano gratuito","Marque a confirmação somente após verificar que as contas estão realmente sem faturamento.",parent=dialog)
                return
            DATA_HOME.mkdir(parents=True,exist_ok=True)
            lines=["# TRAMA — Chaves privadas. Nunca compartilhe este arquivo.",
                   "FREE_TIER_CONFIRMED="+("YES" if agree.get() else "NO"),
                   "FREE_PROVIDER_ORDER=gemini,groq,openrouter",
                   "MAX_REQUESTS_PER_RUN=12"]
            for key,var in secret_vars.items():
                val=var.get().strip()
                if "\n" in val or "\r" in val:
                    messagebox.showerror("Chave inválida","A chave não pode conter quebras de linha.",parent=dialog)
                    return
                lines.append(key+"="+val)
            # Diretório de perfil do próprio usuário. Sem enviar dados a serviços ao salvar.
            with CONFIG_FILE.open("w",encoding="utf-8") as target:
                target.write("\n".join(lines)+"\n")
            if os.name=="posix":
                CONFIG_FILE.chmod(0o600)
            dialog.destroy()
            self._log("Configuração de IA salva no perfil local (sem chamada à API).")
            self.navigate("config")
        actions=tk.Frame(content,bg=C["side"])
        actions.pack(fill="x")
        ActionButton(actions,"Salvar configuração",save,width=187,height=42).pack(side="left")
        ActionButton(actions,"Cancelar",dialog.destroy,kind="outline",width=110,height=42).pack(side="left",padx=(11,0))

    def _set_status(self,message):
        self.status.set(message)
        self.footer_label.configure(text="●  "+message)

    def _poll(self):
        updated=False
        try:
            while True:
                tag,val=self.messages.get_nowait()
                if tag=="log":
                    self.history.append(val)
                    self.history=self.history[-120:]
                    if hasattr(self,"log_widget") and self.log_widget.winfo_exists():
                        self.log_widget.configure(state="normal")
                        self.log_widget.insert("end",val+"\n")
                        self.log_widget.see("end")
                        self.log_widget.configure(state="disabled")
                elif tag=="done":
                    self.working=False
                    self._set_status(val)
                    updated=True
                elif tag=="error":
                    self.working=False
                    self._set_status("Erro controlado — veja a mensagem")
                    self.history.append("Falha: "+val)
                    messagebox.showerror("TRAMA · Operação não concluída",val)
                    updated=True
        except queue.Empty:
            pass
        if updated:
            self.navigate(self.current)
        self.root.after(150,self._poll)


def start_gui():
    root=tk.Tk()
    TramaApp(root)
    root.mainloop()
