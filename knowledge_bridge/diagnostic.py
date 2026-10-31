"""Small, explicit live AI diagnostic. Never publishes notes or leaks API keys.

Uses at most two API calls via the selected provider only. A successful HTTP response
is not proof that the model understood the lesson; human review remains necessary.
"""
from __future__ import annotations
from contextlib import closing

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .ai import FreeAIRouter
from .code_intel import find_code_line, match_lesson_to_repository, redact_sensitive
from .pipeline import Application

SAMPLE_TRANSCRIPT = (
    "[00:05] Hoje vamos revisar interval do RxJS. Ele emite valores periodicamente.\n"
    "[01:12] Quando fazemos subscribe começamos a receber as emissões.\n"
    "[02:20] Para não deixar a assinatura viva para sempre, usamos takeUntilDestroyed.\n"
    "[03:05] Na transcrição apareceu exaust map, mas talvez seja o operador exhaustMap.\n"
    "[04:08] Neste exemplo o exhaustMap evita iniciar uma segunda requisição enquanto a anterior está em execução.\n"
)
SAMPLE_EVIDENCE = [
    {"path": "exemplo/polling.ts", "line": 7, "concept": "interval",
     "snippet": "6: import { interval } from 'rxjs';\n7: const tick$ = interval(5000);"},
    {"path": "exemplo/polling.ts", "line": 9, "concept": "exhaustMap",
     "snippet": "8: tick$.pipe(\n9:   exhaustMap(() => http.get('/status')),\n10:   takeUntilDestroyed(destroyRef)"},
    {"path": "exemplo/polling.ts", "line": 10, "concept": "takeUntilDestroyed",
     "snippet": "9:   exhaustMap(() => http.get('/status')),\n10:   takeUntilDestroyed(destroyRef)"},
]


class MissingTestSources(ValueError):
    pass


def _read_real_sources(vault: Path) -> tuple[str, list[dict], dict]:
    """Read ONE lesson and relevant repository excerpts without changing the vault."""
    db = vault / ".base-conhecimento" / "estado.sqlite3"
    if not db.is_file():
        raise MissingTestSources("Importe uma transcrição e um repositório no TRAMA antes do teste real.")
    try:
        with closing(sqlite3.connect(f"file:{quote(db.as_posix())}?mode=ro", uri=True, timeout=3)) as con:
            con.row_factory = sqlite3.Row
            transcripts = con.execute(
                "SELECT label,stored_path FROM sources WHERE kind='transcript' ORDER BY label LIMIT 30"
            ).fetchall()
            repos = con.execute("SELECT name, payload FROM repositories ORDER BY name LIMIT 12").fetchall()
    except sqlite3.Error as exc:
        raise MissingTestSources("Não foi possível ler o catálogo do TRAMA. Reimporte os materiais.") from exc

    if not transcripts or not repos:
        raise MissingTestSources("Para testar as três camadas, importe ao menos uma transcrição e um GitHub antes.")
    base = vault.resolve()
    for src in transcripts:
        rel = src["stored_path"]
        if not isinstance(rel, str) or not rel:
            continue
        candidate = (base / rel).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file() or candidate.stat().st_size > 1_000_000:
            continue
        transcript = candidate.read_text(encoding="utf-8-sig", errors="replace")
        for row in repos:
            try:
                repo = json.loads(row["payload"])
            except (ValueError, TypeError):
                continue
            if not isinstance(repo, dict):
                continue
            evidence = match_lesson_to_repository(transcript, None, repo, cap=8)
            if evidence:
                return redact_sensitive(transcript[:11_000]), evidence, repo
    raise MissingTestSources(
        "Não encontrei conceitos em comum entre as transcrições e o código importado. "
        "Use o teste de demonstração ou importe uma aula e seu repositório correspondente."
    )


def _compact(value: object, max_chars: int = 700) -> str:
    if not isinstance(value, str):
        return ""
    return redact_sensitive(value.replace("\r", " ").strip())[:max_chars]


