"""Live free-tier Gemini batch diagnostic. Does not access the Obsidian vault/database.

Run: python tools/teste_gemini.py --pasta testes/aulas --limite 40 --pausa 4 --saida testes/resultado
Reports contain course excerpts and must stay local.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knowledge_bridge import ai
from knowledge_bridge.ai import (AllProvidersFailed, BudgetStopped, FreeAIRouter,
                                 NoFreeProvider, ProviderError, read_env)
from knowledge_bridge.content import chunks, timed_lines
from knowledge_bridge.pipeline import Application

TOKEN_FIELDS = ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount")
CONTRACT_FIELDS = ("systemInstruction", "responseJsonSchema", "maxItems",
                   "enum", "thinkingConfig", "thinkingLevel")


def scrub(value, secrets):
    """Remove configured tokens from all persisted API responses and error bodies."""
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[SEGREDO-OCULTO]")
        return re.sub(r'(?i)((?:x-goog-api-key|authorization|api[_-]?key)\s*[:=]\s*)[^\s,;"\x27]+',
                      r'\1[SEGREDO-OCULTO]', value)
    if isinstance(value, dict):
        return {str(k): scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(item, secrets) for item in value]
    return value


def http_error_details(exc, secrets):
    """Read the upstream 400 body for field diagnosis, never exposing the API key."""
    underlying = getattr(exc, "__cause__", None)
    status = getattr(underlying, "code", None)
    if status is None:
        return {}
    try:
        raw = underlying.read(16384).decode("utf-8", "replace")[:12000]
    except Exception:
        raw = ""
    try:
        message = json.loads(raw)
    except ValueError:
        message = raw
    message = scrub(message, secrets)
    text = json.dumps(message, ensure_ascii=False) if isinstance(message, (dict, list)) else str(message)
    suspected = [name for name in CONTRACT_FIELDS if name.lower() in text.lower()]
    return {"http_status": status, "api_error": message,
            "campos_possivelmente_recusados":
                suspected or (["não identificado na resposta"] if status == 400 else [])}


@contextmanager
def capture_calls(calls, secrets):
    """Instrument the actual TRAMA transport without reimplementing AI analysis."""
    real_send = ai._send

    def observed(url, body, headers, provider):
        started = time.perf_counter()
        call = {"provider": provider, "response": None}
        calls.append(call)
        config = body.get("generationConfig", {}) if isinstance(body, dict) else {}
        schema = config.get("responseJsonSchema") or {}
        call["contrato_enviado"] = {
            "systemInstruction": "systemInstruction" in body,
            "responseJsonSchema": "responseJsonSchema" in config,
            "maxItems": '"maxItems"' in json.dumps(schema),
            "enum": '"enum"' in json.dumps(schema),
            "thinkingConfig_minimal": (config.get("thinkingConfig") or {}).get("thinkingLevel") == "minimal",
        }
        try:
            response = real_send(url, body, headers, provider)
            call["response"] = scrub(response, secrets)
            if isinstance(response, dict):
                candidates = response.get("candidates") or []
                first = candidates[0] if isinstance(candidates, list) and candidates else {}
                call["finishReason"] = first.get("finishReason") if isinstance(first, dict) else None
                call["usageMetadata"] = scrub(response.get("usageMetadata") or {}, secrets)
            return response
        except ProviderError as exc:
            call["erro"] = scrub(str(exc), secrets)
            call.update(http_error_details(exc, secrets))
            raise
        finally:
            call["tempo_segundos"] = round(time.perf_counter() - started, 3)

    with patch.object(ai, "_send", side_effect=observed):
        yield


def failure_kind(exc, calls):
    messages = " ".join(str(c.get("erro", "")) for c in calls) + " " + str(exc)
    upper = messages.upper()
    http = next((c.get("http_status") for c in calls if c.get("http_status")), None)
    if http == 429 or "429" in messages:
        # The official Gemini error can contain quotaId and quotaMetric, not
        # merely a human-readable message. Only infer scope when explicit.
        details = " ".join(
            json.dumps(c.get("api_error", ""), ensure_ascii=False) for c in calls
        ).lower()
        by_minute = bool(re.search(
            r"per[\s_-]*minute|requests?[/\s_-]*min(?:ute)?|tokens?[/\s_-]*min(?:ute)?|\b(?:rpm|tpm)\b",
            details,
        ))
        by_day = bool(re.search(
            r"per[\s_-]*day|\bdaily\b|requests?[/\s_-]*day|tokens?[/\s_-]*day|\b(?:rpd|tpd)\b|per[\s_-]*24[\s_-]*hours?",
            details,
        ))
        if by_minute and not by_day:
            return "COTA_429_POR_MINUTO"
        if by_day and not by_minute:
            return "COTA_429_DIARIA"
        return "COTA_429_INDETERMINADA"
    if http:
        return f"HTTP_{http}"
    if any(c.get("finishReason") == "MAX_TOKENS" for c in calls) or "MAX_TOKENS" in upper:
        return "MAX_TOKENS"
    if "BLOQUE" in upper or "SAFETY" in upper or "BLOCK" in upper:
        return "BLOQUEIO_SEGURANCA"
    if "JSON" in upper or "ESTRUTURAD" in upper:
        return "JSON_INVALIDO"
    if "429" in messages or "COTA" in upper or "QUOTA" in upper:
        return "COTA_429"
    if isinstance(exc, BudgetStopped):
        return "LIMITE_LOCAL"
    if "TIMEOUT" in upper or "CONEX" in upper or "TEMPO ESGOTADO" in upper:
        return "TIMEOUT_OU_CONEXAO"
    if isinstance(exc, NoFreeProvider):
        return "PROVEDOR_INDISPONIVEL"
    return type(exc).__name__


def inspect_result(raw, clean, transcript):
    real_times = {stamp for stamp, _ in timed_lines(transcript) if stamp != "sem horário"}
    rejected_times = 0
    for category in ("pessoas", "atividades", "ferramentas", "marcos", "conceitos"):
        rows = raw.get(category, [])
        if isinstance(rows, list):
            for item in rows:
                if isinstance(item, dict):
                    stamp = str(item.get("tempo") or "").strip("[]")
                    if stamp and stamp not in real_times:
                        rejected_times += 1
    empty = [name for name in ("resumo", "tipo_aula", "pessoas", "atividades",
             "ferramentas", "marcos", "conceitos", "exemplos", "duvidas", "nomes_a_conferir")
             if not raw.get(name)]
    to_review = clean.get("conceitos_a_conferir", [])
    return {"resumo": clean.get("resumo", ""),
            "caracteres_resumo": len(clean.get("resumo", "")),
            "conceitos_aceitos": len(clean.get("conceitos", [])),
            "conceitos_por_nome": sum(x.get("confianca") == "nome_literal" for x in clean.get("conceitos", [])),
            "conceitos_por_citacao": sum(x.get("confianca") == "citacao_literal" for x in clean.get("conceitos", [])),
            "nomes_conceitos": [x.get("nome", "") for x in clean.get("conceitos", [])],
            "conceitos_a_conferir": len(to_review),
            "nomes_a_conferir": [x.get("nome", "") for x in to_review],
            "a_conferir_com_citacao_literal": sum(bool(x.get("evidencia_literal")) for x in to_review),
            "timestamps_descartados": rejected_times, "campos_vazios": empty}


def report_markdown(report):
    entries = report["trechos"]
    lessons = defaultdict(list)
    for entry in entries:
        lessons[entry["aula"]].append(entry)
    failures = Counter(x["motivo"] for x in entries if not x["ok"])
    calls = [c for x in entries for c in x["chamadas"]]
    tokens = {field: sum(int(c.get("usageMetadata", {}).get(field) or 0) for c in calls)
              for field in TOKEN_FIELDS}
    first = calls[0] if calls else {}
    accepted = first.get("response") is not None
    lines = ["# TRAMA — diagnóstico Gemini real (dados privados)", "",
             "## 1. Resumo geral", "",
             f"- Executado em: {report['gerado_em']}",
             f"- Aulas: {len(lessons)}; trechos: {len(entries)}; sucessos: {sum(e['ok'] for e in entries)}; falhas: {sum(not e['ok'] for e in entries)}",
             f"- Chamadas usadas: {len(calls)} / {report['limite']}",
             f"- Pausa entre trechos: {report.get('pausa', 4)} segundos",
             f"- Tokens totais: prompt={tokens['promptTokenCount']}, resposta={tokens['candidatesTokenCount']}, raciocínio={tokens['thoughtsTokenCount']}",
             f"- Média de tokens de raciocínio: {round(tokens['thoughtsTokenCount'] / len(calls), 2) if calls else 0}",
             f"- Falhas por motivo: {json.dumps(dict(failures), ensure_ascii=False)}",
             f"- Primeira chamada: {'API aceitou o corpo enviado' if accepted else 'compatibilidade NÃO confirmada'}",
             f"- Campos do contrato: {json.dumps(first.get('contrato_enviado', {}), ensure_ascii=False)}", "",
             "## 2. Tabela por aula", "",
             "| Aula | Trechos | OK/falha | Aceitos | Por nome | Por citação | A conferir | Tamanho resumo | Chamadas (tentativas extras) |",
             "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for name, rows in lessons.items():
        ok = sum(x["ok"] for x in rows)
        accepted_concepts = sum(x.get("conceitos_aceitos", 0) for x in rows)
        accepted_name = sum(x.get("conceitos_por_nome", 0) for x in rows)
        accepted_quote = sum(x.get("conceitos_por_citacao", 0) for x in rows)
        review = sum(x.get("conceitos_a_conferir", 0) for x in rows)
        size = sum(x.get("caracteres_resumo", 0) for x in rows)
        calls_count = sum(x.get("tentativas", len(x.get("chamadas", []))) for x in rows)
        extra = sum(x.get("novas_tentativas", 0) for x in rows)
        lines.append(f"| {name} | {len(rows)} | {ok}/{len(rows)-ok} | {accepted_concepts} | {accepted_name} | {accepted_quote} | {review} | {size} | {calls_count} ({extra}) |")
    lines += ["", "## 3. Lista de falhas", "",
              "| Aula | Trecho | Motivo | finishReason | Tentativas | Detalhes |",
              "|---|---:|---|---|---:|---|"]
    for row in entries:
        if row["ok"]:
            continue
        error = str(row.get("erro", ""))[:300].replace("|", "/").replace("\n", " ")
        for c in row["chamadas"]:
            if c.get("http_status") == 429:
                error += " / API 429: " + str(c.get("api_error", ""))[:500].replace("|", "/").replace("\n", " ")
            if c.get("http_status") == 400:
                error += " / API 400: " + str(c.get("api_error", ""))[:500].replace("|", "/").replace("\n", " ")
                error += " / Campos possivelmente recusados: " + ", ".join(c.get("campos_possivelmente_recusados", []))
        lines.append(f"| {row['aula']} | {row['trecho']} | {row['motivo']} | {row.get('finishReason') or '-'} | {row.get('tentativas', len(row['chamadas']))} | {error} |")
    lines += ["", "## 4. Amostras", ""]
    count = 0
    for name, rows in lessons.items():
        good = next((x for x in rows if x["ok"]), None)
        if not good:
            continue
        lines += [f"### {name}", "", "**Resumo**", "", good["resumo"], "",
                  "**Conceitos aceitos:** " + ", ".join(good["nomes_conceitos"]),
                  "", "**A conferir:** " + ", ".join(good["nomes_a_conferir"]), ""]
        count += 1
        if count == 3:
            break
    lines += ["", "Aviso: os arquivos gerados contêm respostas reais. Não envie ao GitHub.", ""]
    return "\n".join(lines)


def run(pasta: Path, saida: Path, limite: int = 40, pausa: float = 4) -> dict:
    pasta = Path(pasta).expanduser().resolve()
    saida = Path(saida).expanduser().resolve()
    if not 1 <= limite <= 100:
        raise ValueError("O limite deve ficar entre 1 e 100.")
    if not math.isfinite(pausa) or pausa < 0:
        raise ValueError("A pausa deve ser um número finito de segundos, maior ou igual a zero.")
    if not pasta.is_dir() or pasta.is_symlink():
        raise ValueError("Pasta de aulas inexistente ou inválida.")
    if saida == pasta or saida.is_relative_to(pasta):
        raise ValueError("A pasta de saída precisa estar separada da entrada.")
    sources = sorted(p for p in pasta.glob("*.txt") if p.is_file() and not p.is_symlink())
    if not sources:
        raise ValueError("Nenhum .txt foi encontrado na pasta.")
    settings = read_env(ROOT / "config.env")
    if os.environ.get("GEMINI_API_KEY"):
        settings["GEMINI_API_KEY"] = os.environ["GEMINI_API_KEY"]
    if not settings.get("GEMINI_API_KEY"):
        raise ValueError(
            "Chave Gemini não encontrada. O script não lê a chave salva no app (protegida pelo Windows). "
            "No PowerShell, execute:\n"
            "$env:GEMINI_API_KEY = 'SUA_CHAVE'\n"
            '$env:FREE_TIER_CONFIRMED = "YES"'
        )
    if settings.get("FREE_TIER_CONFIRMED") != "YES":
        raise ValueError("Confirme FREE_TIER_CONFIRMED=YES e use um projeto sem faturamento.")
    settings["FREE_PROVIDER_ORDER"] = "gemini"
    settings["MAX_REQUESTS_PER_RUN"] = str(limite)
    router = FreeAIRouter(settings)
    secrets = [v for k, v in settings.items() if isinstance(v, str) and
               len(v) >= 8 and ("KEY" in k.upper() or "TOKEN" in k.upper())]
    report = {"gerado_em": datetime.now(timezone.utc).isoformat(),
              "limite": limite, "pausa": pausa, "trechos": []}
    stop = False
    for source in sources:
        if stop:
            break
        if source.stat().st_size > 20 * 1024 * 1024:
            raise ValueError(f"Arquivo com mais de 20 MB: {source.name}")
        raw = source.read_text(encoding="utf-8-sig", errors="replace")
        for number, piece in enumerate(chunks(raw), 1):
            if router.attempts >= router.max_requests or not router.active():
                stop = True
                break
            # Space successive chunks (including across lesson files) on the Free tier.
            # Never delay the first chunk or a batch already stopped by the quota.
            if report["trechos"] and pausa:
                time.sleep(pausa)
            calls = []
            entry = {"aula": source.stem, "trecho": number,
                     "caracteres_trecho": len(piece), "ok": False, "chamadas": calls}
            started = time.perf_counter()
            try:
                with capture_calls(calls, secrets):
                    result = router.analyze(piece, f"Teste isolado da aula {source.stem}; trecho {number}")
                clean = Application._clean_result(result.payload, piece)
                entry.update(inspect_result(result.payload, clean, piece))
                entry["ok"] = True
                entry["motivo"] = "SUCESSO"
            except (AllProvidersFailed, NoFreeProvider, BudgetStopped, ProviderError, ValueError) as exc:
                entry["motivo"] = failure_kind(exc, calls)
                entry["erro"] = scrub(str(exc), secrets)
                if isinstance(exc, (NoFreeProvider, BudgetStopped)):
                    stop = True
            except Exception as exc:
                entry["motivo"] = "ERRO_LOCAL_" + type(exc).__name__
                entry["erro"] = scrub(str(exc)[:350], secrets)
            finally:
                entry["tempo_total_segundos"] = round(time.perf_counter() - started, 3)
                entry["tentativas"] = len(calls)
                entry["novas_tentativas"] = max(0, len(calls) - 1)
                entry["finishReason"] = next((c.get("finishReason") for c in reversed(calls)
                                              if c.get("finishReason")), None)
                report["trechos"].append(entry)
                target = saida / "respostas" / (re.sub(r"[^a-zA-Z0-9._-]", "_", source.stem)[:120]
                                              + f"-trecho-{number}.json")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(scrub({"aula": source.stem, "trecho": number,
                                                     "chamadas": calls}, secrets),
                                             ensure_ascii=False, indent=2), encoding="utf-8")
            if stop:
                break
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "relatorio_teste.md").write_text(report_markdown(report), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Diagnóstico Gemini gratuito sem abrir TRAMA ou Obsidian.")
    parser.add_argument("--pasta", type=Path, default=Path("testes/aulas"))
    parser.add_argument("--limite", type=int, default=40, help="Máximo de chamadas ao Gemini (1 a 100).")
    parser.add_argument("--pausa", type=float, default=4, metavar="SEGUNDOS",
                        help="Intervalo entre trechos, em segundos (padrão: 4).")
    parser.add_argument("--saida", type=Path, default=Path("testes/resultado"))
    args = parser.parse_args()
    try:
        result = run(args.pasta, args.saida, args.limite, args.pausa)
    except (ValueError, OSError) as exc:
        print(f"Teste não iniciado: {str(exc)[:220]}", file=sys.stderr)
        return 2
    print(f"Trechos tentados: {len(result['trechos'])}. Relatório: {args.saida / 'relatorio_teste.md'}")
    return 0 if all(x["ok"] for x in result["trechos"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
