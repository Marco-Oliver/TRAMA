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
    parser.add_argument("command",choices=["gui","init","import","process","repo","status","rebuild"])
    parser.add_argument("--vault",type=Path,default=ROOT / "Meu-Obsidian",help="pasta do cofre")
    parser.add_argument("--inbox",type=Path,help="pasta de transcrições e materiais (vídeos apenas por link)")
    parser.add_argument("--url",help="URL GitHub pública ou caminho de repo Git local")
    parser.add_argument("--config",type=Path,default=ROOT / "config.env")
    args=parser.parse_args(argv)
    if args.command=="gui":
        start_gui()
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
