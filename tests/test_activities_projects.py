"""Atividades/trabalhos/provas, aulas de desenvolvimento e aba Projetos.

Tudo offline: GitHub e IA simulados, cofre temporário.
"""
from __future__ import annotations

import hashlib
import json
import threading
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from knowledge_bridge.activities import (Activities, activity_note_path, parse_date, parse_post,
                                         suggest_kind)
from knowledge_bridge.ai import AIResult
from knowledge_bridge.auto_ingest import AutoOrganizer
from knowledge_bridge.bridge import Bridge
from knowledge_bridge.github_mapping import MappingError
from knowledge_bridge.pipeline import Application
from knowledge_bridge.projects import Projects, detect_stack, outline, repo_note_path
from knowledge_bridge.study_notes import StudyNotes, lesson_note_path, module_note_path

MY_REPO = "https://github.com/Marco-Oliver/HelloWorld"
PROF_REPO = "https://github.com/academiadoprogramador-fullstack/hello-world"
DUO_REPO = "https://github.com/netos-do-velho-barrero/gerador-de-certificados"
PROF_GERADOR = "https://github.com/academiadoprogramador-fullstack/gerador-de-certificados"
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40

POST = """[M01] Atividade 01 - Hello World em C#
Tiago Santini de Athayde • 3 de mar.
100 pontos
Data de entrega: 10 de mar., 23:59
Crie um programa de console que escreva Hello World usando Console.WriteLine.
Entregue o link do repositório: https://github.com/Marco-Oliver/HelloWorld
Comentários da turma
Adicionar comentário para a turma
"""

FILES = {
    "README.md": "# Hello World\nPrograma de console.\n",
    "HelloWorld/Program.cs": 'using System;\n\nConsole.WriteLine("Hello World");\n',
    "HelloWorld/HelloWorld.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
    "HelloWorld/bin/Debug/x.dll": "binario",
}


class FakeClient:
    """Stands in for GithubMapping._get (REST)."""
    token = ""

    def __init__(self):
        self.calls = []

    def _get(self, repo, endpoint):
        self.calls.append((repo, endpoint))
        if endpoint == "":
            return {"default_branch": "main", "private": False, "description": "Repo de teste"}
        if endpoint.startswith("commits"):
            return [{"sha": SHA_A if "until=" in endpoint else SHA_B}]
        if endpoint.startswith("branches"):
            return [{"name": "main", "commit": {"sha": SHA_B}}, {"name": "v1", "commit": {"sha": SHA_C}}]
        if endpoint.startswith("tags"):
            return [{"name": "V0", "commit": {"sha": SHA_A}}]
        raise MappingError("inesperado")


class FakeReader:
    def __init__(self, files=None):
        self.files = files or FILES
        self._trees = {}
        self.tree_calls = 0
        self.cache = None

    def tree(self, repo, sha):
        if (repo, sha) not in self._trees:
            self.tree_calls += 1
            self._trees[(repo, sha)] = {p: {"size": len(c), "blob_sha": hashlib.sha1(c.encode()).hexdigest()}
                                        for p, c in self.files.items()}
        return self._trees[(repo, sha)]

    def read_file(self, repo, sha, path):
        if path.endswith(".dll"):
            raise MappingError("Arquivo binário.")
        return {"path": path, "content": self.files[path], "size": len(self.files[path])}


class FakeCache:
    def __init__(self):
        self.data = {}

    def get(self, key, private=False):
        return self.data.get(key)

    def put(self, key, data, private=False):
        self.data[key] = data
        return True


class FakeRouter:
    def __init__(self, payload=None):
        self.prompts = []
        self.payload = payload

    def active(self):
        return ["gemini"]

    def study_activity(self, prompt):
        self.prompts.append(prompt)
        return AIResult(self.payload or {
            "em_uma_frase": "Programa de console que escreve Hello World.",
            "pedido": "Escrever Hello World no console.",
            "feito": [{"texto": "Escreve no console", "arquivos": ["HelloWorld/Program.cs"]},
                      {"texto": "Inventado", "arquivos": ["NaoExiste.cs"]}],
            "estrutura": [{"caminho": "HelloWorld", "papel": "Projeto console"},
                          {"caminho": "Fantasma/", "papel": "x"}],
            "conceitos": [{"conceito": "Saída no console", "arquivo": "HelloWorld/Program.cs",
                           "trecho": 'Console.WriteLine("Hello World");', "aulas": ["Aula-002", "Aula-999"]},
                          {"conceito": "Herança", "arquivo": "HelloWorld/Program.cs",
                           "trecho": "class A : B", "aulas": []}],
            "falta": ["README não explica como rodar"],
            "como_rodar": "dotnet run --project HelloWorld"}, "gemini", "fake")


class ActivitiesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.app = Application(self.vault, config=self.root / "none.env", log=lambda _t: None)
        self.addCleanup(self.app.close)

    def study(self):
        return StudyNotes(self.app.store, log=lambda _t: None)

    def transcript(self, name, text, summary_lesson=None):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        self.app.add_file(path)
        row = next(s for s in self.app.store.sources("transcript") if s["label"] == name)
        base = {"tipo_aula": "tecnica", "resumo": "Console e Hello World.",
                "conceitos": [{"nome": "Console", "explicacao": "Saída."}], "pessoas": [],
                "atividades": [], "ferramentas": [], "marcos": [], "exemplos": [], "duvidas": [],
                "nomes_a_conferir": []}
        self.app.store.save_analysis(row["id"], row["digest"], "offline", "x", base)
        return row

    def post(self, lesson, title, day, description=""):
        data = {"aula": lesson, "titulo": title, "data": day, "autor": "Tiago", "pessoas": "",
                "descricao": description, "atividades": "", "gravacoes": [], "_pasted_classroom": True,
                "videos": "", "links": ""}
        AutoOrganizer(self.app, log=lambda _t: None)._save_extracted(
            {"id": "post-" + lesson, "stored_path": "(post)"}, lesson, data, reason="Post")

    # ---------------------------------------------------------- parsing
    def test_classroom_post_is_parsed_into_editable_fields(self):
        parsed = parse_post(POST, reference=date(2026, 3, 20))
        self.assertEqual(parsed["title"], "[M01] Atividade 01 - Hello World em C#")
        self.assertEqual(parsed["module_code"], "M01")
        self.assertEqual(parsed["author"], "Tiago Santini de Athayde")
        self.assertEqual(parsed["posted_at"], "2026-03-03")
        self.assertEqual(parsed["due_at"], "2026-03-10")
        self.assertEqual(parsed["points"], "100")
        self.assertEqual(parsed["kind"], "atividade")
        self.assertEqual(parsed["repos"], [MY_REPO])
        self.assertIn("Console.WriteLine", parsed["description"])
        self.assertNotIn("Comentários da turma", parsed["description"])
        self.assertEqual(suggest_kind("[M02] Trabalho - Gerador de Certificados"), "trabalho")
        self.assertEqual(suggest_kind("Prova 1 - Lógica"), "prova")
        # Year inference across the turn of the year.
        self.assertEqual(parse_date("28 de dez.", date(2027, 1, 5)), "2026-12-28")
        self.assertEqual(parse_date("03/03/2026"), "2026-03-03")

    # ---------------------------------------------------------- CRUD
    def test_crud_module_from_code_grade_validation_and_delete(self):
        acts = self.study().activities
        item = acts.save({"title": "[M01] Atividade 01 - Hello World em C#", "module_code": "M01",
                          "due_at": "2026-03-10", "repos": [MY_REPO, MY_REPO + ".git", "https://evil.com/x"]})
        self.assertEqual(item["kind"], "atividade")
        self.assertEqual(item["module_id"], "logica-de-programacao")
        self.assertEqual([r["repo_url"] for r in item["repos"]], [MY_REPO])
        self.assertEqual(item["repos"][0]["owner_class"], "meu")
        with self.assertRaises(ValueError):
            acts.save({"id": item["id"], "title": "x", "grade": "dez"})
        edited = acts.save({**item, "kind": "prova", "grade": "9,5", "repos": [MY_REPO, PROF_REPO]})
        self.assertEqual(edited["grade"], "9,5")
        self.assertEqual({r["owner_class"] for r in edited["repos"]}, {"meu", "professor"})
        acts.delete(item["id"])
        self.assertEqual(acts.activities(), [])

    def test_delivered_sha_is_last_commit_until_deadline(self):
        acts = self.study().activities
        item = acts.save({"title": "Atividade 01", "due_at": "2026-03-10", "repos": [MY_REPO]})
        client = FakeClient()
        frozen = acts.freeze_repo(item["id"], MY_REPO, client)
        self.assertEqual(frozen["sha"], SHA_A)
        self.assertTrue(any("until=2026-03-10T23%3A59%3A59" in e for _, e in client.calls))
        with self.assertRaises(ValueError):
            acts.freeze_repo(item["id"], PROF_REPO, client)  # not part of the activity

    # ---------------------------------------------------------- development lessons
    def test_development_lesson_links_to_work_in_progress_by_name_or_date(self):
        self.transcript("A02 - V01 - Hello.txt", "[0:01] Console.WriteLine escreve no console.\n")
        self.post("Aula-060", "Dúvidas e ajudas", "20/05/2026")
        self.post("Aula-061", "Desenvolvimento do Gerador de Certificados", "01/07/2026")
        acts = self.study().activities
        self.assertEqual(acts.development_lessons(), ["Aula-060", "Aula-061"])
        short = acts.save({"title": "Atividade 05 - Calculadora", "posted_at": "2026-05-15",
                           "due_at": "2026-05-25"})
        work = acts.save({"title": "[M02] Trabalho - Gerador de Certificados", "posted_at": "2026-05-10",
                          "due_at": "2026-06-05"})
        links = acts.dev_links()
        self.assertEqual(links["Aula-060"], work["id"])       # trabalho wins over short exercise
        self.assertEqual(links["Aula-061"], work["id"])       # name mention, outside the window
        self.assertNotIn(short["id"], links.values())
        view = acts.view(work["id"])
        self.assertEqual([l["lesson"] for l in view["development"]], ["Aula-060", "Aula-061"])
        overview = self.study().overview()
        self.assertEqual([d["lesson"] for d in overview["development"]], ["Aula-060", "Aula-061"])

    # ---------------------------------------------------------- AI summary
    def test_activity_summary_keeps_only_points_checked_in_the_code(self):
        self.transcript("A02 - V01 - Hello.txt", "[0:01] Console.WriteLine escreve.\n")
        study = self.study()
        acts = study.activities
        item = acts.save({"title": "Atividade 01 - Hello World", "due_at": "2026-03-10",
                          "repos": [MY_REPO, PROF_REPO]})
        acts.freeze_repo(item["id"], MY_REPO, FakeClient())
        self.assertEqual(acts.status(item["id"]), "pendente")
        router = FakeRouter()
        clean = acts.generate(router, item["id"], FakeReader())
        self.assertEqual(len(router.prompts), 1)
        self.assertNotIn("x.dll", router.prompts[0].split("arquivos_com_conteudo")[1])
        self.assertEqual([f["texto"] for f in clean["feito"]], ["Escreve no console"])
        self.assertEqual([e["caminho"] for e in clean["estrutura"]], ["HelloWorld"])
        self.assertEqual([c["conceito"] for c in clean["conceitos"]], ["Saída no console"])
        self.assertEqual(clean["conceitos"][0]["aulas"], [])   # Aula-002 has no study summary here
        self.assertEqual(acts.status(item["id"]), "ok")
        acts.save({**acts.activity(item["id"]), "due_at": "2026-03-12"})
        self.assertEqual(acts.status(item["id"]), "desatualizado")
        with self.assertRaises(ValueError):
            acts.generate(FakeRouter({"em_uma_frase": "x", "pedido": "", "feito": [], "estrutura": [],
                                      "conceitos": [], "falta": [], "como_rodar": ""}),
                          item["id"], FakeReader())

    # ---------------------------------------------------------- publish
    def test_publish_writes_activity_dev_lesson_repo_and_module_pages(self):
        self.transcript("A02 - V01 - Hello.txt", "[0:01] Console.WriteLine escreve.\n")
        self.post("Aula-060", "Dúvidas e ajudas", "05/03/2026")
        study = self.study()
        acts = study.activities
        item = acts.save({"title": "[M01] Trabalho 01 - Hello World", "module_code": "M01",
                          "posted_at": "2026-03-01", "due_at": "2026-03-10", "repos": [MY_REPO, PROF_REPO]})
        acts.freeze_repo(item["id"], MY_REPO, FakeClient())
        acts.generate(FakeRouter(), item["id"], FakeReader())
        projects = Projects(study)
        projects.refresh_meta(MY_REPO, FakeClient())
        projects.tree(MY_REPO, SHA_B, FakeReader(), FakeCache())
        self.app.publisher.rebuild()
        note = (self.vault / activity_note_path(item["id"])).read_text(encoding="utf-8")
        self.assertIn("## O que foi feito", note)
        self.assertIn(f"{MY_REPO}/tree/{SHA_A}", note)                     # versão entregue
        self.assertIn(f"[repositório atual]({MY_REPO})", note)
        self.assertIn("[[04-Resumos/Aulas/Aula-060|Aula-060]]", note)
        dev = (self.vault / lesson_note_path("Aula-060")).read_text(encoding="utf-8")
        self.assertIn("Desenvolvimento", dev)
        self.assertIn(activity_note_path(item["id"])[:-3], dev)
        repo = (self.vault / repo_note_path(MY_REPO)).read_text(encoding="utf-8")
        for text in ("## Contexto para IA", "C# / .NET", "dotnet run --project HelloWorld",
                     f"{MY_REPO}/tree/{SHA_A}", "## Estrutura de pastas", "HelloWorld/",
                     "tag V0", "branch v1", "README não explica como rodar"):
            self.assertIn(text, repo)
        self.assertNotIn('Console.WriteLine("Hello World")', repo)          # no code copied
        prof = (self.vault / repo_note_path(PROF_REPO)).read_text(encoding="utf-8")
        self.assertIn("## Par", prof)
        module = (self.vault / module_note_path("logica-de-programacao")).read_text(encoding="utf-8")
        self.assertIn("## Entregas do módulo", module)
        self.assertIn("## Aulas de desenvolvimento", module)
        index = (self.vault / "04-Resumos/00-Indice.md").read_text(encoding="utf-8")
        self.assertIn("## Atividades, trabalhos e provas", index)
        # Module AI input carries the deliveries.
        data = study._module_input("logica-de-programacao")
        self.assertEqual(data["entregas"][0]["titulo"], "[M01] Trabalho 01 - Hello World")
        # Deleting an untouched activity archives its page.
        acts.delete(item["id"])
        self.app.publisher.rebuild()
        self.assertFalse((self.vault / activity_note_path(item["id"])).exists())

    # ---------------------------------------------------------- projects
    def test_projects_group_by_owner_pair_and_list_versions(self):
        study = self.study()
        acts = study.activities
        acts.save({"title": "Trabalho - Gerador de Certificados", "repos": [DUO_REPO]})
        projects = Projects(study)
        projects.register(PROF_GERADOR)
        projects.register(MY_REPO)
        overview = projects.overview()
        groups = {g["klass"]: [r["name"] for r in g["repos"]] for g in overview["groups"]}
        self.assertEqual(groups, {"meu": ["HelloWorld"], "dupla": ["gerador-de-certificados"],
                                  "professor": ["gerador-de-certificados"]})
        duo = next(r for g in overview["groups"] for r in g["repos"] if r["url"] == DUO_REPO)
        self.assertEqual([p["url"] for p in duo["pairs"]], [PROF_GERADOR])
        client = FakeClient()
        projects.refresh_meta(MY_REPO, client)
        calls = len(client.calls)
        projects.refresh_meta(MY_REPO, client)             # cached for 30 min
        self.assertEqual(len(client.calls), calls)
        kinds = [(v["kind"], v["label"]) for v in projects.repo_view(MY_REPO)["versions"]]
        self.assertEqual(kinds, [("main", "main (atual)"), ("branch", "branch v1"), ("tag", "tag V0")])
        acts.save({**acts.activities()[0], "repos": [DUO_REPO, MY_REPO]})
        acts.freeze_repo(acts.activities()[0]["id"], MY_REPO, client)
        self.assertEqual(projects.repo_view(MY_REPO)["versions"][0]["kind"], "entregue")
        # Owner reclassification in Ajustes moves the whole account.
        acts.save_owner("Marco-Oliver", "dupla")
        self.assertEqual(acts.owner_class(MY_REPO), "dupla")
        projects.remove(PROF_GERADOR)
        self.assertNotIn(PROF_GERADOR, projects.repo_urls())
        projects.register(PROF_GERADOR)
        self.assertIn(PROF_GERADOR, projects.repo_urls())

    def test_tree_is_cached_and_version_folders_are_detected(self):
        files = {"V0/Program.cs": "a", "V1/Program.cs": "b", "versao-2/x.cs": "c",
                 "src/Views/Home/Index.cshtml": "d", "README.md": "e"}
        projects = Projects(self.study())
        cache = FakeCache()
        first = FakeReader(files)
        tree = projects.tree(MY_REPO, SHA_B, first, cache)
        self.assertEqual(tree["version_folders"], ["V0", "V1", "versao-2"])
        second = FakeReader(files)
        projects.tree(MY_REPO, SHA_B, second, cache)
        self.assertEqual(second.tree_calls, 0)               # served from the local cache
        with self.assertRaises(ValueError):
            projects.tree(MY_REPO, "main", first, cache)
        self.assertIn("C# / .NET", detect_stack(["App/App.csproj", "App/Program.cs"])["stack"])
        self.assertEqual(detect_stack(["App/App.csproj"])["run"], ["dotnet run --project App"])
        self.assertIn("src/", outline(["src/a.cs", "bin/x.dll"]))
        self.assertNotIn("bin/", outline(["src/a.cs", "x/bin/y.dll"]))


class ActivityBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / "vault"
        Application(self.vault, config=Path(self.tmp.name) / "none.env", log=lambda _t: None).close()
        self.bridge = Bridge.__new__(Bridge)
        self.bridge.settings = {}
        self.bridge._write_lock = threading.Lock()
        patcher = patch.object(Bridge, "_vault", return_value=self.vault)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bridge_crud_confirmations_and_link_allowlist(self):
        with patch("knowledge_bridge.github_mapping.GithubMapping", FakeClient):
            saved = self.bridge.study_save_activity({"title": "Atividade 01", "due_at": "2026-03-10",
                                                     "repos": [MY_REPO]})
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["frozen"], 1)
        activity_id = saved["activity"]["id"]
        self.assertTrue((self.vault / activity_note_path(activity_id)).is_file())
        self.assertFalse(self.bridge.study_delete_activity(activity_id, False)["ok"])
        self.assertFalse(self.bridge.study_generate_activity(activity_id, False)["ok"])
        self.assertFalse(self.bridge.project_remove(MY_REPO, False)["ok"])
        self.assertFalse(self.bridge.study_activity("../x")["ok"])
        self.assertFalse(self.bridge.project_tree(MY_REPO, "main")["ok"])
        self.assertFalse(self.bridge.project_repo("https://evil.com/a/b")["ok"])
        parsed = self.bridge.study_parse_activity(POST)
        self.assertEqual(parsed["parsed"]["module_code"], "M01")
        opened = []
        with patch("knowledge_bridge.bridge.webbrowser.open", lambda url: opened.append(url) or True):
            self.assertTrue(self.bridge.open_study_link(f"{MY_REPO}/tree/{SHA_A}")["ok"])
            self.assertTrue(self.bridge.open_study_link(f"{MY_REPO}/blob/{SHA_A}/HelloWorld/Program.cs")["ok"])
            self.assertFalse(self.bridge.open_study_link("https://github.com/someone/else")["ok"])
            self.assertFalse(self.bridge.open_study_link("javascript:alert(1)")["ok"])
        self.assertEqual(len(opened), 2)
        owners = self.bridge.project_save_owner("netos-do-velho-barrero", "dupla", "Netos")
        self.assertTrue(owners["ok"])
        overview = self.bridge.projects_overview()
        self.assertEqual(overview["groups"][0]["klass"], "meu")
        self.assertTrue(self.bridge.study_delete_activity(activity_id, True)["ok"])

    def test_packaged_ui_contains_projects_view(self):
        from knowledge_bridge.bridge import load_local_ui
        html = load_local_ui()
        for marker in ("projects-workspace", "renderProjectsView", "study-activity-dialog",
                       "project-add-dialog", "owners-setting", ".pfi-cs", "projectsOwnersMount"):
            self.assertIn(marker, html)
        self.assertNotIn('src="projects.js"', html)