def run_ai_diagnostic(router: FreeAIRouter, mode: str, vault: Path | None = None) -> dict:
    """Make at most two requests: one summary and one evidence comparison.

    Does not publish or change Obsidian, and does not include source excerpts in report.
    """
    if mode not in {"demo", "real"}:
        raise ValueError("Modo de teste inválido")
    if mode == "real":
        if vault is None or not vault.is_dir():
            raise MissingTestSources("Conecte primeiro o cofre do Obsidian.")
        transcript, evidence, repo = _read_real_sources(vault)
    else:
        transcript = SAMPLE_TRANSCRIPT
        evidence = SAMPLE_EVIDENCE
        repo = {"evidence": evidence}

    # The diagnostic explicitly limits the number of requests independently of global settings.
    router.max_requests = min(router.max_requests, 2)
    summary = router.analyze(transcript, "Teste diagnóstico do TRAMA; dados de demonstração" if mode == "demo" else "Teste diagnóstico do TRAMA; aula real")
    validated_summary = Application._clean_result(summary.payload, transcript)
    comparison = router.compare(transcript, evidence, "Teste de relações entre aula, conhecimento e código")
    comparison_validated = Application._check_comparison(comparison.payload, transcript, repo)
    return {
        "ok": True,
        "mode": mode,
        "provider": summary.provider,
        "model": summary.model,
        "requests": router.attempts,
        "summary": _compact(validated_summary.get("resumo", ""), 900),
        "concepts": [_compact(x.get("nome", ""), 100) for x in validated_summary.get("conceitos", [])[:8]],
        "relations": [{
            "concept": _compact(x["conceito"], 100),
            "time": _compact(x["tempo"], 15),
            "source_file": _compact(x["path"], 180),
            "source_line": x["line"],
            "explanation": _compact(x["explicacao"], 400),
            "evolution": _compact(x["evolucao"], 400),
            "review": x["status"],
        } for x in comparison_validated["relacoes"][:8]],
        "suggested_corrections": [{
            "heard": _compact(x["ouvido"], 100),
            "suggestion": _compact(x["sugestao"], 100),
            "review": x["status"],
        } for x in comparison_validated["correcoes"][:5]],
        "invalid_references_discarded": max(0, len(comparison.payload.get("relacoes", [])) - len(comparison_validated["relacoes"])),
        "limitations": (
            "Resultado de demonstração; não mede qualidade nas suas aulas. "
            if mode == "demo" else "Trecho parcial de uma aula e evidências de um repositório; não representa todo o curso. "
        ) + "Uma resposta válida não comprova correção factual; revise a gravação e as linhas citadas.",
    }


def format_diagnostic_report(result: dict) -> str:
    """Shareable report without API key, full transcripts, snippets or machine paths."""
    lines = [
        "TRAMA — RELATÓRIO DE TESTE DE INTELIGÊNCIA ARTIFICIAL",
        f"Gerado em: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Modo: {'demonstração fictícia' if result['mode'] == 'demo' else 'materiais reais (sem fonte integral)'}",
        f"Provedor: {result['provider']}",
        f"Modelo: {result['model']}",
        f"Requisições: {result['requests']} (máximo: 2)",
        "Nenhuma nota do Obsidian foi modificada por este teste.",
        "",
        "RESUMO DA IA (revisão humana necessária)",
        result.get("summary", ""),
        "",
        "CONCEITOS RECONHECIDOS",
        *(f"- {x}" for x in result.get("concepts", [])),
        "",
        "RELAÇÕES COM CÓDIGO (âncoras verificadas localmente)",
    ]
    for rel in result.get("relations", []):
        lines.extend([f"- Conceito: {rel['concept']}",
                      f"  Evidência: {rel['source_file']}:{rel['source_line']} | Aula: {rel['time'] or 'horário não confirmado'}",
                      f"  Uso: {rel['explanation']}",
                      f"  Evolução: {rel['evolution']}", f"  Status: {rel['review']}"])
    lines.extend(["", "POSSÍVEIS ERROS DE TRANSCRIÇÃO (não confirmados)"])
    for item in result.get("suggested_corrections", []):
        lines.append(f"- {item['heard']} → {item['suggestion']} ({item['review']})")
    lines.extend(["", f"Referências de código descartadas: {result.get('invalid_references_discarded', 0)}",
                  "", "LIMITAÇÕES", result["limitations"],
                  "", "PRIVACIDADE", "Este relatório não inclui chave de API nem transcrição ou código-fonte integral.",
                  "Verifique o conteúdo antes de compartilhar: a IA pode mencionar informação privada no resumo.", ""])
    return "\n".join(lines)
