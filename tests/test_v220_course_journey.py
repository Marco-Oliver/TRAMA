"""End-to-end TRAMA journey. Synthetic lesson speech; local Git repository.

Source-code concepts mirror public Angular classes/services/guards observed in
academiadoprogramador-fullstack/gerador-de-certificados-2026 at commit
cd86334568a034c9847b34e1e0e9841381fc31a1.
NO classroom audio, real teacher speech, user vault or external AI is used.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.ai import AIResult
from knowledge_bridge.pipeline import Application
from knowledge_bridge.recovery import create_backup, restore_backup
from knowledge_bridge.code_intel import match_lesson_to_repository


class OfflineStudyProvider:
    """Deterministic response for mechanical checks, NOT model-quality evidence."""

    def __init__(self):
        self.analyze_calls: list[str] = []
        self.compare_calls = 0

    def analyze(self, transcript: str, context: str) -> AIResult:
        self.analyze_calls.append(context)
        if "Aula-031" in context:
            payload = {
                "resumo": (
                    "O material introduziu um serviço Angular e o uso de HttpClient. "
                    "A transcrição apresenta uma dúvida sobre injeção e não explica "
                    "o mecanismo; portanto o ponto permanece para revisão."
                ),
                "conceitos": [{
                    "nome": "HttpClient",
                    "explicacao": "Foi mencionado como dependência HTTP de um serviço.",
                    "tempo": "0:01",
                }],
                "duvidas": ["Como funciona a injeção de HttpClient?"],
            }
        elif "Aula-049" in context:
            payload = {
                "resumo": (
                    "Este material trata de guards de autenticação e condições "
                    "para entrar em páginas. Não contém uma explicação de HttpClient."
                ),
                "conceitos": [{
                    "nome": "CanActivateFn",
                    "explicacao": "Foi citado como tipo de função de proteção de rotas.",
                    "tempo": "0:01",
                }],
                "duvidas": [],
            }
        else:
            payload = {
                "resumo": (
                    "O material mostra como um serviço Angular recebe HttpClient "
                    "pela função inject. Apresenta um exemplo de requisição HTTP "
                    "e conecta a explicação ao exemplo de serviço."
                ),
                "conceitos": [
                    {
                        "nome": "HttpClient",
                        "explicacao": "É utilizado pelo serviço no exemplo de HTTP.",
                        "tempo": "0:01",
                    },
                    {
                        "nome": "inject",
                        "explicacao": "É a função empregada para obter HttpClient.",
                        "tempo": "0:02",
                    },
                ],
                "duvidas": [],
            }
        payload = {
            "tipo_aula": "tecnica", "pessoas": [], "atividades": [],
            "ferramentas": [], "marcos": [], "exemplos": [],
            "nomes_a_conferir": [], **payload,
        }
        return AIResult(payload, "fixture-local", "roteiro-deterministico")

    def compare(self, *_args, **_kwargs) -> AIResult:
        self.compare_calls += 1
        return AIResult(
            {"resumo": "Somente relações literais devem ser consideradas.",
             "relacoes": [], "correcoes": [], "novidades": []},
            "fixture-local", "roteiro-deterministico"
        )


class ThreeLessonCourseJourneyTests(unittest.TestCase):
    def test_import_context_backup_and_restore_without_real_data(self):
        with tempfile.TemporaryDirectory(prefix="trama-v220-course-journey-") as folder:
            root = Path(folder)
            vault = root / "Cofre Obsidian de Teste"
            material = root / "transcricoes-exemplo"
            material.mkdir()
            provider = OfflineStudyProvider()
            app = Application(vault, root / "sem-chave-externa.env", log=lambda *_: None)
            app.ai = provider

            def add_lesson(number: int, text: str) -> Path:
                source = material / f"Aula-{number:03d}-V01.txt"
                source.write_text(text, encoding="utf-8")
                self.assertTrue(app.add_file(source))
                return source

            def note_for(number: int) -> Path:
                folder = vault / "02-Minhas-Aulas" / f"Aula-{number:03d}"
                options = [p for p in folder.glob("*.md")
                           if p.name != "00-Visao-geral.md" and ".PROPOSTA" not in p.name]
                self.assertEqual(len(options), 1, f"Unexpected note count: {options}")
                return options[0]

            try:
                src31 = add_lesson(31, (
                    "[0:01] Aqui temos um serviço Angular com HttpClient.\n"
                    "[0:03] Ainda ficou em aberto como esse HttpClient chega ao serviço.\n"
                    "[0:04] Vamos continuar a estrutura de outros componentes."
                ))
                app.process()
                self.assertEqual(len(provider.analyze_calls), 1)
                note31 = note_for(31)
                before = note31.read_text(encoding="utf-8")
                self.assertIn("HttpClient", before)
                self.assertIn("Como funciona a injeção de HttpClient?", before)

                # Unrelated lesson must neither explain nor revisit Aula 031.
                add_lesson(49, (
                    "[0:01] Hoje trataremos de guardas de rota, CanActivateFn "
                    "e condições de sessão autenticada.\n"
                    "[0:03] A rota pode redirecionar para o login."
                ))
                app.process()
                self.assertEqual(len(provider.analyze_calls), 2)
                still_open = note31.read_text(encoding="utf-8")
                self.assertNotIn("Aula-049", still_open)

                # A short local Git fixture reuses observed public-course
                # architecture. It is not a full clone or a teacher transcript.
                project = root / "gerador-de-certificados-exemplo"
                auth = project / "client/src/app/auth/auth.service.ts"
                auth.parent.mkdir(parents=True)
                auth.write_text(
                    "import { HttpClient } from '@angular/common/http';\n"
                    "import { inject } from '@angular/core';\n"
                    "export class AuthService {\n"
                    "  private readonly http = inject(HttpClient);\n"
                    "}\n", encoding="utf-8"
                )
                course = project / "client/src/app/cursos/cursos.service.ts"
                course.parent.mkdir(parents=True)
                course.write_text(
                    "import { HttpClient } from '@angular/common/http';\n"
                    "import { inject } from '@angular/core';\n"
                    "export class CursosService {\n"
                    "  private readonly http = inject(HttpClient);\n"
                    "}\n", encoding="utf-8"
                )
                env = dict(os.environ, GIT_AUTHOR_NAME="TRAMA Fixture",
                           GIT_AUTHOR_EMAIL="fixture@example.invalid",
                           GIT_COMMITTER_NAME="TRAMA Fixture",
                           GIT_COMMITTER_EMAIL="fixture@example.invalid")
                for cmd in (["git", "init", "-q", str(project)],
                            ["git", "-C", str(project), "add", "--", "."],
                            ["git", "-C", str(project), "-c", "commit.gpgsign=false",
                             "commit", "-q", "-m", "synthetic test source"]):
                    subprocess.run(cmd, env=env, check=True, timeout=40,
                                   capture_output=True)
                self.assertTrue(app.add_repo(str(project)))
                self.assertFalse(app.add_repo(str(project)))  # same SHA
                repositories = app.store.repositories()
                self.assertEqual(len(repositories), 1)
                repo_payload = json.loads(repositories[0]["payload"])
                symbols = {s["name"] for s in repo_payload.get("symbols", [])}
                self.assertTrue({"AuthService", "CursosService"}.issubset(symbols))
                self.assertTrue(match_lesson_to_repository(
                    "O AuthService usa HttpClient.", None, repo_payload
                ))

                add_lesson(50, (
                    "[0:01] Agora o HttpClient é usado no AuthService Angular.\n"
                    "[0:02] A função inject(HttpClient) fornece a dependência "
                    "para o serviço.\n"
                    "[0:04] Podemos então realizar requisições HTTP."
                ))
                app.process()
                self.assertEqual(len(provider.analyze_calls), 3,
                                 "Older lessons were re-sent for processing")
                self.assertEqual(len(app.store.sources("transcript")), 3)
                self.assertIn("Aula-050", note31.read_text(encoding="utf-8"))
                self.assertIn("revisar", note31.read_text(encoding="utf-8").lower())

                # All summaries and original attachments must survive a repeat.
                path50 = note_for(50)
                text50 = path50.read_text(encoding="utf-8")
                app.process()
                self.assertEqual(len(provider.analyze_calls), 3)
                self.assertEqual(path50.read_text(encoding="utf-8"), text50)
                original_bytes = [src31.read_bytes(), note31.read_bytes()]

                # Human edit cannot be lost; generated alternative is a proposal.
                note31.write_text(before + "\n\n## Minha observação pessoal\n"
                                  "Ainda quero revisar este exemplo.\n",
                                  encoding="utf-8")
                app.publisher.rebuild()
                self.assertIn("Minha observação pessoal",
                              note31.read_text(encoding="utf-8"))
                proposals = list(note31.parent.glob(note31.stem + ".PROPOSTA*.md"))
                self.assertTrue(proposals, "Expected protected proposed revision")
                self.assertIn("Aula-050",
                              "\n".join(p.read_text(encoding="utf-8")
                                        for p in proposals))

                # Full vault snapshot should restore in another isolated folder.
                backup = root / "trama-backup.zip"
                result = create_backup(vault, backup)
                self.assertTrue(result["ok"])
                restored = root / "Restauracao de Teste"
                recovery = restore_backup(backup, restored)
                self.assertTrue(recovery["ok"])
                relative = note31.relative_to(vault)
                self.assertEqual((restored / relative).read_bytes(),
                                 note31.read_bytes())
                self.assertEqual((restored / path50.relative_to(vault)).read_bytes(),
                                 text50.encode("utf-8"))
                self.assertIn("Aula-031", str(relative))
                self.assertEqual(original_bytes[0], src31.read_bytes())
                self.assertTrue((vault / ".base-conhecimento/estado.sqlite3").is_file())
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