if __name__ == "__main__":
    unittest.main()


class ImportActivityTests(unittest.TestCase):
    """Colar o post de atividade em Importar e organizar cria a atividade."""
    PASTE = """[M01] Atividade 01 - Hello World em C#
Alexandre Rech
3 de mar.
Data de entrega: 4 de mar., 14:00
[M01] Atividade 01 - Hello World em C#
"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = Application(self.root / "vault", config=self.root / "none.env", log=lambda _t: None)
        self.addCleanup(self.app.close)

    def test_paste_parser_returns_activity_block_without_warnings(self):
        from knowledge_bridge.classroom_paste import parse_import_paste
        result = parse_import_paste(self.PASTE + MY_REPO + "\n")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["activities"]), 1)
        mixed = parse_import_paste("Aula 03 - Variáveis\nTiago Santini\nAgenda: 05/03/2026\n"
                                   "Atividades:\nAtividade 02 - Calculadora\n" + self.PASTE)
        self.assertEqual(len(mixed["posts"]), 1)            # lesson post keeps its own activities section
        self.assertIn("Calculadora", mixed["posts"][0]["atividades"])
        self.assertEqual(len(mixed["activities"]), 1)

    def test_import_creates_activity_and_attaches_loose_repo(self):
        from knowledge_bridge.auto_ingest import AutoOrganizer
        with patch("knowledge_bridge.github_mapping.GithubMapping", FakeClient):
            result = AutoOrganizer(self.app, log=lambda _t: None).run(
                [], self.PASTE + "\n" + MY_REPO, authorized=True)
        self.assertEqual(result["activities"], 1)
        acts = StudyNotes(self.app.store, log=lambda _t: None).activities
        [activity] = acts.activities()
        self.assertEqual(activity["author"], "Alexandre Rech")
        self.assertTrue(activity["due_at"].endswith("-03-04"))
        self.assertEqual(activity["module_id"], "logica-de-programacao")
        self.assertEqual([r["repo_url"] for r in activity["repos"]], [MY_REPO])
        self.assertEqual(activity["repos"][0]["sha"], SHA_A)
        self.assertTrue((self.root / "vault" / activity_note_path(activity["id"])).is_file())
        # Pasting it again completes, never duplicates.
        with patch("knowledge_bridge.github_mapping.GithubMapping", FakeClient):
            AutoOrganizer(self.app, log=lambda _t: None).run([], self.PASTE, authorized=True)
        self.assertEqual(len(StudyNotes(self.app.store, log=lambda _t: None).activities.activities()), 1)

    def test_bare_date_line_prefers_the_past(self):
        parsed = parse_post(self.PASTE, reference=date(2026, 11, 9))
        self.assertEqual(parsed["posted_at"], "2026-03-03")
        self.assertEqual(parsed["due_at"], "2026-03-04")
        self.assertEqual(parsed["description"], "")


class ImportPreviewTests(unittest.TestCase):
    def test_preview_counts_without_side_effects(self):
        bridge = Bridge.__new__(Bridge)
        r = bridge.preview_import("Aula 05 - Condicionais\nTiago Santini\nA05 - V01 - If\n"
                                  "https://drive.google.com/file/d/x/view\n" + ImportActivityTests.PASTE +
                                  MY_REPO + "\nlinha solta qualquer\n")
        self.assertTrue(r["ok"])
        self.assertEqual([p["lesson"] for p in r["posts"]], ["Aula-005"])
        self.assertEqual(r["activities"][0]["kind"], "Atividade")
        self.assertEqual(r["activities"][0]["repos"], 1)
        self.assertEqual(r["videos"], 1)
        self.assertFalse(bridge.preview_import("x" * 40000)["ok"])
