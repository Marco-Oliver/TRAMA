"""Public-code integration: genuine course Git commit, synthetic lesson dialogue.

This exercise uses NO real Aula TXT, private Obsidian, external language model,
API key, or user files. It reads, never executes, public TypeScript code in a
pinned checkout of the Academia do Programador certificate generator.

Run from checkout: python tools/qa_public_course.py academy-course-source
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from knowledge_bridge.ai import AIResult
from knowledge_bridge.pipeline import Application
from knowledge_bridge.code_intel import match_lesson_to_repository

SOURCE_REPO = "academiadoprogramador-fullstack/gerador-de-certificados-2026"
SOURCE_COMMIT = "cd86334568a034c9847b34e1e0e9841381fc31a1"


class SimulatedTutor:
    def __init__(self):
        self.analyzed = []
        self.compared = 0

    def analyze(self, transcript: str, context: str) -> AIResult:
        self.analyzed.append(context)
        lesson = "031" if "Aula-031" in context else (
            "049" if "Aula-049" in context else "050")
        summaries = {
            "031": "O material menciona AuthService e HttpClient, mas deixa em aberto o que faz a injeção da dependência.",
            "049": "O material trata de guardas de rota que redirecionam quem ainda não autenticou.",
            "050": "O material explica que inject(HttpClient) obtém uma dependência para AuthService, que realiza chamadas HTTP."
        }
        names = {"031":["HttpClient","AuthService"],
                 "049":["CanActivateFn"],
                 "050":["HttpClient","AuthService","inject"]}[lesson]
        return AIResult({
            "resumo": summaries[lesson],
            "tipo_aula": "tecnica",
            "pessoas": [], "atividades": [], "ferramentas": [], "marcos": [],
            "conceitos": [{"nome": name, "explicacao": "Menção observada na fala simulada.",
                           "tempo": "0:01"} for name in names],
            "exemplos": [], "duvidas":
                ["Como o AuthService recebe HttpClient?"] if lesson=="031" else [],
            "nomes_a_conferir": []
        }, "simulado", "fixture-local")

    def compare(self, *_args) -> AIResult:
        self.compared += 1
        return AIResult(
            {"resumo": "Relações entre material fictício e código real exigem revisão.",
             "relacoes": [], "correcoes": [], "novidades": []},
            "simulado", "fixture-local")


def run(source_dir: Path) -> str:
    source_dir = source_dir.resolve()
    sha = subprocess.check_output(
        ["git","-C",str(source_dir),"rev-parse","HEAD"], text=True,
        timeout=30).strip()
    if sha != SOURCE_COMMIT:
        raise RuntimeError(f"Repositório público em revisão inesperada: {sha[:12]}")
    samples = {
        31: "[0:01] Estou mostrando AuthService e HttpClient.\n"
            "[0:03] Ainda não ficou claro como o AuthService recebe HttpClient.",
        49: "[0:01] Hoje estudamos CanActivateFn e autenticação de rotas.\n"
            "[0:02] Uma rota protegida redireciona quem não está autenticado.",
        50: "[0:01] Vamos retomar AuthService e HttpClient.\n"
            "[0:02] Aqui usamos inject(HttpClient) e o método post para requisições HTTP."
    }
    with tempfile.TemporaryDirectory(prefix="trama-v220-public-course-") as folder:
        workspace = Path(folder)
        vault = workspace/"Obsidian-Exclusivo-QA"
        app = Application(vault,workspace/"no-real-provider.env",log=lambda *_:None)
        teacher = SimulatedTutor()
        app.ai = teacher
        try:
            for n in (31,49):
                original=workspace/f"Aula-{n:03d}-V01.txt"
                original.write_text(samples[n], encoding="utf-8")
                if not app.add_file(original):
                    raise AssertionError(f"Falha ao adicionar Aula {n}")
                app.process()
            if len(teacher.analyzed)!=2:
                raise AssertionError("Aulas antigas foram reprocessadas")
            if not app.add_repo(str(source_dir)):
                raise AssertionError("Não indexou código do curso real")
            repo_rows=app.store.repositories()
            if len(repo_rows)!=1:
                raise AssertionError("Repositório real não registrado")
            indexed=json.loads(repo_rows[0]["payload"])
            symbols={x.get("name") for x in indexed.get("symbols",[])}
            for expected in ("AuthService","CursosService"):
                if expected not in symbols:
                    raise AssertionError(f"Símbolo de código público ausente: {expected}")
            if not match_lesson_to_repository(samples[31],None,indexed):
                raise AssertionError("Aula 031 não foi vinculada a código realmente indexado")
            original=workspace/"Aula-050-V01.txt"
            original.write_text(samples[50], encoding="utf-8")
            app.add_file(original)
            app.process()
            if len(teacher.analyzed)!=3:
                raise AssertionError("Importação Aula 050 consumiu análise de aula anterior")
            l31=vault/"02-Minhas-Aulas"/"Aula-031"
            note=next(p for p in l31.glob("*.md") if p.name!="00-Visao-geral.md")
            written=note.read_text(encoding="utf-8")
            if "Aula-050" not in written:
                raise AssertionError("Aula 050 não gerou evidência posterior para Aula 031")
            if "não comprovam" not in written:
                raise AssertionError("A nota afirma uma hipótese como fato")
            project=next(p for p in (vault/"03-Meus-Projetos").glob("*.md"))
            project_text=project.read_text(encoding="utf-8")
            if "AuthService" not in project_text or "CursosService" not in project_text:
                raise AssertionError("Nota do GitHub não documentou declarações verificadas")
            files = list(vault.rglob("*.md"))
            return (
                "# TRAMA 2.2 — Integração com código público da Academia\n\n"
                "- **Fonte de código:** `"+SOURCE_REPO+"`\n"
                "- **Commit exato:** `"+sha+"`\n"
                "- **Transcrições:** 3 roteiros SINTÉTICOS, não aulas reais.\n"
                "- **IA:** respostas determinísticas simuladas; nenhuma chamada externa.\n"
                "- **Importação:** processou Aula 031, depois 049, depois 050.\n"
                "- **Processamentos simulados:** "+str(len(teacher.analyzed))+" (um por aula).\n"
                "- **Arquivos de código indexados:** "+str(indexed.get("total_files"))+".\n"
                "- **Símbolos reais encontrados:** AuthService e CursosService.\n"
                "- **Vínculo:** Aula 050 acrescentou evidência revisável à dúvida da Aula 031.\n"
                "- **Notas Markdown criadas:** "+str(len(files))+".\n"
                "- **Integridade:** nenhuma fonte externa executada, sem API, sem vault pessoal.\n\n"
                "**O que isso NÃO comprova:** a fidelidade de uma transcrição "
                "real ou a qualidade do Gemini Free em resumos didáticos. "
                "Essas validações exigem material real autorizado.\n"
            )
        finally:
            app.close()


if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("Uso: python tools/qa_public_course.py pasta-do-repo-publico")
    summary=run(Path(sys.argv[1]))
    dest=Path("qa-artifacts/public-course-integration.md")
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(summary,encoding="utf-8")
    print(summary)
