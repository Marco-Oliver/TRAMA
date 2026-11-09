"""Camada de estudo (04-Resumos): resumos por aula/módulo, CRUD e publicação.

Tudo offline: IA simulada, cofre temporário, nenhuma rede.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from knowledge_bridge.ai import AIResult, BudgetStopped
from knowledge_bridge.bridge import Bridge
from knowledge_bridge.pipeline import Application
from knowledge_bridge.study_notes import (
    DEFAULT_MODULES, UNASSIGNED, StudyNotes, lesson_note_path, module_note_path, publish)


def lesson_payload(**over):
    data = {
        "em_uma_frase": "Configuração do ambiente C# e primeiro programa.",
        "mapa_mental": [
            {"tema": "Ambiente", "pontos": [
                {"texto": "Instalar o .NET SDK e conferir a versão", "videos": ["V01"]},
                {"texto": "VS Code com C# Dev Kit", "videos": ["v2"]}]},
            {"tema": "Primeiro programa", "pontos": [
                {"texto": "Console.WriteLine escreve na tela", "videos": ["V99"]}]},
        ],
        "o_que_saber": [
            {"ponto": "SDK", "explicacao": "Kit para compilar C#.", "videos": ["V01"]},
            {"ponto": "Depuração", "explicacao": "Breakpoint e F10.", "videos": []},
        ],
        "comandos": [
            {"codigo": "dotnet --version", "para_que": "ver a versão", "videos": ["V01"]},
            {"codigo": "rm -rf /", "para_que": "inventado", "videos": ["V01"]},
        ],
        "ligacoes": {"anterior": "", "prepara": "Lógica de programação."},
        "lacunas": [{"item": "Criação de conta no GitHub", "situacao": "problema de captcha"}],
        "para_fazer": ["Hello World"],
        "revisao": [{"pergunta": "O que é o SDK?", "resposta": "Kit de desenvolvimento."}],
        "modulos": ["logica-de-programacao", "modulo-inexistente"],
    }
    data.update(over)
    return data


class FakeStudyRouter:
    def __init__(self, lesson=None, module=None, stop_after=None):
        self.lesson = lesson or lesson_payload()
        self.module = module or {
            "visao_geral": "Fundamentos de C#.",
            "trilha": [{"etapa": "Ambiente", "resumo": "Preparar.", "aulas": ["Aula-002", "Aula-999"]}],
            "conceitos_chave": [{"conceito": "SDK", "explicacao": "Kit.", "aulas": ["Aula-002"]}],
            "como_se_conecta": "Tudo começa pelo ambiente.",
            "pontos_de_atencao": ["Versão do SDK"],
            "checklist_revisao": ["Sei instalar o SDK"],
        }
        self.prompts, self.attempts, self.stop_after = [], 0, stop_after

    def active(self):
        return ["gemini"]

    def _count(self, prompt):
        if self.stop_after is not None and self.attempts >= self.stop_after:
            raise BudgetStopped("Limite local de chamadas atingido; retome depois.")
        self.attempts += 1
        self.prompts.append(prompt)

    def study_lesson(self, prompt):
        self._count(prompt)
        return AIResult(json.loads(json.dumps(self.lesson)), "gemini", "fake")

    def study_module(self, prompt):
        self._count(prompt)
        return AIResult(json.loads(json.dumps(self.module)), "gemini", "fake")

    def analyze(self, *_a, **_k):
        raise AssertionError("análise não esperada")


class StudyNotesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.app = Application(self.vault, config=self.root / "none.env", log=lambda _t: None)
        self.addCleanup(self.app.close)

    def add(self, filename, text, analysis=None):
        path = self.root / filename
        path.write_text(text, encoding="utf-8")
        self.app.add_file(path)
        row = next(s for s in self.app.store.sources("transcript") if s["label"] == filename)
        if analysis is not None:
            base = {"tipo_aula": "tecnica", "resumo": "Resumo.", "conceitos": [], "pessoas": [],
                    "atividades": [], "ferramentas": [], "marcos": [], "exemplos": [],
                    "duvidas": [], "nomes_a_conferir": []}
            base.update(analysis)
            self.app.store.save_analysis(row["id"], row["digest"], "offline", "cached", base)
        return row

    def study(self):
        return StudyNotes(self.app.store, log=lambda _t: None)

    def lesson2(self):
        self.add("A02 - V01 - SDK.txt", "[0:01] Rode dotnet --version no terminal.\n",
                 {"resumo": "Instalação do .NET SDK e verificação com dotnet --version.",
                  "conceitos": [{"nome": "SDK", "explicacao": "Kit."}],
                  "exemplos": ["dotnet --version"]})
        self.add("A02 - V02 - VS Code.txt", "[0:01] Instale o C# Dev Kit e use console.\n",
                 {"resumo": "VS Code, C# Dev Kit, Console.WriteLine e console.",
                  "conceitos": [{"nome": "Console", "explicacao": "Saída."}]})

    # -------------------------------------------------------------- modules
    def test_default_modules_are_the_course_modules_in_order_and_seeded_once(self):
        study = self.study()
        self.assertEqual([m["id"] for m in study.modules()], [m[0] for m in DEFAULT_MODULES])
        for module in study.modules():
            study.delete_module(module["id"])
        self.assertEqual(self.study().modules(), [])

    def test_module_crud_and_delete_keeps_lessons(self):
        study = self.study()
        created = study.save_module({"name": "Mensageria", "description": "RabbitMQ",
                                     "keywords": "rabbitmq, masstransit"})
        self.assertEqual(created["id"], "mensageria")
        self.assertEqual(created["keywords"], ["rabbitmq", "masstransit"])
        with self.assertRaises(ValueError):
            study.save_module({"name": "mensageria"})
        study.save_module({"id": "mensageria", "name": "Mensageria e Filas"})
        self.assertEqual(study.module("mensageria")["name"], "Mensageria e Filas")
        study.move_module("mensageria", -1)
        self.assertEqual(study.modules()[-2]["id"], "mensageria")
        self.lesson2()
        study.set_lesson_modules("Aula-002", ["mensageria"])
        self.assertEqual(study.lesson_modules("Aula-002"), ["mensageria"])
        study.delete_module("mensageria")
        self.assertEqual(study.lesson_modules("Aula-002"), [])
        self.assertIn("Aula-002", study.module_lessons(UNASSIGNED))
        self.assertEqual(len(self.app.store.sources("transcript")), 2)

    def test_manual_choice_beats_ai_and_keywords_and_can_be_reset(self):
        self.lesson2()
        study = self.study()
        self.assertEqual(study.lesson_modules("Aula-002"), ["logica-de-programacao"])
        self.assertEqual(study.module_origin("Aula-002"), "automatico")
        study.run(FakeStudyRouter(lesson_payload(modulos=["testes"])), ["Aula-002"], modules=False)
        self.assertEqual(study.lesson_modules("Aula-002"), ["testes"])
        self.assertEqual(study.module_origin("Aula-002"), "ia")
        study.set_lesson_modules("Aula-002", ["banco-de-dados"])
        self.assertEqual(study.lesson_modules("Aula-002"), ["banco-de-dados"])
        study.run(FakeStudyRouter(lesson_payload(modulos=["frontend"])), ["Aula-002"], modules=False)
        self.assertEqual(study.lesson_modules("Aula-002"), ["banco-de-dados"])
        study.set_lesson_modules("Aula-002", None)
        self.assertEqual(study.lesson_modules("Aula-002"), ["frontend"])

    # -------------------------------------------------------------- lesson summary
    def test_lesson_summary_is_grounded_before_publication(self):
        self.lesson2()
        study = self.study()
        self.assertEqual(study.lesson_status("Aula-002"), "pendente")
        router = FakeStudyRouter()
        result = study.run(router, study.pending_lessons())
        self.assertEqual(result["lessons"], ["Aula-002"])
        summary = study.lesson_summary("Aula-002")["payload"]
        codes = [c["codigo"] for c in summary["comandos"]]
        self.assertEqual(codes, ["dotnet --version"])
        self.assertEqual(summary["comandos_descartados"], 1)
        self.assertEqual(summary["comandos"][0]["origem"], "transcrição")
        refs = [p["videos"] for t in summary["mapa_mental"] for p in t["pontos"]]
        self.assertEqual(refs[0], ["V01"])
        self.assertEqual(refs[1], ["V02"])          # "v2" normalizado
        self.assertNotIn("V99", refs[2])            # vídeo inexistente descartado
        self.assertEqual(summary["modulos"], ["logica-de-programacao"])
        self.assertEqual(study.lesson_status("Aula-002"), "atualizado")
        prompt = router.prompts[0]
        self.assertIn("<dados_nao_confiaveis>", prompt)
        self.assertIn("modulos_disponiveis", prompt)
        self.assertNotIn("[0:01] Rode", prompt)     # TXT bruto não é enviado

    def test_lesson_not_ready_until_every_recording_is_analyzed(self):
        self.add("A03 - V01 - A.txt", "texto", {"resumo": "Um."})
        self.add("A03 - V02 - B.txt", "texto dois")
        study = self.study()
        self.assertEqual(study.lesson_status("Aula-003"), "sem_analise")
        router = FakeStudyRouter()
        self.assertEqual(study.run(router, ["Aula-003"])["lessons"], [])
        self.assertEqual(router.attempts, 0)

    def test_new_recording_marks_summary_outdated(self):
        self.lesson2()
        study = self.study()
        study.run(FakeStudyRouter(), ["Aula-002"], modules=False)
        self.add("A02 - V03 - Debug.txt", "breakpoint", {"resumo": "Depuração com breakpoint."})
        self.assertEqual(self.study().lesson_status("Aula-002"), "desatualizado")
        self.assertEqual(self.study().pending_lessons(), ["Aula-002"])

    def test_interrupted_auto_study_retries_next_run_but_never_backfills(self):
        self.add("A01 - V01 - Antiga.txt", "texto antigo", {"resumo": "Aula antiga."})
        self.lesson2()
        self.app.auto_study = True
        self.app.ai = FakeStudyRouter(stop_after=0)
        self.app.study_after_analysis({"Aula-002"})
        self.assertEqual(self.study().auto_queue(), {"Aula-002"})
        router = FakeStudyRouter()
        self.app.ai = router
        self.app.study_after_analysis(set())          # nenhuma aula nova nesta execução
        self.assertIsNotNone(self.study().lesson_summary("Aula-002"))
        self.assertIsNone(self.study().lesson_summary("Aula-001"))
        self.assertEqual(self.study().auto_queue(), set())

    def test_open_doubts_come_from_local_catalog_not_ai(self):
        row = self.add("A04 - V01 - X.txt", "texto", {"resumo": "Resumo."})
        self.app.store.upsert_uncertainty(
            "u1", row["id"], row["digest"], "x", "check password saind assim", "",
            "PENDENTE", [])
        self.app.store.upsert_uncertainty(
            "u2", row["id"], row["digest"], "x", "resolvida", "",
            "EXPLICADA_PELO_CODIGO", [{"x": 1}])
        doubts = self.study().open_doubts("Aula-004")
        self.assertEqual([d["pergunta"] for d in doubts], ["check password saind assim"])

    def test_invalid_ai_payload_is_not_saved(self):
        self.lesson2()
        study = self.study()
        result = study.run(FakeStudyRouter(lesson_payload(em_uma_frase="", mapa_mental=[],
                                                          o_que_saber=[])), ["Aula-002"])
        self.assertEqual(result["failed"], ["Aula-002"])
        self.assertIsNone(study.lesson_summary("Aula-002"))

    def test_budget_stop_keeps_finished_lessons(self):
        self.lesson2()
        self.add("A03 - V01 - A.txt", "texto", {"resumo": "Classes e objetos."})
        study = self.study()
        result = study.run(FakeStudyRouter(stop_after=1), study.pending_lessons())
        self.assertEqual(result["lessons"], ["Aula-002"])
        self.assertTrue(result["stopped"])
        self.assertEqual(study.pending_lessons(), ["Aula-003"])

    # -------------------------------------------------------------- modules AI/living
    def test_module_summary_is_automatic_after_three_lessons_and_validated(self):
        study = self.study()
        for n in (2, 3, 4):
            self.add(f"A0{n} - V01 - T.txt", "console", {"resumo": f"Aula {n} com console."})
        router = FakeStudyRouter()
        result = study.run(router, study.pending_lessons())
        self.assertEqual(result["modules"], ["logica-de-programacao"])
        summary = study.module_summary("logica-de-programacao")["payload"]
        self.assertEqual(summary["trilha"][0]["aulas"], ["Aula-002"])   # Aula-999 descartada
        self.assertEqual(study.module_status("logica-de-programacao")["new_since_summary"], 0)
        living = study.living_module("logica-de-programacao")
        self.assertEqual([x["aula"] for x in living["aulas"]], ["Aula-002", "Aula-003", "Aula-004"])

    def test_module_not_regenerated_until_five_new_lessons(self):
        study = self.study()
        for n in (2, 3, 4):
            self.add(f"A0{n} - V01 - T.txt", "console", {"resumo": f"Aula {n} com console."})
        study.run(FakeStudyRouter(), study.pending_lessons())
        self.add("A05 - V01 - T.txt", "console", {"resumo": "Aula 5 com console."})
        router = FakeStudyRouter()
        result = study.run(router, study.pending_lessons())
        self.assertEqual(result["modules"], [])
        self.assertEqual(router.attempts, 1)
        self.assertEqual(study.module_status("logica-de-programacao")["new_since_summary"], 1)


    # -------------------------------------------------------------- lacunas retomadas
    def test_gap_is_marked_retaken_only_by_a_later_lesson_passage(self):
        self.lesson2()
        study = self.study()
        study.run(FakeStudyRouter(lesson_payload(lacunas=[
            {"item": "Criação de Conta no Github", "situacao": "problema de captcha"},
            {"item": "Instalação do Git", "situacao": "não aparece"},
            {"item": "Entrada de dados", "situacao": "não aparece"}])), ["Aula-002"], modules=False)
        # Aula anterior não conta; aula posterior sim, mas só no mesmo trecho.
        self.add("A01 - V01 - Antes.txt", "x", {"resumo": "Criamos a conta no GitHub juntos."})
        self.add("A03 - V01 - Depois.txt", "x", {
            "resumo": ("Hoje criamos a conta no GitHub e publicamos o repositório. "
                       + "palavra " * 60 + "Também falamos de instalação de extensões. "
                       + "palavra " * 60 + "O comando git commit registra alterações.")})
        gaps = {g["item"]: g["retomada"] for g in self.study().gap_followups("Aula-002")}
        self.assertEqual(gaps["Criação de Conta no Github"]["aula"], "Aula-003")
        self.assertIsNone(gaps["Instalação do Git"])          # termos longe um do outro
        self.assertIsNone(gaps["Entrada de dados"])
        study = self.study()
        living = study.living_module("logica-de-programacao")
        self.assertEqual({g["item"] for g in living["lacunas_abertas"]},
                         {"Instalação do Git", "Entrada de dados"})
        self.app.publisher.rebuild()
        note = (self.vault / lesson_note_path("Aula-002")).read_text(encoding="utf-8")
        self.assertIn("retomada em [[04-Resumos/Aulas/Aula-003|Aula-003]]", note)
        self.assertIn("Instalação do Git** — não aparece — *em aberto*", note)

    def test_gap_followup_needs_no_ai_and_does_not_mark_summary_outdated(self):
        self.lesson2()
        study = self.study()
        study.run(FakeStudyRouter(), ["Aula-002"], modules=False)
        self.add("A03 - V01 - Depois.txt", "x", {"resumo": "Criação da conta no GitHub com captcha."})
        study = self.study()
        self.assertEqual(study.lesson_status("Aula-002"), "atualizado")
        self.assertEqual(study.gap_followups("Aula-002")[0]["retomada"]["aula"], "Aula-003")

    # -------------------------------------------------------------- publication
    def test_publish_writes_04_resumos_and_protects_manual_edits(self):
        self.lesson2()
        study = self.study()
        study.run(FakeStudyRouter(), ["Aula-002"], modules=False)
        self.app.publisher.rebuild()
        note = self.vault / lesson_note_path("Aula-002")
        text = note.read_text(encoding="utf-8")
        for heading in ("## Em uma frase", "## Mapa mental", "## O que você precisa saber",
                        "## Comandos e código", "## Ligação com outras aulas", "## Lacunas",
                        "## Para fazer", "## Dúvidas em aberto", "## Revisão rápida"):
            self.assertIn(heading, text)
        self.assertIn("`dotnet --version`", text)
        self.assertNotIn("rm -rf", text)
        self.assertTrue((self.vault / module_note_path("logica-de-programacao")).is_file())
        self.assertTrue((self.vault / "04-Resumos/00-Indice.md").is_file())
        note.write_text(text + "\nMinha anotação.\n", encoding="utf-8")
        study.run(FakeStudyRouter(lesson_payload(em_uma_frase="Outra frase.")), ["Aula-002"],
                  modules=False)
        self.add("A02 - V03 - Novo.txt", "novo", {"resumo": "Novo."})
        study.run(FakeStudyRouter(lesson_payload(em_uma_frase="Outra frase.")),
                  self.study().pending_lessons(), modules=False)
        self.app.publisher.rebuild()
        self.assertIn("Minha anotação.", note.read_text(encoding="utf-8"))
        self.assertTrue(list(note.parent.glob("Aula-002.PROPOSTA*.md")))

    def test_deleted_module_page_is_archived_only_if_untouched(self):
        self.lesson2()
        study = self.study()
        study.save_module({"name": "Extra"})
        study.set_lesson_modules("Aula-002", ["extra"])
        self.app.publisher.rebuild()
        page = self.vault / module_note_path("extra")
        self.assertTrue(page.is_file())
        study.delete_module("extra")
        self.app.publisher.rebuild()
        self.assertFalse(page.exists())
        self.assertTrue(list((self.vault / "90-Sistema/Resumos-Arquivados").glob("extra-*.md")))

    # -------------------------------------------------------------- pipeline
    def test_process_generates_study_only_for_lessons_analyzed_in_this_run(self):
        self.add("A01 - V01 - Antiga.txt", "texto antigo", {"resumo": "Aula antiga."})
        new = self.root / "A02 - V01 - Nova.txt"
        new.write_text("[0:01] Rode dotnet --version agora.\n", encoding="utf-8")
        self.app.add_file(new)
        router = FakeStudyRouter()
        router.analyze = lambda text, context: AIResult(
            {"resumo": "Instalação do SDK.", "conceitos": [], "tipo_aula": "tecnica",
             "pessoas": [], "atividades": [], "ferramentas": [], "marcos": [],
             "exemplos": [], "duvidas": [], "nomes_a_conferir": []}, "gemini", "fake")
        self.app.ai = router
        self.app.process()      # auto_study desligado (CLI/testes)
        self.assertIsNone(self.study().lesson_summary("Aula-002"))
        self.app.auto_study = True
        self.app.process(lesson_filter="Aula-002", force=True)
        study = self.study()
        self.assertIsNotNone(study.lesson_summary("Aula-002"))
        self.assertIsNone(study.lesson_summary("Aula-001"))
        self.assertTrue((self.vault / lesson_note_path("Aula-002")).is_file())


class StudyBridgeTests(unittest.TestCase):
    def test_ai_actions_require_confirmation_and_reads_need_vault(self):
        bridge = Bridge.__new__(Bridge)
        bridge.settings = {}
        bridge._write_lock = __import__("threading").Lock()
        self.assertFalse(bridge.study_generate(False)["ok"])
        self.assertFalse(bridge.study_update_module("testes", False)["ok"])
        self.assertFalse(bridge.study_delete_module("testes", False)["ok"])
        with patch.object(Bridge, "_vault", return_value=None):
            self.assertFalse(bridge.study_overview()["ok"])
        self.assertFalse(bridge.study_lesson("../x")["ok"])
        self.assertFalse(bridge.study_module("Bad Id")["ok"])

    def test_crud_through_bridge_publishes_without_ai(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            bridge = Bridge.__new__(Bridge)
            bridge.settings = {}
            bridge._write_lock = __import__("threading").Lock()
            with patch.object(Bridge, "_vault", return_value=vault):
                created = bridge.study_save_module({"name": "Mensageria"})
                self.assertTrue(created["ok"], created)
                overview = bridge.study_overview()
                self.assertIn("mensageria", [m["id"] for m in overview["modules"]])
                self.assertTrue((vault / "04-Resumos/00-Indice.md").is_file())
                self.assertTrue(bridge.study_delete_module("mensageria", True)["ok"])
                self.assertFalse(bridge.study_save_module({"name": ""})["ok"])


class AuditFixesTests(unittest.TestCase):
    """Links de materiais registrados na aula abrem; o resto continua bloqueado."""

    def test_registered_material_and_official_doc_links_open_others_do_not(self):
        from knowledge_bridge.auto_ingest import AutoOrganizer
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            app = Application(vault, config=root / "none.env", log=lambda _t: None)
            post = {"aula": "Aula-002", "titulo": "T", "data": "", "descricao": "", "pessoas": "",
                    "atividades": "", "videos": "", "links": "https://whimsical.com/aula-02"}
            AutoOrganizer(app, log=lambda _t: None)._save_extracted(
                {"id": "p", "stored_path": "(post)"}, "Aula-002", post, reason="teste")
            sha = "9af5282b722d71a5f97d60a7cdbe9a8da826d838"
            app.store.freeze_academy_docs("Aula-002", sha)
            docs = "https://academiadoprogramador-fullstack.github.io/docs/tutoriais/dotnet-sdk/"
            app.store.register_academy_doc("Aula-002", docs, sha, "docs/01 - Tutoriais/01 - Dotnet SDK.md",
                                           "SDK", [], [], [])
            app.close()
            bridge = Bridge.__new__(Bridge)
            bridge.settings = {}
            opened = []
            blob = ("https://github.com/academiadoprogramador-fullstack/docs/blob/" + sha +
                    "/docs/01%20-%20Tutoriais/01%20-%20Dotnet%20SDK.md#L22")
            with patch.object(Bridge, "_vault", return_value=vault.resolve()), \
                    patch("knowledge_bridge.bridge.webbrowser.open", side_effect=lambda u: opened.append(u) or True):
                for url in ("https://whimsical.com/aula-02", docs, blob):
                    self.assertTrue(bridge.open_video_link(url)["ok"], url)
                for url in ("https://evil.example/x", "https://github.com/academiadoprogramador-fullstack/docs/blob/"
                            + "0" * 40 + "/docs/x.md", "javascript:alert(1)"):
                    self.assertFalse(bridge.open_video_link(url)["ok"], url)
            self.assertEqual(len(opened), 3)

    def test_packaged_ui_contains_study_view_and_assets(self):
        from knowledge_bridge.bridge import load_local_ui
        html = load_local_ui()
        self.assertIn('data-view="study"', html)
        self.assertIn("renderStudyView", html)
        self.assertIn(".study-workspace", html)
        self.assertIn('id="study-module-dialog"', html)
        self.assertNotIn('<script src=', html)


if __name__ == "__main__":
    unittest.main()
