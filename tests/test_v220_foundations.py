"""Regressões da base 2.2.0: restauração real, longa e não destrutiva.

Usa somente fixtures artificiais, sem acessar o cofre real do usuário,
GitHub, credenciais ou serviços de IA.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
import zipfile
from pathlib import Path

from knowledge_bridge.recovery import (
    MANIFEST, _filesystem_path, create_backup, restore_backup,
)


class PreviewIsolationTests(unittest.TestCase):
    def test_preview_marker_selects_a_separate_data_namespace(self):
        from knowledge_bridge.gui_legacy import _storage_namespace
        with tempfile.TemporaryDirectory(prefix="trama-v220-preview-isolation-") as folder:
            root=Path(folder)
            (root/"assets").mkdir()
            self.assertEqual(_storage_namespace(root),"TRAMA")
            (root/"assets"/"trama-preview.marker").write_text("TRAMA_PREVIEW_ISOLATED_V1",
                                                           encoding="utf-8")
            self.assertEqual(_storage_namespace(root),"TRAMA-Preview")
            self.assertFalse((root/"assets"/"trama-stable.marker").exists())


class ObsidianLessonPublicationQualityTests(unittest.TestCase):
    def test_overview_does_not_silently_cut_summary_and_projects_show_classes(self):
        from knowledge_bridge.pipeline import Application

        with tempfile.TemporaryDirectory(prefix="trama-v220-quality-publication-") as folder:
            base=Path(folder)
            app=Application(base/"Obsidian",base/"unused.env",log=lambda *_:None)
            try:
                source=base/"Aula-012-V01.txt"
                source.write_text(
                    "[0:01] O CertificateService faz parte do exemplo da aula. "
                    "A interface e o serviço são discutidos no contexto do projeto.",
                    encoding="utf-8"
                )
                self.assertTrue(app.add_file(source))
                registered=next(row for row in app.store.sources("transcript")
                                if row["label"]==source.name)
                summary=("Explicação fundamentada do exemplo da aula. " * 36 +
                         "A conclusão deve continuar aparecendo na visão geral.")
                self.assertGreater(len(summary),1250)
                app.store.save_analysis(registered["id"],registered["digest"],
                    "fixture","offline",{"resumo":summary,"tipo_aula":"tecnica",
                    "conceitos":[],"exemplos":[],"duvidas":[]})
                sha="a"*40
                app.store.save_repo("https://github.com/unit/certificates",
                    "certificates",sha,{"files":[],"documentation":[],
                    "technologies":["TypeScript"],"history":[],"evidence":[],
                    "symbols":[{"name":"CertificateService","concept":"CertificateService",
                                "path":"src/certificate.service.ts","line":7,
                                "snippet":"7: export class CertificateService {}"}]},
                    "INDEXED")
                app.publisher.rebuild()
                overview=(app.store.vault/"02-Minhas-Aulas/Aula-012/00-Visao-geral.md"
                         ).read_text(encoding="utf-8")
                self.assertIn("A conclusão deve continuar aparecendo",overview)
                project=(app.store.vault/"03-Meus-Projetos/certificates-aaaaaaa.md"
                        ).read_text(encoding="utf-8")
                self.assertIn("Classes, interfaces e funções presentes no código",project)
                self.assertIn("CertificateService",project)
                self.assertIn("src/certificate.service.ts",project)
                linked_note=next(x for x in (app.store.vault/"02-Minhas-Aulas/Aula-012").glob("*.md")
                                 if x.name!="00-Visao-geral.md")
                self.assertIn("CertificateService",linked_note.read_text(encoding="utf-8"))
            finally:
                app.close()


class RestoreBackupFoundationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trama-220-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "original"
        db = self.vault / ".base-conhecimento" / "estado.sqlite3"
        db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db)) as conn:
            conn.execute("CREATE TABLE evidencias (id TEXT PRIMARY KEY, descricao TEXT)")
            conn.execute("INSERT INTO evidencias VALUES (?,?)", ("aula-001", "fonte artificial"))
            conn.commit()
        # Several valid path components, together longer than classic MAX_PATH.
        self.relative = (
            ".base-conhecimento/repos/" +
            "projeto-" + "a" * 80 + "/" +
            "subpasta-" + "b" * 80 + "/" +
            "arquivos-" + "c" * 80 + ".txt"
        )
        self.original_file = _filesystem_path(self.vault / self.relative)
        self.original_file.parent.mkdir(parents=True, exist_ok=True)
        self.original_file.write_text("Apenas texto fictício da Aula 001.", encoding="utf-8")
        self.backup = self.root / "copia.zip"

    def test_restores_long_github_paths_without_touching_original(self):
        report = create_backup(self.vault, self.backup)
        self.assertTrue(report["ok"])
        self.assertGreater(len(str(self.root / "restored" / self.relative)), 260)
        self.assertGreaterEqual(report["files"], 2)
        target = self.root / "restored"
        restored = restore_backup(self.backup, target)
        self.assertTrue(restored["ok"])
        self.assertEqual(
            _filesystem_path(target / self.relative).read_text(encoding="utf-8"),
            "Apenas texto fictício da Aula 001.",
        )
        self.assertEqual(
            self.original_file.read_text(encoding="utf-8"),
            "Apenas texto fictício da Aula 001.",
        )
        with closing(sqlite3.connect(target / ".base-conhecimento" / "estado.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM evidencias").fetchone()[0], 1)

    def test_restore_never_overwrites_an_existing_vault(self):
        create_backup(self.vault, self.backup)
        with self.assertRaises(ValueError):
            restore_backup(self.backup, self.vault)
        self.assertTrue(self.original_file.is_file())

    def test_rejects_path_traversal_before_publishing(self):
        malicious = self.root / "malicioso.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../escape.txt", "bad")
            archive.writestr(MANIFEST, json.dumps({
                "format": 1,
                "files": {
                    "../escape.txt": {"sha256": "0" * 64, "size": 3},
                    ".base-conhecimento/estado.sqlite3": {"sha256": "0" * 64, "size": 0},
                },
            }))
            archive.writestr(".base-conhecimento/estado.sqlite3", "")
        target = self.root / "malicious-restore"
        with self.assertRaises(ValueError):
            restore_backup(malicious, target)
        self.assertFalse(target.exists())
        self.assertFalse((self.root / "escape.txt").exists())

class DesktopExperienceFoundationsTests(unittest.TestCase):
    def test_github_import_and_confirmations_are_embedded_in_trama(self):
        from knowledge_bridge.bridge import load_local_ui
        html = load_local_ui()
        self.assertIn('id="repo-dialog"', html)
        self.assertIn('id="trama-confirm-dialog"', html)
        self.assertIn('function askTramaConfirm', html)
        self.assertNotIn("const url=prompt(", html)
        self.assertNotIn("if(!confirm(", html)
        self.assertIn("Cole um print aqui (Ctrl + V)", html)
        self.assertNotIn("Não precisa abrir o Paint.", html)

    def test_consent_is_persistent_in_settings_and_can_be_revoked(self):
        from unittest.mock import patch
        from knowledge_bridge.bridge import Bridge
        bridge = Bridge()
        bridge.settings = {"vault": "", "ai_processing_consent": False}
        with patch.object(bridge, "_save") as save:
            self.assertTrue(bridge.set_ai_processing_consent(True)["ok"])
            self.assertTrue(bridge.ai_status()["processing_consent"])
            self.assertTrue(bridge.set_ai_processing_consent(False)["ok"])
            self.assertFalse(bridge.ai_status()["processing_consent"])
            self.assertEqual(save.call_count, 2)
        self.assertFalse(bridge.set_ai_processing_consent("true")["ok"])
        with patch.object(bridge, "_save", side_effect=OSError("disk full")):
            self.assertFalse(bridge.set_ai_processing_consent(True)["ok"])
        self.assertFalse(bridge.settings["ai_processing_consent"])


    def test_git_process_does_not_spawn_console_on_windows(self):
        import subprocess
        from unittest.mock import patch
        from knowledge_bridge.pipeline import Application
        with patch("knowledge_bridge.pipeline.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "git version test"
            self.assertIn("git version test", Application._git(["--version"]))
            self.assertEqual(
                run.call_args.kwargs.get("creationflags"),
                getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )



class VerifiedCodeNavigationTests(unittest.TestCase):
    def test_only_provenance_checked_github_line_is_opened(self):
        from unittest.mock import patch
        from knowledge_bridge.bridge import Bridge
        from knowledge_bridge.store import Store

        with tempfile.TemporaryDirectory(prefix="trama-v220-code-links-") as folder:
            vault = Path(folder) / "Obsidian"
            catalog = Store(vault)
            sha = "a" * 40
            repo_url = "https://github.com/unit/example"
            catalog.save_repo(
                repo_url, "example", sha,
                {"evidence": [{"path": "src/sample.cs", "line": 17}],
                 "files": [{"path": "src/sample.cs", "size": 99}]},
                "INDEXED",
            )
            catalog.close()
            bridge = Bridge()
            bridge.settings = {"vault": str(vault)}
            valid = f"{repo_url}/blob/{sha}/src/sample.cs#L17"
            invalid = [
                "javascript:alert(1)",
                f"https://github.com/other/example/blob/{sha}/src/sample.cs#L17",
                f"{repo_url}/blob/{'b' * 40}/src/sample.cs#L17",
                f"{repo_url}/blob/{sha}/src/sample.cs#L18",
                f"{repo_url}/blob/{sha}/src/../secret.cs#L17",
                f"{repo_url}/blob/{sha}/src/%2e%2e/secret.cs#L17",
                f"{repo_url}/blob/{sha}/src/sample.cs?token=secret#L17",
                f"https://github.com@evil.test/unit/example/blob/{sha}/src/sample.cs#L17",
            ]
            with patch("knowledge_bridge.bridge.webbrowser.open",
                       return_value=True) as opener:
                for address in invalid:
                    self.assertFalse(bridge.open_code_link(address)["ok"], address)
                opener.assert_not_called()
                self.assertTrue(bridge.open_code_link(valid)["ok"])
                opener.assert_called_once_with(valid)

    def test_desktop_renders_code_citations_as_safe_controls(self):
        from knowledge_bridge.bridge import load_local_ui
        html = load_local_ui()
        self.assertIn('data-lib-code', html)
        self.assertIn("call('open_code_link'", html)
        self.assertNotIn('window.open(', html)


class IncrementalUncertaintyIndexTests(unittest.TestCase):
    def test_new_lesson_only_parses_new_term_evidence(self):
        from unittest.mock import patch
        import knowledge_bridge.learning_review as reviews
        from knowledge_bridge.pipeline import Application

        with tempfile.TemporaryDirectory(prefix="trama-v220-indexed-followups-") as folder:
            base=Path(folder)
            app=Application(base/"Obsidian",base/"unused.env",log=lambda *_:None)
            def add(number, content, questions=()):
                source=base/f"Aula-{number:03d}-V01.txt"
                source.write_text(content,encoding="utf-8")
                self.assertTrue(app.add_file(source))
                rec=next(s for s in app.store.sources("transcript")
                         if s["label"]==source.name)
                app.store.save_analysis(rec["id"],rec["digest"],"fake","offline",{
                    "resumo":"Aula com fonte preservada.","tipo_aula":"tecnica",
                    "conceitos":[],"exemplos":[],"duvidas":list(questions)})
                return rec
            try:
                old=add(31,"[0:01] O operador parece exustrix.",
                        questions=["O exustrix corresponde a algum operador RxJS?"])
                calls=[]
                original=reviews._source_text
                def track(store,source):
                    calls.append(source["id"])
                    return original(store,source)
                with patch.object(reviews,"_source_text",side_effect=track):
                    app.publisher.rebuild()
                    self.assertIn(old["id"],calls)
                    calls.clear()
                    app.publisher.rebuild()
                    self.assertEqual(calls,[],"Revisita local repetida sem novas fontes")
                    future=add(50,"[0:02] exhaustMap descarta solicitações concorrentes.")
                    app.publisher.rebuild()
                    self.assertEqual(calls,[future["id"]],"Aula 031 foi relida sem necessidade")
                    rows=app.store.uncertainties_for_source(old["id"])
                    self.assertEqual(len(rows),1)
                    self.assertEqual(rows[0]["status"],"NOVA_EVIDENCIA_PARA_REVISAR")
                    calls.clear()
                    app.publisher.rebuild()
                    self.assertEqual(calls,[])
            finally:
                app.close()


class TargetedFollowUpKnowledgeTests(unittest.TestCase):
    def test_later_evidence_enriches_only_the_question_from_aula_031(self):
        from knowledge_bridge.pipeline import Application

        with tempfile.TemporaryDirectory(prefix="trama-v220-follow-up-") as folder:
            base = Path(folder)
            app = Application(base / "Obsidian", base / "unused.env", log=lambda _: None)
            try:
                def record(lesson, raw, doubt=""):
                    file = base / f"Aula-{lesson}-V01.txt"
                    file.write_text(raw, encoding="utf-8")
                    self.assertTrue(app.add_file(file))
                    src = next(s for s in app.store.sources("transcript")
                               if s["label"] == file.name)
                    app.store.save_analysis(src["id"], src["digest"], "test", "offline", {
                        "resumo": "Conteúdo fictício de teste.",
                        "tipo_aula": "tecnica",
                        "conceitos": [],
                        "exemplos": [],
                        "duvidas": [doubt] if doubt else [],
                    })
                    return src

                src31 = record("031", "[0:01] Não entendi este assunto ainda.",
                               "Como funciona o HttpClient?")
                app.publisher.rebuild()
                note31 = app.store.vault / "02-Minhas-Aulas" / "Aula-031"
                entry31 = next(n for n in note31.glob("*.md")
                               if n.name != "00-Visao-geral.md")
                first = entry31.read_text(encoding="utf-8")
                self.assertIn("Nenhuma explicação posterior", first)

                record("049", "[0:01] Aula sobre organização do curso.")
                app.publisher.rebuild()
                self.assertEqual(entry31.read_text(encoding="utf-8"), first)

                src50 = record("050", "[0:01] O HttpClient realiza requisições HTTP.")
                app.publisher.rebuild()
                enriched = entry31.read_text(encoding="utf-8")
                self.assertIn("Aula-050", enriched)
                self.assertIn("HttpClient realiza requisições", enriched)
                self.assertIn("não comprovam que a dúvida foi resolvida", enriched)
                self.assertIn("NOVA_EVIDENCIA_PARA_REVISAR", enriched)
                self.assertNotEqual(first, enriched)
                # Never rewrite the original transcript when evidence is found.
                self.assertIn("Não entendi", (
                    app.store.vault / src31["stored_path"]
                ).read_text(encoding="utf-8"))
                self.assertIn("HttpClient", (
                    app.store.vault / src50["stored_path"]
                ).read_text(encoding="utf-8"))
            finally:
                app.close()


class IncrementalAutomationFoundationsTests(unittest.TestCase):
    def test_new_lessons_reuse_old_analyses_and_single_part_summary_has_no_prefix(self):
        from knowledge_bridge.ai import AIResult
        from knowledge_bridge.pipeline import Application

        class FakeFreeAI:
            def __init__(self):
                self.calls = 0

            def analyze(self, text, context):
                self.calls += 1
                return AIResult({
                    "resumo": "O professor demonstrou um exemplo de programação.",
                    "tipo_aula": "tecnica",
                    "conceitos": [{
                        "nome": "Console.WriteLine",
                        "explicacao": "Escreve texto no console segundo o exemplo.",
                        "tempo": "0:01",
                    }],
                    "pessoas": [],
                    "atividades": [],
                    "ferramentas": [],
                    "marcos": [],
                    "exemplos": [],
                    "duvidas": [],
                    "nomes_a_conferir": [],
                }, "gemini", "offline-test")

        with tempfile.TemporaryDirectory(prefix="trama-v220-incremental-") as folder:
            root = Path(folder)
            app = Application(root / "obsidian", root / "no-key.env", log=lambda _: None)
            try:
                ai = FakeFreeAI()
                app.ai = ai
                original = root / "Aula-001-V01.txt"
                original.write_text(
                    "[0:01] O professor demonstrou Console.WriteLine em C#.",
                    encoding="utf-8",
                )
                self.assertTrue(app.add_file(original))
                app.process()
                self.assertEqual(ai.calls, 1)
                notes = list((app.store.vault / "02-Minhas-Aulas" / "Aula-001").glob("*.md"))
                transcript_notes = [p for p in notes if p.name != "00-Visao-geral.md"]
                self.assertTrue(transcript_notes)
                self.assertIn("O professor demonstrou", transcript_notes[0].read_text(encoding="utf-8"))
                self.assertNotIn("**Parte 1:**", transcript_notes[0].read_text(encoding="utf-8"))

                # A second run has nothing new and must spend no AI calls.
                app.process()
                self.assertEqual(ai.calls, 1)

                newer = root / "Aula-002-V01.txt"
                newer.write_text("[0:01] Um novo exemplo foi ensinado.", encoding="utf-8")
                self.assertTrue(app.add_file(newer))
                app.process()
                self.assertEqual(ai.calls, 2)
                self.assertTrue((app.store.vault / "02-Minhas-Aulas" / "Aula-001").is_dir())
                self.assertTrue((app.store.vault / "02-Minhas-Aulas" / "Aula-002").is_dir())
            finally:
                app.close()



class ProposedNoteComparisonTests(unittest.TestCase):
    def test_proposal_diff_is_read_only_and_scoped_to_its_original(self):
        from knowledge_bridge.bridge import Bridge,load_local_ui
        with tempfile.TemporaryDirectory(prefix="trama-v220-proposals-") as folder:
            vault=Path(folder)/"Obsidian"
            lesson=vault/"02-Minhas-Aulas"/"Aula-031"
            lesson.mkdir(parents=True)
            note=lesson/"resumo.md"
            draft=lesson/"resumo.PROPOSTA.md"
            note.write_text("# Aula 031\n\nO conceito ainda não foi explicado.",encoding="utf-8")
            draft.write_text("# Aula 031\n\nA Aula 050 trouxe uma evidência.",encoding="utf-8")
            before=(note.read_bytes(),draft.read_bytes())
            bridge=Bridge()
            bridge.settings={"vault":str(vault)}
            ref="02-Minhas-Aulas/Aula-031/resumo.PROPOSTA.md"
            result=bridge.compare_proposal(ref)
            self.assertTrue(result["ok"],result)
            self.assertIn("-O conceito ainda não foi explicado.",result["diff"])
            self.assertIn("+A Aula 050 trouxe uma evidência.",result["diff"])
            self.assertFalse(result["truncated"])
            self.assertFalse(bridge.compare_proposal("02-Minhas-Aulas/Aula-031/resumo.md")["ok"])
            self.assertFalse(bridge.compare_proposal("../resumo.PROPOSTA.md")["ok"])
            self.assertEqual(before,(note.read_bytes(),draft.read_bytes()))
            html=load_local_ui()
            self.assertIn('id="trama-diff-dialog"',html)
            self.assertIn("call('compare_proposal'",html)


class StorageMetricsTests(unittest.TestCase):
    def test_usage_reports_local_categories_without_reading_files(self):
        from knowledge_bridge.bridge import Bridge
        with tempfile.TemporaryDirectory(prefix="trama-v220-storage-") as folder:
            base=Path(folder)
            vault=base/"Cofre"
            files={
                "02-Minhas-Aulas/Aula-001/00-Visao-geral.md":b"note",
                "99-Anexos/Transcricoes-Originais/aula.txt":b"raw" * 3,
                ".base-conhecimento/repos/projeto/app.cs":b"code" * 4,
                ".base-conhecimento/estado.sqlite3":b"db",
                "outros/cache.dat":b"abc",
            }
            for relative,payload in files.items():
                dest=vault/relative
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(payload)
            bridge=Bridge()
            bridge.settings={"vault":str(vault)}
            report=bridge.vault_disk_usage()
            self.assertTrue(report["ok"])
            self.assertEqual(report["files"],len(files))
            self.assertEqual(report["total_bytes"],sum(len(data) for data in files.values()))
            self.assertEqual(report["categories"]["repositories"],16)
            self.assertEqual(report["categories"]["notes"],4)
            self.assertEqual(report["categories"]["attachments"],9)
            self.assertFalse(report["partial"])


class UnsupportedConceptClaimsTests(unittest.TestCase):
    def test_ai_cannot_invent_concepts_or_timestamps_from_unseen_content(self):
        from knowledge_bridge.pipeline import Application
        transcript=(
            "[0:01] Hoje vamos citar o HttpClient do Angular.\\n"
            "[0:02] A transcrição capturou a expressão exaust map, mas "
            "não temos certeza da grafia.\\n"
        )
        response={
            "resumo":"O encontro mencionou HttpClient e uma palavra incerta.",
            "tipo_aula":"tecnica",
            "conceitos":[
                {"nome":"HttpClient","explicacao":"Aparece no texto","tempo":"0:01"},
                {"nome":"GraphQL","explicacao":"A IA inventou este termo","tempo":"99:99"},
                {"nome":"exhaustMap","explicacao":"Pode ser outro operador","tempo":"0:02"},
            ],
            "duvidas":[],
        }
        clean=Application._clean_result(response,transcript)
        self.assertEqual([c["nome"] for c in clean["conceitos"]],["HttpClient"])
        self.assertEqual(clean["conceitos"][0]["tempo"],"0:01")
        self.assertEqual(
            {c["nome"] for c in clean["conceitos_a_conferir"]},
            {"GraphQL","exhaustMap"}
        )
        self.assertNotIn("99:99",str(clean))

    def test_unverified_model_label_stays_out_of_concept_pages(self):
        from knowledge_bridge.pipeline import Application
        with tempfile.TemporaryDirectory(prefix="trama-v220-unsupported-") as folder:
            root=Path(folder)
            app=Application(root/"Obsidian",root/"no-key.env",log=lambda *_:None)
            try:
                file=root/"Aula-070-V01.txt"
                file.write_text("[0:01] O exemplo da aula menciona HttpClient.",
                                encoding="utf-8")
                app.add_file(file)
                src=app.store.sources("transcript")[0]
                data=Application._clean_result({
                    "resumo":"O exemplo apresentou HttpClient.","tipo_aula":"tecnica",
                    "conceitos":[{"nome":"HttpClient","explicacao":"Presente."},
                                {"nome":"GraphQL","explicacao":"Inventado."}]
                },file.read_text(encoding="utf-8"))
                app.store.save_analysis(src["id"],src["digest"],
                                        "fixture","offline",data)
                app.publisher.rebuild()
                lesson_folder=app.store.vault/"02-Minhas-Aulas/Aula-070"
                lesson=next(n for n in lesson_folder.glob("*.md")
                            if n.name!="00-Visao-geral.md")
                text=lesson.read_text(encoding="utf-8")
                self.assertIn("Termos sugeridos pela IA para conferir",text)
                self.assertIn("GraphQL",text)
                self.assertNotIn("**GraphQL**",text)
                concept_files=list((app.store.vault/"01-Meu-Conhecimento").rglob("*.md"))
                self.assertFalse(any("GraphQL" in p.name for p in concept_files))
            finally:
                app.close()


class SummaryQualityRegressionTests(unittest.TestCase):
    def test_short_summary_is_flagged_for_long_transcript_without_another_api_call(self):
        from knowledge_bridge.pipeline import Application
        raw="Uma transcrição de aula técnica com vários exemplos. " * 50
        cleaned=Application._clean_result(
            {"tipo_aula":"tecnica","resumo":"Explicação breve."},raw
        )
        self.assertTrue(cleaned["qualidade_pendente"])
        brief=Application._clean_result(
            {"tipo_aula":"apresentacao","resumo":"Apresentação da turma."},
            "Apresentação curta."
        )
        self.assertFalse(brief["qualidade_pendente"])

    def test_sparse_note_hides_empty_fields_but_preserves_uncertainties(self):
        from knowledge_bridge.pipeline import Application
        with tempfile.TemporaryDirectory(prefix="trama-v220-quality-") as folder:
            base=Path(folder)
            app=Application(base/"Obsidian",base/"no-key.env",log=lambda _:None)
            try:
                file=base/"Aula-009-V01.txt"
                file.write_text("[0:01] O professor falou sobre o tema.",encoding="utf-8")
                app.add_file(file)
                src=app.store.sources("transcript")[0]
                app.store.save_analysis(src["id"],src["digest"],"fake","offline",{
                    "resumo":"O professor explicou o conteúdo da aula.",
                    "tipo_aula":"tecnica",
                    "conceitos":[],"exemplos":[],"pessoas":[],"atividades":[],
                    "ferramentas":[],"marcos":[],"duvidas":[],
                    "qualidade_pendente":["A conferir com a transcrição."]
                })
                app.publisher.rebuild()
                folder=app.store.vault/"02-Minhas-Aulas"/"Aula-009"
                note=next(p for p in folder.glob("*.md") if p.name!="00-Visao-geral.md")
                written=note.read_text(encoding="utf-8")
                self.assertIn("## Qualidade da síntese",written)
                self.assertIn("A conferir com a transcrição.",written)
                self.assertNotIn("## Pessoas citadas e papéis",written)
                self.assertNotIn("## Exemplos mencionados",written)
            finally:
                app.close()


class LocalPreferencesRegressionTests(unittest.TestCase):
    def test_favorite_survives_restart_and_failed_write_keeps_previous_state(self):
        from unittest.mock import patch
        from knowledge_bridge.bridge import Bridge
        with tempfile.TemporaryDirectory(prefix="trama-v220-favorites-") as folder:
            base=Path(folder)
            vault=base/"Obsidian"
            (vault/"01-Meu-Conhecimento").mkdir(parents=True)
            (vault/"01-Meu-Conhecimento"/"POO.md").write_text(
                "# Orientação a Objetos\nConteúdo local.",encoding="utf-8")
            data=base/"settings"
            settings_file=data/"settings.json"
            with (patch("knowledge_bridge.bridge.DATA_HOME",data),
                  patch("knowledge_bridge.bridge.SETTINGS_FILE",settings_file)):
                original=Bridge()
                original.settings={"vault":str(vault),"favorites":[]}
                chosen="01-Meu-Conhecimento/POO.md"
                self.assertTrue(original.toggle_favorite(chosen)["ok"])
                reopened=Bridge()
                self.assertIn(chosen,reopened.snapshot()["favorites"])
                self.assertTrue(reopened.copy_note_link("../wrong.md")["ok"] is False)
                response=reopened.copy_note_link(chosen)
                self.assertTrue(response["ok"] or response.get("text")=="[[01-Meu-Conhecimento/POO]]")
                with patch("knowledge_bridge.bridge.os.replace",
                           side_effect=OSError("simulated locked settings")):
                    self.assertFalse(reopened.toggle_favorite(chosen)["ok"])
                self.assertIn(chosen,reopened.snapshot()["favorites"])
                after=Bridge()
                self.assertIn(chosen,after.snapshot()["favorites"])

    def test_importer_has_separate_github_field_and_native_clipboard_api(self):
        from knowledge_bridge.bridge import load_local_ui
        html=load_local_ui()
        self.assertIn('id="auto-repos"',html)
        self.assertIn("call('copy_note_link'",html)
        self.assertIn("call('search_notes'",html)
        self.assertIn('id="lib-search-status"',html)


class LiteralSourceSymbolTests(unittest.TestCase):
    def test_custom_class_and_interface_are_linked_only_when_named_in_lesson(self):
        from knowledge_bridge.code_intel import index_repository,match_lesson_to_repository,find_code_line
        with tempfile.TemporaryDirectory(prefix="trama-v220-symbol-") as folder:
            root=Path(folder)
            (root/"services").mkdir()
            file=root/"services"/"certificate.service.ts"
            file.write_text(
                "export class CertificateService {\n"
                "  create() { return true; }\n"
                "}\n",
                encoding="utf-8",
            )
            (root/"services"/"contract.cs").write_text(
                "public interface ICertificateRepository { }\n",
                encoding="utf-8",
            )
            indexed=index_repository(root,[
                "services/certificate.service.ts","services/contract.cs"
            ])
            names={item["name"] for item in indexed["symbols"]}
            self.assertIn("CertificateService",names)
            self.assertIn("ICertificateRepository",names)
            matches=match_lesson_to_repository(
                "[0:04] O CertificateService gerencia a criação de certificados.",
                None,indexed
            )
            self.assertTrue(any(m["concept"]=="CertificateService" for m in matches))
            self.assertFalse(any(m["concept"]=="ICertificateRepository" for m in matches))
            self.assertEqual(
                find_code_line(indexed,"services/certificate.service.ts",1)["concept"],
                "CertificateService"
            )

    def test_symbol_code_reference_requires_exact_registered_line(self):
        from unittest.mock import patch
        from knowledge_bridge.bridge import Bridge
        from knowledge_bridge.store import Store
        sha="c"*40
        url="https://github.com/unit/symbol-example"
        with tempfile.TemporaryDirectory(prefix="trama-v220-symbol-url-") as folder:
            vault=Path(folder)/"vault"
            store=Store(vault)
            store.save_repo(url,"symbol-example",sha,{
                "evidence":[],
                "symbols":[{"name":"CertificateService","concept":"CertificateService",
                            "path":"services/certificate.service.ts","line":1}]
            },"INDEXED")
            store.close()
            bridge=Bridge()
            bridge.settings={"vault":str(vault)}
            good=f"{url}/blob/{sha}/services/certificate.service.ts#L1"
            bad=f"{url}/blob/{sha}/services/certificate.service.ts#L2"
            with patch("knowledge_bridge.bridge.webbrowser.open",
                       return_value=True) as opener:
                self.assertFalse(bridge.open_code_link(bad)["ok"])
                self.assertTrue(bridge.open_code_link(good)["ok"])
                opener.assert_called_once_with(good)


class FairCodeEvidenceTests(unittest.TestCase):
    def test_rare_angular_operator_is_not_hidden_by_early_generic_classes(self):
        from knowledge_bridge.code_intel import index_repository, MAX_EVIDENCE
        with tempfile.TemporaryDirectory(prefix="trama-v220-index-") as folder:
            root=Path(folder)
            paths=[]
            for i in range(95):
                name=f"src/part-{i:03d}.ts"
                file=root/name
                file.parent.mkdir(parents=True,exist_ok=True)
                file.write_text(
                    "\n".join(f"class Example{j:02d} {{}}" for j in range(12)),
                    encoding="utf-8"
                )
                paths.append(name)
            rare="src/zz-final-polling.ts"
            (root/rare).write_text(
                "import { exhaustMap } from 'rxjs/operators';\n"
                "source.pipe(exhaustMap(() => request()));",
                encoding="utf-8"
            )
            paths.append(rare)
            indexed=index_repository(root,sorted(paths))
            evidence=indexed["evidence"]
            self.assertLessEqual(len(evidence),MAX_EVIDENCE)
            self.assertTrue(any(e["concept"]=="exhaustMap" and
                                e["path"]==rare for e in evidence))
            self.assertGreater(len({e["path"] for e in evidence}),10)


class ObsidianFullTextSearchTests(unittest.TestCase):
    def test_search_finds_text_inside_notes_and_shows_short_excerpts(self):
        from unittest.mock import patch
        from knowledge_bridge.bridge import Bridge
        with tempfile.TemporaryDirectory(prefix="trama-v220-search-") as folder:
            vault=Path(folder)/"Vault"
            section=vault/"02-Minhas-Aulas"
            section.mkdir(parents=True)
            (section/"Aula-031.md").write_text(
                "# Aula 031\n\nExemplo de Angular com HttpClient usado nas requisições.",
                encoding="utf-8"
            )
            (section/"Aula-050.md").write_text(
                "# Aula 050\n\nNenhuma relação com o conceito pesquisado.",
                encoding="utf-8"
            )
            bridge=Bridge()
            bridge.settings={"vault":str(vault)}
            with patch("knowledge_bridge.bridge.webbrowser.open",
                       side_effect=AssertionError("Search must not open URLs")):
                matches=bridge.search_notes("HttpClient")
            self.assertTrue(matches["ok"])
            self.assertEqual(matches["total"],1)
            self.assertEqual(len(matches["matches"]),1)
            self.assertEqual(matches["matches"][0]["id"],
                             "02-Minhas-Aulas/Aula-031.md")
            self.assertIn("HttpClient",matches["matches"][0]["snippet"])
            self.assertNotIn("Aula 050",str(matches))
            self.assertTrue(matches["matches"][0]["in_content"])
            self.assertFalse(bridge.search_notes("../bad\nname")["ok"])
            self.assertFalse(bridge.search_notes("x"*121)["ok"])
            self.assertFalse(bridge.search_notes("HttpClient",101)["ok"])

    def test_search_never_follows_symlinks_outside_vault(self):
        from knowledge_bridge.bridge import Bridge
        with tempfile.TemporaryDirectory(prefix="trama-v220-search-symlink-") as folder:
            base=Path(folder)
            vault=base/"Obsidian"
            vault.mkdir()
            outside=base/"PRIVATE.md"
            outside.write_text("SENHA_SUPER_SECRETA_PARA_TESTE",encoding="utf-8")
            try:
                (vault/"link.md").symlink_to(outside)
            except (OSError,NotImplementedError):
                self.skipTest("Symlinks not available for this account")
            bridge=Bridge()
            bridge.settings={"vault":str(vault)}
            found=bridge.search_notes("SENHA_SUPER_SECRETA_PARA_TESTE")
            self.assertEqual(found["total"],0)


class LargeLocalLibraryTests(unittest.TestCase):
    def test_150_lessons_enter_six_at_a_time_without_losing_structure(self):
        """Simulate the user's gradual import rhythm without an external API."""
        from knowledge_bridge.pipeline import Application

        with tempfile.TemporaryDirectory(prefix="trama-v220-150-lessons-") as folder:
            base = Path(folder)
            app = Application(base / "cofre", base / "no-key.env", log=lambda _: None)
            try:
                for number in range(1, 151):
                    name = f"Aula-{number:03d}-V01.txt"
                    source = base / name
                    source.write_text(
                        f"[0:01] Material fictício referente à aula {number}.",
                        encoding="utf-8",
                    )
                    self.assertTrue(app.add_file(source))
                    if number % 6 == 0:
                        app.publisher.rebuild()
                sources = app.store.sources("transcript")
                self.assertEqual(len(sources), 150)
                lessons = app.store.vault / "02-Minhas-Aulas"
                self.assertTrue((lessons / "Aula-001" / "00-Visao-geral.md").is_file())
                self.assertTrue((lessons / "Aula-150" / "00-Visao-geral.md").is_file())
                self.assertEqual(
                    sum(p.is_dir() and p.name.startswith("Aula-") for p in lessons.iterdir()),
                    150,
                )
                self.assertEqual(
                    len(list(app.store.vault.rglob("*.PROPOSTA*.md"))), 0
                )
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
