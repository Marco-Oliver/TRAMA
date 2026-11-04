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


class EvidenceNavigationRegressionTests(unittest.TestCase):
    """Real disk round trips with synthetic TXT. No provider or real vault."""

    def _create(self, base: Path, transcript: str, concepts: list, people: list | None = None):
        app = Application(base / "cofre-de-teste", base / "sem-chave.env", log=lambda *_: None)
        original = base / "A02 - V01 - Instalacao do .NET SDK.txt"
        original.write_text(transcript, encoding="utf-8")
        self.assertTrue(app.add_file(original))
        src = next(s for s in app.store.sources("transcript") if s["label"] == original.name)
        app.store.save_analysis(src["id"], src["digest"], "fixture", "offline", {
            "resumo": "O instrutor apresenta SDK, LTS e o ambiente .NET.",
            "tipo_aula": "tecnica", "conceitos": concepts,
            "pessoas": people or [], "duvidas": [], "exemplos": [],
        })
        app.publisher.rebuild()
        return app, src, original

    def test_missing_ai_times_use_only_verified_source_segments(self):
        from knowledge_bridge.content import concept_slug
        from knowledge_bridge.memory_atlas import note_for
        with tempfile.TemporaryDirectory(prefix="trama-verified-anchor-") as folder:
            base=Path(folder)
            raw=("[0:01] Alec apresenta o .NET SDK versão LTS.\n"
                 "[0:07] SDK significa software development kit.\n"
                 "[0:10] LTS é uma modalidade de suporte de longo prazo.\n"
                 "[0:12] Confira com dotnet --version no terminal.\n")
            concepts=[
                {"nome":"SDK (Software Development Kit)",
                 "explicacao":"Kit de ferramentas para desenvolver.", "tempo":""},
                {"nome":"LTS (Long-Term Support)",
                 "explicacao":"Suporte estendido.", "tempo":"8:88"},
                {"nome":"Comando dotnet --version",
                 "explicacao":"Mostra a versão instalada.", "tempo":""},
            ]
            app,src,original=self._create(base,raw,concepts,[{"nome":"Alec"}])
            try:
                vault=app.store.vault
                sdk=(vault/"01-Meu-Conhecimento/Conceitos"/
                     (concept_slug(concepts[0]["nome"])+".md")).read_text(encoding="utf-8")
                lts=(vault/"01-Meu-Conhecimento/Conceitos"/
                     (concept_slug(concepts[1]["nome"])+".md")).read_text(encoding="utf-8")
                command=(vault/"01-Meu-Conhecimento/Conceitos"/
                         (concept_slug(concepts[2]["nome"])+".md")).read_text(encoding="utf-8")
                source=(vault/note_for(src)).read_text(encoding="utf-8")
                self.assertIn("Menção literal na transcrição",sdk)
                self.assertIn("#^min-0-07|0:07",sdk)
                self.assertIn("#^min-0-10|0:10",lts)
                self.assertIn("#^min-0-12|0:12",command)
                for stamp in ["0-07","0-10","0-12"]:
                    self.assertIn("^min-"+stamp,source)
                self.assertNotIn("horário não localizado",sdk+lts+command)
                self.assertIn("horários acima recuperados diretamente do TXT",lts)
                self.assertEqual(original.read_text(encoding="utf-8"),raw)

                bridge=Bridge()
                bridge.settings={"vault":str(vault)}
                lesson=bridge.note("02-Minhas-Aulas/Aula-002/00-Visao-geral.md")
                self.assertIn("SDK",lesson["concepts"])
                self.assertNotIn("Alec",lesson["concepts"])
                self.assertIn("Alec",lesson["content"])
                concept=bridge.note(
                    "01-Meu-Conhecimento/Conceitos/"+
                    concept_slug(concepts[1]["nome"])+".md")
                self.assertIn("Suporte estendido",concept["summary"])
                self.assertIn("Menção literal na transcrição",concept["summary"])
                self.assertEqual(concept["concepts"],"")
            finally:
                app.close()

    def test_no_timestamp_is_not_invented_and_original_is_preserved(self):
        from knowledge_bridge.content import concept_slug
        from knowledge_bridge.memory_atlas import note_for
        with tempfile.TemporaryDirectory(prefix="trama-no-false-time-") as folder:
            base=Path(folder)
            raw="Falamos de SDK e bibliotecas, sem marcadores de tempo."
            label="SDK (Software Development Kit)"
            app,src,original=self._create(
                base,raw,[{"nome":label,"explicacao":"Kit de desenvolvimento."}])
            try:
                vault=app.store.vault
                concept_path=vault/"01-Meu-Conhecimento/Conceitos"/(concept_slug(label)+".md")
                note=concept_path.read_text(encoding="utf-8")
                self.assertIn("sem trecho com horário verificável",note)
                self.assertNotIn("#^min-",note)
                source=(vault/note_for(src)).read_text(encoding="utf-8")
                self.assertNotIn("^min-",source)
                self.assertEqual(original.read_text(encoding="utf-8"),raw)
                # Rebuilding never overwrites a human edit, and avoids
                # accumulating duplicate proposals when the output is stable.
                concept_path.write_text("# Minhas anotações pessoais\n",encoding="utf-8")
                app.publisher.rebuild()
                self.assertEqual(concept_path.read_text(encoding="utf-8"),
                                 "# Minhas anotações pessoais\n")
                proposals=list(concept_path.parent.glob(concept_path.stem+".PROPOSTA*.md"))
                self.assertEqual(len(proposals),1)
                app.publisher.rebuild()
                self.assertEqual(len(list(
                    concept_path.parent.glob(concept_path.stem+".PROPOSTA*.md"))),1)
            finally:
                app.close()

    def test_repeated_timestamp_links_to_the_specific_spoken_line(self):
        from knowledge_bridge.content import concept_slug
        from knowledge_bridge.memory_atlas import note_for
        with tempfile.TemporaryDirectory(prefix="trama-duplicate-timestamps-") as folder:
            base = Path(folder)
            transcript = (
                "[0:04] Primeiro falamos de uma apresentação administrativa.\n"
                "[0:04] LTS é suporte prolongado nas versões .NET.\n"
                "[0:05] SDK é o kit de desenvolvimento.\n"
            )
            label = "LTS (Long-Term Support)"
            app, source, original = self._create(
                base, transcript,
                [{"nome": label, "explicacao": "Conceito citado, analisar.", "tempo": "0:04"}]
            )
            try:
                vault = app.store.vault
                concept = (vault/"01-Meu-Conhecimento/Conceitos"/
                           (concept_slug(label)+".md")).read_text(encoding="utf-8")
                note = (vault/note_for(source)).read_text(encoding="utf-8")
                self.assertIn("#^min-0-04-2|0:04", concept)
                self.assertIn("^min-0-04-1", note)
                self.assertIn("^min-0-04-2", note)
                self.assertIn("apresentação administrativa.", note)
                self.assertIn("LTS é suporte prolongado", note)
                self.assertNotIn("#^min-0-04-1|0:04", concept)
                self.assertEqual(original.read_text(encoding="utf-8"), transcript)
                app.publisher.rebuild()
                self.assertEqual(note, (vault/note_for(source)).read_text(encoding="utf-8"))
            finally:
                app.close()

    def test_long_source_sentence_cites_context_near_the_observed_term(self):
        from knowledge_bridge.content import concept_slug
        from knowledge_bridge.memory_atlas import note_for
        with tempfile.TemporaryDirectory(prefix="trama-long-mention-") as folder:
            base = Path(folder)
            transcript = (
                "[0:08] " + ("histórico de instalação e preparação do ambiente. " * 22)
                + " LTS é a sigla de suporte prolongado.\n"
            )
            label = "LTS (Long-Term Support)"
            app, source, original = self._create(
                base, transcript,
                [{"nome": label, "explicacao": "Interpretação para revisar."}]
            )
            try:
                vault = app.store.vault
                concept = (vault/"01-Meu-Conhecimento/Conceitos"/
                           (concept_slug(label)+".md")).read_text(encoding="utf-8")
                note = (vault/note_for(source)).read_text(encoding="utf-8")
                self.assertIn("#^min-0-08|0:08", concept)
                self.assertIn("LTS é a sigla de suporte prolongado", concept)
                excerpt = next(
                    line for line in note.splitlines() if " ^min-0-08" in line
                )
                self.assertIn("LTS", excerpt)
                self.assertIn("…", excerpt)
                self.assertEqual(original.read_text(encoding="utf-8"), transcript)
            finally:
                app.close()

    def test_hand_edited_source_points_to_proposed_anchor_not_a_broken_note(self):
        from knowledge_bridge.content import concept_slug
        from knowledge_bridge.memory_atlas import note_for
        with tempfile.TemporaryDirectory(prefix="trama-protected-timed-note-") as folder:
            base = Path(folder)
            raw = "[0:11] SDK significa Software Development Kit.\n"
            label = "SDK (Software Development Kit)"
            app, source, original = self._create(
                base, raw, [{"nome": label,
                             "explicacao": "Termo explicado, revisar.", "tempo": ""}]
            )
            try:
                vault = app.store.vault
                source_note = vault / note_for(source)
                source_note.write_text(
                    "# Minha nota pessoal da aula\n\nTexto escrito por mim.\n",
                    encoding="utf-8"
                )
                app.publisher.rebuild()
                self.assertEqual(source_note.read_text(encoding="utf-8"),
                                 "# Minha nota pessoal da aula\n\nTexto escrito por mim.\n")
                proposals = sorted(source_note.parent.glob(
                    source_note.stem + ".PROPOSTA*.md"))
                self.assertEqual(len(proposals), 1)
                self.assertIn("^min-0-11",
                              proposals[0].read_text(encoding="utf-8"))
                concept = (vault/"01-Meu-Conhecimento/Conceitos"/
                           (concept_slug(label)+".md")).read_text(encoding="utf-8")
                target = proposals[0].relative_to(vault).with_suffix("").as_posix()
                self.assertIn(target+"#^min-0-11|0:11", concept)
                self.assertIn("proposta de atualização", concept)
                self.assertNotIn(
                    source_note.relative_to(vault).with_suffix("").as_posix()+
                    "#^min-0-11|0:11", concept
                )
                self.assertEqual(original.read_text(encoding="utf-8"), raw)
            finally:
                app.close()

    def test_sdk_and_lts_prefer_explanations_with_original_neighboring_lines(self):
        from knowledge_bridge.content import concept_slug
        from knowledge_bridge.memory_atlas import note_for
        with tempfile.TemporaryDirectory(prefix="trama-full-context-") as folder:
            root = Path(folder)
            raw = (
                "[0:40] Estes programas aqui, o DNET SDK, o VS.\n"
                "[2:07] Fazer o .NET SDK, eu vou entrar aqui no.\n"
                "[3:05] O SDK se chama Software Development Kit.\n"
                "[3:10] É um conjunto de ferramentas do ambiente de desenvolvimento.\n"
                "[3:16] Você instala esse kit antes de compilar seu primeiro projeto.\n"
                "[6:11] LTS significa que a Microsoft vai estender.\n"
                "[6:18] O suporte desta versão por um período mais longo.\n"
                "[6:27] Compare as versões antes de escolher qual instalar.\n"
                "[10:00] Voltamos para outro assunto sem relação.\n"
            )
            concepts = [
                {"nome": "SDK (Software Development Kit)",
                 "explicacao": "Kit de desenvolvimento, interpretação da IA.", "tempo": ""},
                {"nome": "LTS (Long-Term Support)",
                 "explicacao": "Três anos de suporte, não confirmados na fonte.",
                 "tempo": ""},
            ]
            app, source, original = self._create(root, raw, concepts)
            try:
                vault = app.store.vault
                sdk = (vault/"01-Meu-Conhecimento/Conceitos"/
                       (concept_slug(concepts[0]["nome"])+".md")).read_text(
                           encoding="utf-8")
                lts = (vault/"01-Meu-Conhecimento/Conceitos"/
                       (concept_slug(concepts[1]["nome"])+".md")).read_text(
                           encoding="utf-8")
                source_note = (vault/note_for(source)).read_text(encoding="utf-8")
                # The explanatory SDK sentence must outrank the earlier
                # "we are installing programs" mentions.
                sdk_pos = sdk.index("Menção literal na transcrição")
                self.assertIn("#^min-3-05|3:05",sdk[sdk_pos:sdk_pos+210])
                self.assertIn("3:10 — É um conjunto de ferramentas",sdk)
                self.assertIn("3:16 — Você instala esse kit",sdk)
                # LTS source context crosses short ASR-timestamp segments.
                lts_pos = lts.index("Menção literal na transcrição")
                self.assertIn("#^min-6-11|6:11",lts[lts_pos:lts_pos+210])
                self.assertIn("6:18 — O suporte desta versão",lts)
                self.assertIn("6:27 — Compare as versões",lts)
                self.assertNotIn("10:00 — Voltamos",lts)
                self.assertIn("não valida automaticamente a explicação da IA",lts)
                self.assertIn("^min-3-05",source_note)
                self.assertIn("^min-6-11",source_note)
                self.assertEqual(raw,original.read_text(encoding="utf-8"))
            finally:
                app.close()

    def test_source_passages_are_chronological_readable_and_not_repeated(self):
        from knowledge_bridge.content import concept_slug
        with tempfile.TemporaryDirectory(prefix="trama-reading-passages-") as folder:
            base=Path(folder)
            transcript=(
                "[0:40] Estes programas aqui, o SDK, o VS.\n"
                "[3:06] Bem específico, SDK. O que é SDK?\n"
                "[3:10] SDK se chama Software Development Kit.\n"
                "[3:15] O que nós vamos instalar.\n"
                "[3:17] Vai ser um kit de desenvolvimento.\n"
                "[3:18] De software do .NET.\n"
                "[6:11] LTS significa que a Microsoft vai estar.\n"
                "[6:14] Suportando essa versão por alguns.\n"
                "[6:15] Anos, geralmente o suporte dessa.\n"
                "[6:18] Versão LTS, aliás, tá?\n"
                "[6:20] Elas duram mais ou menos 3 anos.\n"
                "[6:24] E depois vamos para outra versão.\n"
            )
            names=["SDK (Software Development Kit)", "LTS (Long-Term Support)"]
            app,source,original=self._create(base,transcript,[
                {"nome":name,"explicacao":"Hipótese de definição da IA.", "tempo":""}
                for name in names])
            try:
                folder=app.store.vault/"01-Meu-Conhecimento/Conceitos"
                sdk=(folder/(concept_slug(names[0])+".md")).read_text(encoding="utf-8")
                lts=(folder/(concept_slug(names[1])+".md")).read_text(encoding="utf-8")
                self.assertEqual(sdk.count("Menção literal na transcrição"), 1)
                self.assertIn("#^min-3-06|3:06",sdk)
                self.assertIn("  > - 3:06 —",sdk)
                self.assertIn("  > - 3:10 —",sdk)
                self.assertIn("  > - 3:18 —",sdk)
                self.assertLess(sdk.index("  > - 3:06"),sdk.index("  > - 3:10"))
                self.assertEqual(sdk.count("  > - 3:10 —"),1)
                self.assertEqual(lts.count("Menção literal na transcrição"),1)
                self.assertIn("#^min-6-11|6:11",lts)
                self.assertIn("  > - 6:18 —",lts)
                self.assertIn("  > - 6:24 —",lts)
                self.assertEqual(lts.count("  > - 6:18 —"),1)
                self.assertIn("trechos originais em sequência",lts)
                self.assertEqual(original.read_text(encoding="utf-8"),transcript)
            finally:
                app.close()

    def test_separate_distant_explanations_stay_independent(self):
        from knowledge_bridge.content import concept_slug
        with tempfile.TemporaryDirectory(prefix="trama-separated-explanations-") as folder:
            label="SDK (Software Development Kit)"
            raw=(
                "[1:00] SDK significa kit de desenvolvimento.\n"
                "[1:04] Primeiro instalamos as ferramentas.\n"
                "[12:00] No segundo exemplo SDK permite compilar o projeto.\n"
                "[12:05] Este é outro assunto da mesma aula.\n"
            )
            app,_,_=self._create(Path(folder),raw,[{
                "nome":label,"explicacao":"Definição para conferir.", "tempo":""}])
            try:
                result=(app.store.vault/"01-Meu-Conhecimento/Conceitos"/
                    (concept_slug(label)+".md")).read_text(encoding="utf-8")
                self.assertEqual(result.count("Menção literal na transcrição"),2)
                self.assertIn("#^min-1-00|1:00",result)
                self.assertIn("#^min-12-00|12:00",result)
                self.assertLess(result.index("  > - 1:00"),result.index("  > - 12:00"))
            finally:
                app.close()

    def test_context_does_not_join_distant_segments_or_invent_explanation(self):
        from knowledge_bridge.content import concept_slug
        with tempfile.TemporaryDirectory(prefix="trama-gap-context-") as folder:
            label="LTS (Long-Term Support)"
            raw=("[0:01] Falamos de uma versão LTS.\n"
                 "[12:34] Mudamos de assunto e demonstramos outro recurso.\n")
            app,_,_=self._create(Path(folder),raw,[
                {"nome":label,"explicacao":"Interpretação que requer conferência."}
            ])
            try:
                content=(app.store.vault/"01-Meu-Conhecimento/Conceitos"/
                         (concept_slug(label)+".md")).read_text(encoding="utf-8")
                self.assertIn("0:01 — Falamos de uma versão LTS",content)
                self.assertNotIn("12:34 — Mudamos",content)
                self.assertIn("não valida automaticamente a explicação",content)
            finally:
                app.close()

    def test_audit_recognizes_literal_abbreviations_and_recovered_times(self):
        from knowledge_bridge.audit import audit_lesson
        with tempfile.TemporaryDirectory(prefix="trama-audit-real-label-") as folder:
            raw=("[0:01] Instalamos o SDK do .NET.\n"
                 "[0:02] O LTS tem suporte estendido.\n"
                 "[0:03] Execute dotnet --version.\n")
            concepts=[
                {"nome":"SDK (Software Development Kit)",
                 "explicacao":"Kit de ferramentas.", "tempo":""},
                {"nome":"LTS (Long-Term Support)",
                 "explicacao":"Suporte longo.", "tempo":"0:02"},
                {"nome":"Comando dotnet --version",
                 "explicacao":"Versão do SDK.", "tempo":""},
            ]
            app,src,original=self._create(Path(folder),raw,concepts)
            try:
                report=audit_lesson(app.store.vault,"Aula-002")
                self.assertTrue(report["ok"],report)
                self.assertEqual(report["contagens"]["horarios_validos"],1)
                self.assertEqual(report["contagens"]["horarios_recuperados_txt"],2)
                self.assertEqual(report["contagens"]["referencias_duvidosas"],0)
                self.assertFalse(any("sem menção literal" in line.lower()
                                     for line in report["pendencias"]))
            finally:
                app.close()

    def test_atlas_prefers_source_evidence_over_wrong_model_time(self):
        from knowledge_bridge.memory_atlas import make_atlas
        with tempfile.TemporaryDirectory(prefix="trama-atlas-duplicate-time-") as folder:
            raw=("[0:01] Apresentação de ferramentas antes da aula.\n"
                 "[0:01] O LTS é uma versão de suporte estendido.\n"
                 "[0:05] SDK é uma sigla do kit de desenvolvimento.\n")
            concepts=[
                {"nome":"LTS (Long-Term Support)",
                 "explicacao":"Suporte de longo prazo.", "tempo":"0:01"},
                {"nome":"SDK (Software Development Kit)",
                 "explicacao":"Kit de desenvolvimento.", "tempo":"0:01"},
            ]
            app,_,_=self._create(Path(folder),raw,concepts)
            try:
                atlas=make_atlas(app.store)
                records={c["name"]:c["mentions"][0] for c in atlas["concepts"]}
                lts=records["LTS (Long-Term Support)"]
                sdk=records["SDK (Software Development Kit)"]
                self.assertEqual(lts["timestamp"],"0:01")
                self.assertIn("LTS",lts["excerpt"])
                self.assertIn("repetido",lts["confidence"])
                self.assertEqual(sdk["timestamp"],"0:05")
                self.assertIn("SDK",sdk["excerpt"])
                self.assertIn("horário da IA não confirma",sdk["confidence"])
            finally:
                app.close()

    def test_transcript_quote_escapes_markup(self):
        from knowledge_bridge.content import concept_slug
        with tempfile.TemporaryDirectory(prefix="trama-safe-evidence-") as folder:
            base=Path(folder)
            raw="[0:09] SDK <img src=x onerror=alert(1)> [[Nota-Falsa]]\n"
            label="SDK (Software Development Kit)"
            app,_,_=self._create(
                base,raw,[{"nome":label,"explicacao":"Ferramentas."}])
            try:
                note=(app.store.vault/"01-Meu-Conhecimento/Conceitos"/
                      (concept_slug(label)+".md")).read_text(encoding="utf-8")
                self.assertIn("&lt;img",note)
                self.assertNotIn("<img",note)
                self.assertNotIn("[[Nota-Falsa]]",note)
            finally:
                app.close()


if __name__=="__main__":
    unittest.main()
