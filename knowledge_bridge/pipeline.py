"""Orquestração incremental, sem dependência de APIs pagas."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import os
from pathlib import Path
from urllib.parse import urlparse

from .ai import BudgetStopped, FreeAIRouter, NoFreeProvider, read_env
from .content import chunks, file_hash, lesson_identity, slug, concept_slug, timed_lines
from .code_intel import index_repository, match_lesson_to_repository, find_code_line, concept_from_text
from .publishing import Publisher
from .store import Store
from .memory_atlas import related_prior, norm, literal_technical_mention
from .classroom import save_classroom_record

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm"}
TEXT_EXTS = {".txt", ".md"}
MATERIAL_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".docx"}
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}


class Application:
    def __init__(self, vault: Path, config: Path | None = None, log=print):
        self.store = Store(vault)
        self.publisher = Publisher(self.store)
        self.env = read_env(config or Path(__file__).resolve().parent.parent / "config.env")
        self.ai = FreeAIRouter(self.env)
        self.log = log

    def close(self):
        self.store.close()

    def add_file(self, path: Path):
        path = path.expanduser()
        if path.is_symlink():
            raise ValueError("Links simbólicos não são importados por segurança.")
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        ext = path.suffix.lower()
        kind = "transcript" if ext in TEXT_EXTS else "video" if ext in VIDEO_EXTS else "material" if ext in MATERIAL_EXTS else None
        if kind == "video":
            raise ValueError("O TRAMA não armazena vídeos. Cadastre o título e o link da gravação em Aulas → Contexto +.")
        if not kind:
            self.log(f"Ignorado (formato ainda não aceito): {path.name}")
            return False
        size = path.stat().st_size
        if kind == "transcript" and size > 20 * 1024 * 1024:
            raise ValueError("Transcrição acima de 20 MB; revise o arquivo antes de importar.")
        if kind == "material" and size > 60 * 1024 * 1024:
            raise ValueError("Material acima de 60 MB; revise o arquivo antes de importar.")
        if kind == "video" and size > 8 * 1024 * 1024 * 1024:
            raise ValueError("Vídeo acima de 8 GB; revise o arquivo antes de importar.")
        if size > shutil.disk_usage(self.store.vault).free - 200 * 1024 * 1024:
            raise ValueError("Espaço insuficiente para copiar o material e manter uma reserva de 200 MB.")
        # Evitar reimportação das cópias já depositadas no cofre.
        if path.is_relative_to(self.store.vault):
            self.log(f"Ignorado (arquivo interno do Obsidian): {path.name}")
            return False
        source_id = hashlib.sha256((str(path).casefold() + kind).encode()).hexdigest()[:24]
        lesson, video = lesson_identity(path.stem)
        digest = file_hash(path)
        existing = self.store.matching_digest(kind, digest)
        if (existing and existing["id"] != source_id
                and existing["lesson"] == lesson and (existing["video"] or "") == (video or "")):
            self.log(f"Duplicata da mesma aula/gravação, já cadastrada como {existing['label']}: {path.name}")
            return False
        # Aulas distintas podem repetir literalmente o conteúdo; preservar
        # os registros individuais enquanto compartilham o anexo físico.
        stored = self.publisher.attachment(path, kind)
        changed = self.store.upsert_source(dict(id=source_id, original_path=str(path), kind=kind,
                                                digest=digest,label=path.name,lesson=lesson,video=video,stored_path=stored))
        self.log(f"{'Novo/alterado' if changed else 'Já cadastrado'}: {path.name} ({kind})")
        return changed

    def attach_classroom_material(self, lesson: str, path: Path) -> bool:
        """Vincula um print/PDF/documento a uma aula explícita, sem inferir seu conteúdo."""
        from .classroom import lesson_number
        lesson = lesson_number(lesson)
        path = path.expanduser()
        if path.is_symlink():
            raise ValueError("Links simbólicos não são aceitos.")
        path = path.resolve()
        if not path.is_file() or path.is_relative_to(self.store.vault):
            raise ValueError("Selecione um arquivo original fora do cofre.")
        if path.suffix.lower() not in MATERIAL_EXTS:
            raise ValueError("Use um print (.png/.jpg/.webp), PDF ou documento Word.")
        size = path.stat().st_size
        if size > 60*1024*1024 or size > shutil.disk_usage(self.store.vault).free - 200*1024*1024:
            raise ValueError("Material muito grande ou espaço insuficiente.")
        digest = file_hash(path)
        source_id = hashlib.sha256(("classroom-material:" + lesson + ":" + str(path).casefold()).encode()).hexdigest()[:24]
        stored = self.publisher.attachment(path, "material")
        return self.store.upsert_source(dict(
            id=source_id, original_path=str(path), kind="material", digest=digest,
            label=path.name, lesson=lesson, video="", stored_path=stored))

    def register_classroom(self, data: dict) -> dict:
        """Registra uma aula do Classroom mesmo quando não há vídeo ou código."""
        stored, digest, lesson = save_classroom_record(self.store.vault, data)
        source_id = hashlib.sha256(("classroom:" + lesson).encode()).hexdigest()[:24]
        changed = self.store.upsert_source({
            "id": source_id, "original_path": "classroom:" + lesson,
            "kind": "classroom", "digest": digest,
            "label": f"Contexto Classroom {lesson}", "lesson": lesson,
            "video": "", "stored_path": stored,
        })
        self.publisher.rebuild()
        return {"ok": True, "aula": lesson, "changed": changed}

    def scan(self, inbox: Path):
        inbox = inbox.expanduser().resolve()
        if not inbox.is_dir():
            raise FileNotFoundError(f"Pasta de entrada não encontrada: {inbox}")
        if inbox == self.store.vault or self.store.vault.is_relative_to(inbox):
            raise ValueError("Escolha uma pasta de entrada separada do cofre, para não importar o próprio Obsidian.")
        count = 0
        for path in sorted(inbox.rglob("*")):
            if path.is_file() and not path.is_symlink() and not any(x in SKIP_DIRS for x in path.parts):
                if path.suffix.lower() in VIDEO_EXTS:
                    self.log(f"Vídeo não copiado: {path.name}. Cadastre seu link em Aulas → Contexto +.")
                    continue
                if path.suffix.lower() in TEXT_EXTS | MATERIAL_EXTS:
                    count += int(self.add_file(path))
        self.publisher.rebuild()
        self.log(f"Importação concluída. Novos ou alterados: {count}.")
        return count

    def _verified_transcript(self, src) -> str:
        """Refuse missing or modified cached sources before sending content to AI."""
        # Check the STORED path before resolving it: Path.resolve() follows
        # symbolic links, so checking file.is_symlink() afterwards is ineffective.
        stored = self.store.vault / (src["stored_path"] or "")
        file = stored.resolve()
        if (stored.is_symlink() or not file.is_relative_to(self.store.vault)
                or not file.is_file()):
            raise ValueError("Fonte original ausente ou caminho inseguro: " + src["label"])
        if file_hash(file) != src["digest"]:
            self.store.update_status(src["id"], "NEEDS_REVIEW")
            raise ValueError("Transcrição armazenada foi alterada ou corrompida: " +
                             src["label"] + ". Reimporte a fonte original antes de processar.")
        return file.read_text(encoding="utf-8-sig", errors="replace")

    @staticmethod
    def _clean_result(payload: dict, raw_text: str) -> dict:
        """Limita resultados da IA e valida referências temporais reais."""
        if not isinstance(payload, dict):
            payload = {}
        real_times = {t for t, _ in timed_lines(raw_text)}
        def safe(value, size):
            return str(value)[:size].strip() if isinstance(value, (str, int, float)) else ""
        def entries(key, fields, cap):
            result = []
            for entry in payload.get(key, []) if isinstance(payload.get(key), list) else []:
                if not isinstance(entry, dict):
                    continue
                obj = {name: safe(entry.get(name), limit) for name, limit in fields.items()}
                stamp = safe(entry.get("tempo"), 20).strip("[]")
                obj["tempo"] = stamp if stamp in real_times else ""
                if any(obj.get(k) for k in fields):
                    result.append(obj)
                if len(result) >= cap:
                    break
            return result
        kinds = {"apresentacao", "tecnica", "organizacional", "atividade", "mista", "indefinida"}
        kind = safe(payload.get("tipo_aula"), 24)
        clean = {
            "resumo": safe(payload.get("resumo"), 2200),
            "tipo_aula": kind if kind in kinds else "indefinida",
            "pessoas": entries("pessoas", {"nome": 130, "papel": 140, "informacao": 420}, 8),
            "atividades": entries("atividades", {"descricao": 380}, 8),
            "ferramentas": entries("ferramentas", {"nome": 110, "contexto": 360}, 8),
            "marcos": entries("marcos", {"descricao": 420}, 8),
            "conceitos": entries("conceitos", {"nome": 90, "explicacao": 700}, 12),
            "exemplos": [safe(x, 350) for x in payload.get("exemplos", []) if isinstance(x, str)][:7],
            "duvidas": [safe(x, 350) for x in payload.get("duvidas", []) if isinstance(x, str)][:7],
            "nomes_a_conferir": [safe(x, 180) for x in payload.get("nomes_a_conferir", [])
                                 if isinstance(x, str)][:7],
        }
        # A provider can put a spoken personal name in multiple JSON fields.
        # Resolve direct category conflicts deterministically rather than
        # publishing a name as a programming concept or technical question.
        def normalized_name(value):
            return re.sub(r"\s+", " ", str(value).casefold().strip(' \t\r\n.,:;!?"“”')).strip()
        known_names = {
            normalized_name(value) for value in clean["nomes_a_conferir"]
        } | {
            normalized_name(person.get("nome", ""))
            for person in clean["pessoas"]
        }
        known_names.discard("")
        if known_names:
            clean["conceitos"] = [
                concept for concept in clean["conceitos"]
                if normalized_name(concept.get("nome", "")) not in known_names
            ]
            clean["duvidas"] = [
                doubt for doubt in clean["duvidas"]
                if normalized_name(doubt) not in known_names
            ]
        # A model's concept label is not an observed lesson fact unless its
        # name appears literally in the ORIGINAL transcript. Names suggested
        # from a code repository may be useful hypotheses, but must never
        # turn into confirmed concept pages by mere model assertion.
        grounded=[]
        unverified=[]
        for concept in clean["conceitos"]:
            label=concept.get("nome","").strip()
            observed=literal_technical_mention(label,raw_text)
            if observed:
                # A literal abbreviation confirms a mention, NOT the model's
                # explanation or a claim that the learner mastered the topic.
                grounded.append(concept)
            else:
                unverified.append({
                    "nome":label,
                    "motivo":"Nome ou abreviação não encontrado na transcrição original.",
                })
        clean["conceitos"]=grounded
        clean["conceitos_a_conferir"]=unverified[:12]
        # A shallow or empty summary is not silently promoted as complete
        # knowledge. Do not spend a second paid/free call automatically:
        # preserve the original and mark the deficiency for later review.
        review=[]
        if len(raw_text.strip())>=1600 and len(clean["resumo"])<160:
            review.append("Resumo curto para o volume da transcrição; revisar fidelidade e detalhes.")
        if len(raw_text.strip())>=400 and not clean["resumo"]:
            review.append("A IA não forneceu síntese; consultar a transcrição original.")
        clean["qualidade_pendente"]=review
        return clean

    def process(self, lesson_filter: str | None = None, force: bool = False):
        sources = self.store.sources("transcript")
        if lesson_filter is not None:
            sources = [s for s in sources if s["lesson"] == lesson_filter]
        if not sources:
            self.log("Nenhuma transcrição cadastrada. Adicione .txt ou .md à pasta de entrada.")
            return {"aulas":0, "conceitos":0, "projetos":len(self.store.repositories())}
        for src in sources:
            # Validate even already-cached analyses before reusing their notes.
            text = self._verified_transcript(src)
            # Só reprocessa se o conteúdo mudou ou a nota ainda está pendente.
            context_rows = self.publisher._context_rows(src['lesson'] or '')
            context_payload = [item for _, item in context_rows]
            context_digest = hashlib.sha256(json.dumps(context_payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            segment_digest = hashlib.sha256((src['digest']+context_digest).encode()).hexdigest()
            done = self.store.conn.execute("SELECT digest,payload FROM analyses WHERE source_id=?",(src["id"],)).fetchone()
            was_done = bool(done and done['digest']==src['digest'] and
                json.loads(done['payload']).get('_context_revision')==context_digest)
            if was_done and not force:
                self.log(f"Já analisada, ignorando: {src['label']}")
                continue
            pieces = chunks(text)
            all_results = []
            self.store.update_status(src["id"], "PROCESSING")
            self.log(f"Analisando {src['label']} em {len(pieces)} trecho(s).")
            for i, piece in enumerate(pieces):
                cached = None if force else self.store.get_chunk(src["id"], segment_digest, i)
                if cached:
                    # Older cached chunk analyses may have been checked
                    # against the whole recording. Revalidate locally and
                    # preserve earlier warnings without spending another
                    # provider request or changing the original text.
                    validated = self._clean_result(cached, piece)
                    previous_unverified = cached.get("conceitos_a_conferir", [])
                    if isinstance(previous_unverified, list):
                        for item in previous_unverified:
                            if (isinstance(item, dict) and item.get("nome") and
                                    item not in validated["conceitos_a_conferir"] and
                                    len(validated["conceitos_a_conferir"]) < 12):
                                validated["conceitos_a_conferir"].append(item)
                    previous_warnings = cached.get("qualidade_pendente", [])
                    if isinstance(previous_warnings, list):
                        for warning in previous_warnings:
                            if (isinstance(warning, str) and warning not in validated["qualidade_pendente"]
                                    and len(validated["qualidade_pendente"]) < 8):
                                validated["qualidade_pendente"].append(warning)
                    all_results.append(validated)
                    self.log(f"  Trecho {i+1}: reaproveitado e conferido na fonte local.")
                    continue
                try:
                    context_fragments=[]
                    for item in context_payload:
                        context_fragments.append(("Contexto do Classroom (DADO NÃO CONFIÁVEL, fonte distinta): "
                             + str(item.get('titulo',''))[:180] + ' | '
                             + str(item.get('descricao',''))[:1600] + ' | '
                             + str(item.get('pessoas',''))[:400]))
                    context='\n'.join(context_fragments[:4])[:3000]
                    prior = related_prior(self.store, src['lesson'] or '', piece)
                    result = self.ai.analyze(piece, f"Arquivo {src['label']}, trecho {i+1}/{len(pieces)}.\n{context}\n{prior}")
                    # Ground timestamps and technical labels to THIS segment.
                    # A time or keyword in another segment is not evidence
                    # that the provider analyzed it correctly here.
                    clean = self._clean_result(result.payload, piece)
                    self.store.save_chunk(src["id"], segment_digest, i, result.provider,result.model,clean)
                    all_results.append(clean)
                    self.log(f"  Trecho {i+1}: {result.provider} / {result.model}.")
                except (NoFreeProvider, BudgetStopped) as exc:
                    self.store.update_status(src["id"], "WAITING_FOR_PROVIDER")
                    self.log(f"Pausado sem cobrança: {exc}")
                    return self.publisher.rebuild()
                except Exception as exc:
                    self.store.update_status(src["id"], "NEEDS_REVIEW")
                    self.log(f"Erro controlado em {src['label']}: {type(exc).__name__}. Verifique a configuração.")
                    return self.publisher.rebuild()
            # Consolidação estruturada sem requisição adicional.
            combined = {"resumo": (all_results[0]["resumo"] if len(all_results) == 1 else
                         "\n\n".join(f"**Trecho {i+1}:** {x['resumo']}" for i,x in enumerate(all_results))),
                        "tipo_aula": "indefinida", "pessoas": [], "atividades": [],
                        "ferramentas": [], "marcos": [], "conceitos": [],
                        "exemplos": [], "duvidas": [], "nomes_a_conferir": [],
                        "conceitos_a_conferir": []}
            # Preserve different explanations/timestamps from distinct parts of
            # the same recording. A concept may be introduced and then applied.
            known = set()
            for result in all_results:
                for item in result.get("conceitos", []):
                    k = (concept_slug(item["nome"]), item.get("tempo", ""),
                         item.get("explicacao", "").strip().casefold())
                    if k not in known:
                        combined["conceitos"].append(item)
                        known.add(k)
                if result.get("tipo_aula") and result["tipo_aula"] != "indefinida":
                    if combined["tipo_aula"] not in ("indefinida", result["tipo_aula"]):
                        combined["tipo_aula"] = "mista"
                    else:
                        combined["tipo_aula"] = result["tipo_aula"]
                for category in ("pessoas", "atividades", "ferramentas", "marcos"):
                    for item in result.get(category, []):
                        # Dedup keeps different evidence timestamps if substantive text differs.
                        if item not in combined[category]:
                            combined[category].append(item)
                combined["exemplos"].extend(result.get("exemplos", []))
                combined["duvidas"].extend(result.get("duvidas", []))
                combined["nomes_a_conferir"].extend(result.get("nomes_a_conferir", []))
                for caution in result.get("conceitos_a_conferir", []):
                    if caution not in combined["conceitos_a_conferir"]:
                        combined["conceitos_a_conferir"].append(caution)
            combined['_context_revision']=context_digest
            # Preserve warnings from each analyzed segment for the published note.
            combined['qualidade_pendente']=list(dict.fromkeys(
                warning for part in all_results for warning in
                part.get('qualidade_pendente',[]) if isinstance(warning,str)))[:8]
            meta = self.store.conn.execute("SELECT provider,model FROM chunks WHERE source_id=? AND digest=? ORDER BY segment LIMIT 1",
                                           (src["id"],segment_digest)).fetchone()
            self.store.save_analysis(src["id"], src["digest"],meta["provider"] if meta else "unknown",
                                     meta["model"] if meta else "unknown", combined)
            self.store.update_status(src["id"], "PUBLISHED")
            self.log(f"Concluída: {src['label']}")
            # SQLite analysis and status already committed after each lesson.
            # One final rebuild avoids O(n²) Markdown rewrites for large batches.
            # If interrupted, rebuilding on the next run recovers saved results.
        # Cross-source comparison is separate from transcription summaries,
        # cached by transcript digest + commit SHA, and opt-in via process().
        # A single-lesson refresh must not silently spend more API calls on
        # unrelated repositories and lessons.
        if lesson_filter is None:
            self.enrich_context()
        return self.publisher.rebuild()

    @staticmethod
    def _check_comparison(payload: dict, transcript: str, repository: dict) -> dict:
        """Discard fabricated source paths/lines/timestamps. Keep hypotheses as hypotheses."""
        valid_times={t for t,_ in timed_lines(transcript)}
        observed_concepts = concept_from_text(transcript)
        indexed = [item for item in (
            *repository.get("evidence", []), *repository.get("symbols", []))
            if isinstance(item, dict)]
        indexed_concepts = {str(item.get("concept", "")) for item in indexed}

        def code_supports(label: str, path: str = "", line: int = 0,
                          require_lecture: bool = False) -> bool:
            """A reference to one valid line is not proof of a DIFFERENT term.

            When a line includes several indexed concepts, any matching one
            suffices. A completely unrelated label must be discarded, even
            when the model cited a valid path/line of some other concept.
            """
            if not label.strip():
                return False
            candidates = [item for item in indexed if
                          (not path or item.get("path") == path) and
                          (not line or item.get("line") == line)]
            model_terms = concept_from_text(label)
            for item in candidates:
                term = str(item.get("concept", "")).strip()
                if term in model_terms and (
                        not require_lecture or term in observed_concepts):
                    return True
                # Arbitrary actual declaration names cannot use the
                # predefined alias table; require literal token boundaries.
                symbol = str(item.get("name", "")).strip()
                if (len(symbol) >= 4 and
                        re.search(r"(?<![A-Za-z0-9_])" + re.escape(symbol) +
                                  r"(?![A-Za-z0-9_])", label, re.I) and
                        (not require_lecture or literal_technical_mention(symbol, transcript))):
                    return True
            return False

        out={"resumo":str(payload.get("resumo", ""))[:1000],
             "relacoes":[],"correcoes":[],"novidades":[]}
        for row in payload.get("relacoes",[])[:8]:
            if not isinstance(row,dict):continue
            path=str(row.get('path',''))
            try:line=int(row.get('line',0))
            except (ValueError,TypeError):continue
            label=str(row.get('conceito',''))[:90]
            if not find_code_line(repository,path,line):continue
            if not code_supports(label,path,line,require_lecture=True):continue
            stamp=str(row.get('tempo','')).strip('[]')
            out['relacoes'].append({"conceito":label,
                 "tempo":stamp if stamp in valid_times else "", "path":path,"line":line,
                 "explicacao":str(row.get('explicacao',''))[:450],
                 "evolucao":str(row.get('evolucao',''))[:450], "status":"SUGESTÃO — verificar fontes"})
        for row in payload.get("correcoes",[])[:5]:
            if not isinstance(row,dict):continue
            heard=str(row.get('ouvido','')).strip()[:130]
            path=str(row.get('path',''))
            try:line=int(row.get('line',0))
            except (ValueError,TypeError):continue
            if not heard or heard.casefold() not in transcript.casefold():continue
            if not find_code_line(repository,path,line):continue
            if not code_supports(str(row.get("sugestao",""))[:100],path,line):continue
            stamp=str(row.get('tempo','')).strip('[]')
            out['correcoes'].append({"ouvido":heard,"sugestao":str(row.get('sugestao',''))[:100],
                "tempo":stamp if stamp in valid_times else "", "path":path,"line":line,
                "justificativa":str(row.get('justificativa',''))[:350],
                "status":"HIPÓTESE — revisão humana necessária"})
        for row in payload.get('novidades',[])[:5]:
            if not isinstance(row,dict):continue
            label=str(row.get('conceito',''))[:100]
            # Novelty is a hypothesis grounded in actual code or lecture,
            # not a free-standing invented model label.
            if not (code_supports(label) or
                    literal_technical_mention(label,transcript)):
                continue
            stamp=str(row.get('tempo','')).strip('[]')
            out['novidades'].append({"conceito":label,
                "tempo":stamp if stamp in valid_times else "",
                "explicacao":str(row.get('explicacao',''))[:350]})
        return out

    def enrich_context(self):
        """Optional AI review of candidate links, incremental and free-tier-only."""
        for src in self.store.sources('transcript'):
            analysis=self.store.analysis(src['id'],src['digest'])
            if not analysis:continue  # no externally generated claims without prior summary
            transcript=self._verified_transcript(src)
            for repo in self.store.repositories():
                payload=json.loads(repo['payload'])
                matched=match_lesson_to_repository(transcript,analysis,payload,cap=10)
                if not matched:continue
                if self.store.connection(src['id'],src['digest'],repo['url'],repo['sha']):continue
                try:
                    answer=self.ai.compare(transcript,matched,
                        f"Aula: {src['label']}; projeto: {repo['name']}; commit: {repo['sha'][:12]}.")
                    checked=self._check_comparison(answer.payload,transcript,payload)
                    self.store.save_connection(src['id'],src['digest'],repo['url'],repo['sha'],
                                               answer.provider,answer.model,checked)
                    self.log(f"Vínculo analisado: {src['label']} ↔ {repo['name']}")
                except (NoFreeProvider,BudgetStopped):
                    self.log('Comparações pendentes por cota/configuração: dados locais preservados.')
                    return
                except Exception as exc:
                    self.log(f'Comparação pendente: {src["label"]} / {repo["name"]} ({type(exc).__name__})')
                    continue

    def add_repo(self, url_or_dir: str):
        """Lê repositório público ou local; nunca faz commit/push/staging."""
        source = url_or_dir.strip()
        local = Path(source).expanduser()
        if local.is_dir():
            repo = local.resolve()
            source_id = str(repo)
        else:
            # Sem URL arbitrária: somente HTTPS público do GitHub.
            if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?", source):
                raise ValueError("Informe pasta Git local ou URL HTTPS pública de repositório GitHub.")
            owner, name = source.removesuffix("/").removesuffix(".git").split("/")[-2:]
            source_id = f"https://github.com/{owner}/{name}"
            checkout_dir = self.store.vault / ".base-conhecimento" / "repos" / f"{slug(owner)}-{slug(name)}"
            checkout_dir.parent.mkdir(parents=True,exist_ok=True)
            if not checkout_dir.exists():
                self.log("Obtendo repositório público (pode levar alguns instantes)...")
                self._git(["clone", "--depth", "80", "--single-branch", source_id, str(checkout_dir)])
            else:
                self._git(["-C",str(checkout_dir),"pull","--ff-only"])
            repo = checkout_dir
        sha = self._git(["-C",str(repo),"rev-parse","HEAD"]).strip()
        previous = self.store.conn.execute("SELECT sha,payload FROM repositories WHERE url=?",(source_id,)).fetchone()
        if previous and previous["sha"] == sha and "evidence" in json.loads(previous["payload"]):
            self.log("Repositório inalterado, nada a reprocessar.")
            return False
        # Git metadata is evidence of shared work, not proof of who wrote a method.
        history_text = self._git(["-C", str(repo), "log", "-n", "80", "--date=short",
                                  "--pretty=format:%h%x1f%an%x1f%ae%x1f%ad%x1f%s%x1e"])
        history=[]
        for rec in history_text.strip("\x1e\n").split("\x1e"):
            parts=rec.strip().split("\x1f")
            if len(parts)==5:
                short_sha,author,email,day,subject=parts
                history.append({"sha":short_sha[:12], "author":author[:90],
                                "author_email":email[:120], "date":day[:12], "subject":subject[:180]})
        paths = self._git(["-C", str(repo), "ls-files"]).splitlines()
        payload=index_repository(repo, paths, history)
        # compatibility with previous views and notes
        payload["signals"]=[{"term": e["concept"],"path": e["path"],"line":e["line"]}
                            for e in payload["evidence"]]
        self.store.save_repo(source_id,repo.name,sha,payload,"INDEXED")
        self.publisher.rebuild()
        self.log(f"Projeto indexado: {repo.name} ({len(payload['files'])} arquivos relevantes, commit {sha[:9]}).")
        return True

    @staticmethod
    def _git(args: list[str]) -> str:
        try:
            env = os.environ.copy()
            # Não aceitar prompts por credenciais e ignorar filtros/hooks configurados
            # globalmente. Nunca executar scripts do repositório importado.
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            env["GIT_CONFIG_GLOBAL"] = os.devnull
            sandbox_opts = ["-c", "core.hooksPath=" + str(Path(os.devnull)),
                            "-c", "protocol.ext.allow=never",
                            "-c", "protocol.file.allow=never",
                            "-c", "credential.helper="]
            run = subprocess.run(["git", *sandbox_opts, *args], capture_output=True,
                                 text=True, timeout=180, check=False, encoding="utf-8",
                                 errors="replace", env=env,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Git indisponível ou operação demorou demais") from exc
        if run.returncode:
            raise RuntimeError("Git falhou: " + run.stderr[:400])
        return run.stdout

    def stats(self):
        states = {}
        for src in self.store.sources():
            states[src["status"]] = states.get(src["status"],0) + 1
        return states
