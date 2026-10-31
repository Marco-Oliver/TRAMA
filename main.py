"""Entrada por terminal e interface simples para Windows."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from knowledge_bridge.pipeline import Application

ROOT = Path(__file__).resolve().parent


def start_gui():
    """Abre o painel visual TRAMA (interface Tkinter nativa)."""
    from knowledge_bridge.bridge import start_webview as launch
    launch()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Base de conhecimento incremental para Obsidian")
    parser.add_argument("command",choices=["gui","init","import","process","repo","status","rebuild","backup","restore"])
    parser.add_argument("--vault",type=Path,default=ROOT / "Meu-Obsidian",help="pasta do cofre")
    parser.add_argument("--inbox",type=Path,help="pasta de transcrições e materiais (vídeos apenas por link)")
    parser.add_argument("--url",help="URL GitHub pública ou caminho de repo Git local")
    parser.add_argument("--config",type=Path,default=ROOT / "config.env")
    parser.add_argument("--backup",type=Path,help="arquivo ZIP de backup (destino ou origem)")
    parser.add_argument("--restore-to",type=Path,help="nova pasta para restaurar um backup; não deve existir")
    args=parser.parse_args(argv)
    if args.command=="gui":
        start_gui()
        return
    if args.command == "restore":
        if not args.backup or not args.restore_to:
            parser.error("restore exige --backup e --restore-to")
        from knowledge_bridge.recovery import restore_backup
        print("Cofre restaurado:", restore_backup(args.backup, args.restore_to))
        return
    if args.command == "backup":
        if not args.backup:
            parser.error("backup exige --backup")
        from knowledge_bridge.recovery import create_backup
        print("Backup criado:", create_backup(args.vault, args.backup))
        return
    app=Application(args.vault,config=args.config)
    try:
        if args.command=="init":
            print("Cofre criado. Índices:",app.publisher.rebuild())
        elif args.command=="import":
            if not args.inbox: parser.error("--inbox é obrigatório")
            app.scan(args.inbox)
        elif args.command=="process":
            print("Índices:",app.process())
        elif args.command=="repo":
            if not args.url: parser.error("--url é obrigatório")
            app.add_repo(args.url)
        elif args.command=="rebuild":
            print("Índices:",app.publisher.rebuild())
        elif args.command=="status":
            print("Estados:",app.stats())
            print("Repositórios:",len(app.store.repositories()))
    finally:
        app.close()


if __name__=="__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido. O progresso salvo foi preservado.")
        sys.exit(130)
