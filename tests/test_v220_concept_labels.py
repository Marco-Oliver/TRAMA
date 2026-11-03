"""Real user-feedback regressions: V01 summary and technical name labels.

All transcriptions below are SYNTHETIC fixtures. No external AI calls and no
changes to a user's Obsidian vault are performed.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_bridge.memory_atlas import literal_technical_mention
from knowledge_bridge.pipeline import Application
from knowledge_bridge.bridge import Bridge


class TechnicalLabelGroundingTests(unittest.TestCase):
    def test_explicit_abbreviation_and_command_not_rejected(self):
        transcript=(
            "[0:01] Instalamos o .NET SDK 10, que é uma versão LTS.\n"
            "[0:03] Abra o terminal e execute dotnet --version.\n"
        )
        labels={
            "SDK (Software Development Kit)":"SDK",
            "LTS (Long-Term Support)":"LTS",
            "Comando dotnet --version":"dotnet --version",
        }
        for label,expected in labels.items():
            with self.subTest(label=label):
                self.assertEqual(literal_technical_mention(label,transcript),expected)
        self.assertEqual(literal_technical_mention("GraphQL",transcript),"")
        self.assertEqual(literal_technical_mention(
            "exhaustMap", "[0:01] O áudio capturou exaust map."),"")

        result=Application._clean_result({
            "resumo":"Instalação e verificação do SDK do .NET.",
            "tipo_aula":"tecnica",
            "conceitos":[{"nome":key,"explicacao":"Interpretação da IA."}
                        for key in [*labels,"GraphQL"]]
        },transcript)
        self.assertEqual(
            {x["nome"] for x in result["conceitos"]},set(labels))
        self.assertEqual(
            {x["nome"] for x in result["conceitos_a_conferir"]},{"GraphQL"})

    def test_legacy_cached_v01_is_clarified_locally_without_new_ai_calls(self):
        with tempfile.TemporaryDirectory(prefix="trama-v220-v01-legacy-") as folder:
            base=Path(folder)
            app=Application(base/"Obsidian",base/"no-provider.env",log=lambda *_:None)
            try:
                source=base/"A02 - V01 - Instalacao do .NET SDK.txt"
                source.write_text(
                    "[0:01] Vamos instalar o SDK .NET 10, versão LTS.\n"
                    "[0:08] No terminal, use dotnet --version para conferir a instalação.\n",
                    encoding="utf-8"
                )
                self.assertTrue(app.add_file(source))
                src=next(s for s in app.store.sources("transcript")
                         if s["label"]==source.name)
                app.store.save_analysis(src["id"],src["digest"],"fixture","offline",{
                    "resumo":"O material mostra instalação e verificação do SDK.",
                    "tipo_aula":"tecnica","conceitos":[],"pessoas":[],
                    "conceitos_a_conferir":[
                        {"nome":"SDK (Software Development Kit)",
                         "motivo":"Nome completo não encontrado literalmente."},
                        {"nome":"LTS (Long-Term Support)",
                         "motivo":"Nome completo não encontrado literalmente."},
                        {"nome":"Comando dotnet --version",
                         "motivo":"Nome completo não encontrado literalmente."},
                        {"nome":"GraphQL","motivo":"Sem suporte na aula."},
                    ],
                    "duvidas":[],"exemplos":[],
                })
                app.publisher.rebuild()  # NO provider is configured or invoked
                overview=(app.store.vault/"02-Minhas-Aulas/Aula-002/00-Visao-geral.md"
                          ).read_text(encoding="utf-8")
                self.assertIn("Termos técnicos presentes no TXT",overview)
                self.assertIn("SDK (Software Development Kit)",overview)
                self.assertIn("dotnet --version",overview)
                self.assertNotIn("Nenhum conceito técnico comprovado",overview)
                note=next(x for x in (app.store.vault/"02-Minhas-Aulas/Aula-002").glob("*.md")
                          if x.name!="00-Visao-geral.md")
                detail=note.read_text(encoding="utf-8")
                self.assertIn("Termos técnicos mencionados",detail)
                self.assertIn("forma observada: `SDK`",detail)
                self.assertIn("Termos sugeridos pela IA para conferir",detail)
                self.assertIn("GraphQL",detail)
                self.assertFalse((app.store.vault/"01-Meu-Conhecimento/Conceitos/graphql.md").exists())
            finally:
                app.close()

    def test_note_related_entries_expose_person_or_technical_type(self):
        with tempfile.TemporaryDirectory(prefix="trama-v220-kind-") as folder:
            vault=Path(folder)/"vault"
            lesson=vault/"02-Minhas-Aulas/Aula-002/00-Visao-geral.md"
            person=vault/"01-Meu-Conhecimento/Pessoas/alec.md"
            concept=vault/"01-Meu-Conhecimento/Conceitos/dotnet-sdk.md"
            for file in (lesson,person,concept):
                file.parent.mkdir(parents=True,exist_ok=True)
            lesson.write_text("# Aula 002\n\n[[alec]]\n[[dotnet-sdk]]",
                              encoding="utf-8")
            person.write_text("---\ntipo: 'pessoa'\n---\n# Alec\n",
                              encoding="utf-8")
            concept.write_text("---\ntipo: 'conceito'\n---\n# .NET SDK\n",
                               encoding="utf-8")
            bridge=Bridge()
            bridge.settings={"vault":str(vault)}
            result=bridge.note("02-Minhas-Aulas/Aula-002/00-Visao-geral.md")
            kinds={r["title"]:r["kind"] for r in result["related"]}
            self.assertEqual(kinds["Alec"],"pessoa")
            self.assertEqual(kinds[".NET SDK"],"conceito")


if __name__=="__main__":
    unittest.main()
