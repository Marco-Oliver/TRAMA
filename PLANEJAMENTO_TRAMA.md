# PLANEJAMENTO TRAMA — fonte de verdade do projeto

> **Status:** fotografia do projeto em 31/10/2026. Documento vivo, não é promessa de que tudo já funciona.
>
> **Projeto:** [Marco-Oliver/TRAMA](https://github.com/Marco-Oliver/TRAMA)
>
> **Release pública:** v1.9.0, publicada em 31/10/2026. Código de referência da release: commit 92553125f6472ab4fef87893d2dc3109159a994f.
>
> **Correções ainda NÃO publicadas:** branch fix/critical-audit-20261031. Passou em 97 testes de regressão e 10 cenários adversariais, tanto em Windows quanto em Linux. Não integra o instalador v1.9.0.
>
> **Regra de leitura:** uma capacidade só pode ser apresentada como entregue se existir no código da versão indicada e houver evidência adequada. Não confundir protótipo, teste automatizado e uso real no computador do estudante.

---

## 1. Visão, finalidade e decisões firmadas

**TRAMA é, principalmente, uma automação de conhecimento pessoal para a Academia do Programador.** Sua função central é transformar fontes dispersas em um cofre Obsidian legível, navegável, rastreável e durável.

O usuário poderia fazer o fluxo manualmente: baixar transcrição, enviar a um modelo de IA, solicitar resumo, criar Markdown, conectar referências, guardar links e atualizar o Obsidian. O TRAMA automatiza esse trabalho intermediário.

**O Obsidian é o produto principal do fluxo, não um mero banco de dados para IA.** Deve permitir estudo humano sem qualquer assistente; o uso posterior por ChatGPT, Claude ou outras IAs externas é uma vantagem adicional, não a única finalidade.

**O aplicativo TRAMA não deve substituir nem aprisionar o Obsidian.** Os arquivos Markdown, links wiki e materiais locais devem continuar acessíveis no Obsidian mesmo sem o TRAMA.

O objetivo de curto prazo é permitir uma revisão fiel do curso após o encerramento previsto para dezembro de 2026, especialmente no período de estudos de dezembro/janeiro e na preparação para buscar trabalho de desenvolvimento a partir de fevereiro.

### Princípios obrigatórios

1. **Fidelidade ao curso:** preservar o modo de ensinar do professor e os códigos realmente demonstrados. Não antecipar métodos, atalhos, abstrações ou recursos que não tenham sido encontrados nas fontes cadastradas; se houver lacuna, declarar a lacuna.
2. **Rastreabilidade:** diferenciar fala original, código encontrado, interpretação do modelo, hipótese e revisão humana. Incluir número da aula, gravação, horário, arquivo, linha e/ou commit quando existirem; jamais inventar uma referência.
3. **Leitura humana primeiro:** notas Markdown claras, resumidas quando apropriado, mas completas quanto ao escopo, com navegação simples, links internos e mapa do Obsidian útil.
4. **Preservação:** nunca alterar a transcrição ou o código originais para “consertar” um erro. Registrar correções e dúvidas em notas próprias, mantendo a trilha de evidências. Proteger edições humanas.
5. **Automação de baixo atrito:** o usuário fornece os arquivos e links disponíveis; a automação organiza e processa. Não pressupor acesso automático a contas, Classroom, Meet ou vídeo.
6. **Custo controlado:** funcionamento local e pendências sem API; chamadas a provedores externos apenas quando autorizadas. Respeitar limites, informar falhas e não induzir uso pago.
7. **Escopo especializado:** o primeiro público é o próprio estudante da Academia do Programador. O funil curricular é contexto de organização, não prova de que determinados conteúdos foram ensinados.
8. **Estado explícito:** distinguir *implementado na release*, *implementado apenas em branch*, *parcial*, *planejado*, *hipótese/ideia* e *dependente de testes reais*.

### Não objetivos do momento

- Não desenvolver uma plataforma genérica de estudos para qualquer curso neste ciclo.
- Não transformar o TRAMA em um editor substituto do Obsidian.
- Não construir ou treinar um modelo de IA do zero.
- Não tornar o “Professor IA” pré-requisito para o Obsidian funcionar.
- Não desenvolver agora recursos adicionais sugeridos em conversas, como explorador completo de pastas GitHub ou acesso automático ao Classroom. Podem ser reavaliados **depois** das prioridades.
- Não ampliar uma ideia informal para requisito implementado sem decisão explícita do usuário.

## 2. Ordem de prioridades — não mudar sem decisão explícita

**Etapa zero — documentação de estado atual (esta entrega).**
Criar e manter este documento antes de novas funcionalidades. Registrar decisões, código real, limitações e critérios de conclusão; atualizar junto com mudanças relevantes. O README é apresentação pública e pode ser revisado depois.

**1 — Obsidian excelente (prioridade máxima de produto).**
Produzir uma biblioteca completa, fácil de navegar **à mão**, com:
- Visão por módulo, aula e gravações V01/V02/V03, quando identificadas.
- Resumo fiel por aula, exemplos realmente usados, conceitos, atividades, decisões e dúvidas.
- Links para o vídeo original e horários verificáveis; quando ausentes, informar que não foram encontrados.
- Referências para repositórios, caminhos, linhas e commit quando disponível.
- Backlinks e mapa/Graph View do Obsidian que façam sentido, não apenas links artificiais.
- Consolidação da evolução entre aulas, evitando tratar uma primeira menção como domínio comprovado.
- Notas adequadas para consulta por pessoas e, posteriormente, por IAs externas.

**2 — Automação confiável (base técnica).**
Garantir ingestão, classificação, extração, cruzamento de fontes, integridade, proteção de dados, reprocessamento, testes, atualizações e desempenho em escala. Em especial:
- Dúvidas estruturadas e persistentes: *pendente*, *investigando*, *hipótese*, *corroborada por evidências* ou *contraditória*.
- Ao chegar uma aula ou revisão nova do código, localizar dúvidas antigas relacionadas e reavaliar **somente** as evidências pertinentes.
- Nunca apagar interpretações antigas: guardar histórico do que mudou, de quando mudou e por quais fontes. Evidência encontrada em aula posterior pode esclarecer uma dúvida anterior, mas não torna a transcrição original falsa automaticamente.
- Diferenciar confirmação de que *um trecho existe* de confirmação de que *a explicação pedagógica está correta*. O resumo gerado por IA não é prova independente.
- Recuperação após interrupções, backups e simulações de acervo de aproximadamente 100–200 aulas.
- Reforços de segurança, performance, testes Windows e migração entre versões.

**3 — IA Professor (depois das etapas anteriores).**
Recurso adicional de conversa e estudo, **somente leitura do acervo**: responder com base no Obsidian/fontes, explicar como foi ensinado, criar desafios e comentar soluções. Não deve editar nem reescrever o cofre. Qualidade comparável à de ferramentas excelentes é uma meta sujeita à escolha do modelo e a testes reais, nunca uma garantia. Não antecipar implementação nesta etapa.

**Oportunidade futura, sem escopo aprovado:** eventualmente avaliar uma plataforma de estudos para outras áreas e a integração de um modelo avançado. Não abrir tarefas de desenvolvimento para isso agora.

## 3. Contexto curricular conhecido

A Academia segue um percurso por módulos (aproximadamente mensal; ordem informada pelo estudante). A organização inicial do TRAMA acompanha:

1. Lógica de Programação.
2. Programação Orientada a Objetos.
3. Desenvolvimento Web.
4. Banco de Dados.
5. Testes.
6. APIs e Backend.
7. Frontend (Angular e React).
8. Desenvolvimento Agêntico.
9. TCC.

**Regra:** conhecer o nome e a ordem de um módulo não equivale a conhecer suas aulas, atividades, resultados, exercícios ou código. O TRAMA só deve afirmar o que foi estudado se houver material que sustente essa informação.

### Modelo mental das fontes

- **Transcrição:** registro da fala, potencialmente com erros automáticos de reconhecimento.
- **Código Git:** evidência de que determinada implementação consta de um commit/arquivo; não prova autoria, quando foi estudado ou se o aluno dominou o tema.
- **Classroom/print/documento:** contexto, instruções ou informações visíveis; planejamento de aula não é prova de que a atividade foi realizada.
- **Resumo gerado:** interpretação auxiliar, nunca confirmação independente de outra interpretação da mesma origem.
- **Vídeo/áudio:** fonte de revisão quando necessário; somente o link pode estar disponível atualmente.
- **Decisão humana:** esclarecimento ou correção registrada pelo usuário com preservação do original.

## 4. Estado comprovável do aplicativo v1.9.0 (main/release)

### 4.1 Tecnologias e estrutura

- Python 3.11+ para backend/orquestração; SQLite local como catálogo e cache.
- Interface HTML/CSS/JavaScript apresentada em janela desktop com pywebview/WebView2, usando arquivos locais.
- Markdown em cofre Obsidian; fontes e registros locais não são hospedados no GitHub do projeto.
- Git e repositórios GitHub públicos ou locais para indexação de código.
- Integração opcional com Gemini, Groq e OpenRouter, configurada pelo usuário; modelos específicos e disponibilidade dependem dos provedores.
- PyInstaller + Inno Setup para empacotamento Windows; GitHub Actions para testes, instalação de CI e release.

Referências técnicas centrais:
- [main.py](main.py): CLI (gui, init, import, process, repo, status, rebuild).
- [knowledge_bridge/bridge.py](knowledge_bridge/bridge.py): API de ponte e operações da interface.
- [knowledge_bridge/auto_ingest.py](knowledge_bridge/auto_ingest.py): importação em lote, links e materiais visuais.
- [knowledge_bridge/pipeline.py](knowledge_bridge/pipeline.py): orquestração, análise, comparação e repositórios.
- [knowledge_bridge/ai.py](knowledge_bridge/ai.py): chamadas aos provedores, limites e prompts.
- [knowledge_bridge/code_intel.py](knowledge_bridge/code_intel.py): indexação, evidências e sanitização de trechos.
- [knowledge_bridge/store.py](knowledge_bridge/store.py): tabelas SQLite de fontes, análises, trechos, relações e escritas.
- [knowledge_bridge/publishing.py](knowledge_bridge/publishing.py): arquivos e estrutura do Obsidian.
- [knowledge_bridge/memory_atlas.py](knowledge_bridge/memory_atlas.py): atlas temporal e contexto anterior.
- [knowledge_bridge/vault_index.py](knowledge_bridge/vault_index.py): leitura de Markdown, busca e grafo da biblioteca.
- [knowledge_bridge/secure_keys.py](knowledge_bridge/secure_keys.py): chaves de API protegidas com DPAPI no Windows.
- [knowledge_bridge/update_service.py](knowledge_bridge/update_service.py): consulta de releases e verificação SHA-256.
- [trama_launcher.py](trama_launcher.py) e [.github/workflows/release.yml](.github/workflows/release.yml): inicialização e distribuição Windows.

### 4.2 Entrada e processamento existentes

**Implementado:**
- Selecionar cofre e importar transcrições TXT/MD, imagens, PDFs e DOCX nos fluxos suportados; fila de materiais e colagem de prints.
- Agrupar gravações com identificação explícita de aula e V01/V02/V03, com limites para inferências.
- Cadastrar contexto e links de Classroom/Meet/Drive e associar repositórios GitHub ou locais.
- Preservar fontes no cofre, gerar resumos estruturados por trechos via IA opcional e registrar pendências se não houver provedor/cota.
- Consultar fontes anteriores pertinentes (contexto limitado) e comparar menções da transcrição com evidências de código.
- Produzir relatórios e notas com ressalvas de hipótese, possíveis correções e evolução.
- Reconstruir índice do Obsidian a partir dos dados já disponíveis, sem exigir nova chamada de IA para cada reconstrução.
- Exibir notas, busca, informações relacionadas e grafo parcial do cofre na interface.

**Não implementado ou não confirmado como comportamento completo:**
- Login automático no Classroom ou download automático de aulas e vídeos.
- Transcrição integral de áudio/vídeo pelo próprio TRAMA, ou validação automática universal do áudio contra o TXT.
- Investigação persistente de dúvidas antigas acionada automaticamente por **aulas futuras** e atualização documentada de conclusões passadas.
- Garantia de interpretação factual correta só porque o horário ou arquivo citado existe.
- Navegador Git completo (árvore de arquivos editável/navegável como IDE) embutido.
- IA Professor conversacional integrada.
- Prova de desempenho com o acervo pessoal inteiro.

### 4.3 Saída Obsidian hoje

O [Publisher](knowledge_bridge/publishing.py) escreve uma estrutura orientada à leitura e a links Wiki. Entre as áreas:
- **01-Meu-Conhecimento:** conceitos, módulos, índices e Mapa-da-Evolucao.
- **02-Minhas-Aulas:** notas de aulas/gravações e visões gerais.
- **03-Meus-Projetos:** notas associadas aos repositórios.
- **90-Sistema:** índices/relatórios de processamento e pendências.
- **99-Anexos:** transcrições e materiais originais, contexto adicional.

A organização efetiva é guiada pelas fontes cadastradas: não prometer que todo módulo ou aula já tem notas ou que todos os links e horários estarão completos. O mapa atual registra menções, relações candidatas e o que foi visto nas fontes disponíveis. **Ele não é ainda o ciclo completo de investigação e autocorreção desejado.**

### 4.4 Segurança e preservação atuais

- Chaves de API locais com DPAPI no Windows.
- Confirmar antes de enviar materiais à IA externa; provedores possuem seus próprios limites e políticas.
- Evitar importação de links simbólicos; limitar caminhos e tamanhos de anexos conforme código.
- Preservação das fontes originais e controle de escritas automáticas, com arquivos de proposta em certos conflitos com edição humana.
- Dados pessoais, cofre, transcrições e credenciais **não** fazem parte do repositório ou instalador distribuído.
- Release tem hash SHA-256, **não** possui certificado de assinatura digital.
- Testes automatizados não comprovam proteção absoluta contra vazamento de segredos ou perda de dados.

## 5. Correções críticas desenvolvidas, mas fora da versão pública

**Branch:** [fix/critical-audit-20261031](https://github.com/Marco-Oliver/TRAMA/tree/fix/critical-audit-20261031)

**Status:** implementadas na branch e validadas em [execução Linux + Windows](https://github.com/Marco-Oliver/TRAMA/actions/runs/41173887741), sem merge na main e sem novo instalador.

| Problema | Situação na release v1.9.0 | Situação na branch |
| --- | --- | --- |
| Mesclar indevidamente C, C# e C++ | Risco identificado | Normalização/consolidação corrigida e coberta por teste |
| Arquivo armazenado alterado mantendo tamanho | Verificação insuficiente em um caminho | Hash do conteúdo e verificação da cópia, com teste |
| Credenciais em código enviado à IA | Filtro incompleto | Padrões comuns ampliados, com testes; **não garante 100% dos segredos** |

**Testes da branch:** 97 regressões + 10 adversariais aprovados no Linux; 97 regressões + 10 adversariais aprovados no Windows; auditoria de pacote aprovada. Isso **não** significa que o usuário já testou a nova versão no próprio Windows, nem que as mudanças já estejam no instalador v1.9.0.

Antes de publicar uma versão nova: revisar alterações, integrar a branch de forma controlada, incrementar versão, executar pipeline completo Windows e conferir o release, sem sobrescrever v1.9.0.

## 6. Lacunas e riscos conhecidos (backlog, não promessas)

| Prioridade de avaliação | Lacuna | Critério de conclusão sugerido |
| --- | --- | --- |
| Alta | Qualidade do resumo e fidelidade ao professor | Avaliação humana com transcrições/códigos representativos e referências clicáveis; distinguir inferência de fato |
| Alta | Dúvidas que amadurecem em aulas futuras | Persistência, investigação incremental, trilha de revisões e casos simulados de dúvida→evidência nova→reavaliação |
| Alta | Integridade do cofre e atualizações | Backup/teste de migração com SQLite, Markdown e notas humanas antes/depois de atualização |
| Alta | Proteção de credenciais | Filtros mais amplos, exclusões de arquivos sensíveis e conferência do que será enviado |
| Média | Segurança da interface | Revisar CSP/superfície de conteúdo importado sem quebrar o aplicativo |
| Média | Escala com 100–200 aulas | Testes de volume e métricas de tempo/memória, inclusive com máquina modesta como referência |
| Média | Windows/WebView2 visual | Abrir e navegar na GUI em ambiente real; validar tamanhos de janela, eventos, erros e reabertura |
| Média | Instalação e upgrade | Testar duas versões publicáveis consecutivas, instalar/reinstalar/atualizar/desinstalar preservando dados |
| Média | Explicações da IA | Declaração de incerteza, revisão das referências e limites de contexto; não afirmar que IA interpreta perfeitamente |
| Posterior | Conveniência da navegação Git dentro do TRAMA | Explorar pastas/código e relacionar aulas, sem comprometer o Obsidian nem ampliar escopo presente |

**Observações de estado:** CI de release da v1.9.0 passou com 92 testes de regressão e 10 adversariais, compilação, self-test do EXE e smoke test de instalação/reinstalação/desinstalação. São verificações automatizadas, não uma avaliação de experiência em uso cotidiano. O README ainda contém uma frase condicional sobre a primeira publicação do instalador; revisar texto na próxima atualização do README, não assumir que release esteja indisponível.

## 7. Fluxo-alvo de produção de conhecimento

1. Usuário seleciona cofre e fornece as fontes disponíveis: TXT/MD, prints, PDF/DOCX, contexto/links da aula e um ou mais repositórios.
2. TRAMA verifica formato, integridade, aula/gravação e proveniência; preserva original e separa fontes de inferências.
3. Python identifica o módulo mais plausível, trechos e evidências; não inventa aula, atividade realizada nem domínio.
4. Gemini/Groq/OpenRouter, quando autorizados e disponíveis, produzem interpretação estruturada. O Python filtra saída, valida horários e associações concretas.
5. Se houver ambiguidade, pesquisar fontes disponíveis em ordem apropriada (transcrição original, código relevante, contexto/README/documentos, outras aulas), com limites de custo e informação.
6. Incertezas não resolvidas ficam visíveis, **não** viram conclusões definitivas; trabalho de investigação longitudinal ainda é objetivo de implementação.
7. O Publisher gera Markdown navegável para estudo humano, com fonte/horário/arquivo/linha quando disponíveis; notas pessoais permanecem preservadas.
8. Uma aula futura pode motivar reavaliação de uma dúvida antiga, **quando o mecanismo de revisão progressiva for implementado**. Registrar evidência nova e histórico sem reescrever o original.
9. O estudante consegue ler tudo manualmente no Obsidian; uma IA externa poderá consultar os mesmos documentos sem se tornar dependência estrutural do TRAMA.

### Exemplo de comportamento desejado, NÃO implementado integralmente

Aula 35 tem termo transcrito incorretamente; o GitHub da época não resolve → estado *pendente*. Aula 37 traz termo e código compatíveis → sugerir correção da Aula 35 com links e justificativa, mantendo transcrição, primeira hipótese e possibilidade de revisão humana. Aula 50 pode contradizer a hipótese → reabrir a análise. Não executar correção silenciosa da fala original.

## 8. Critérios de aceitação das próximas etapas

### Etapa 1 — Obsidian excelente

- Notas legíveis e úteis sem abrir TRAMA nem conversar com IA.
- Estrutura modular e índices por aulas/gravações, conceitos e projetos.
- Exemplos de código do professor apresentados de forma clara e ligados a arquivos/commits corretos, quando existentes.
- Caminho para localizar gravação e minuto real de uma explicação; ausência registrada honestamente.
- Backlinks e grafo com conexões úteis; evitar falsos relacionamentos.
- Dúvidas, hipóteses e correções visíveis e separadas de afirmações verificadas.
- Revisar uma amostra real de conteúdos e comparar com as fontes antes de declarar a etapa concluída.

### Etapa 2 — Automação confiável

- Processar lotes repetidos sem duplicações indevidas ou perda de originais.
- Testar arquivos alterados, cópias corrompidas, falhas de IA, interrupções e retomada.
- Investigar dúvidas antigas quando surgem evidências, com histórico e controle de reprocessamento.
- Garantir isolamento de segredos e confirmação de qualquer envio à IA.
- Ensaiar acervo sintético de 100–200 aulas e múltiplos repositórios, com medições.
- Validar backup e migração de dados, instalação/atualização, e compatibilidade Windows GUI.

### Etapa 3 — IA Professor (a definir depois)

- Consultar o cofre em leitura apenas, com perguntas, explicações e desafios baseados nas fontes.
- Não afirmar que a ausência de uma fonte comprova que o assunto nunca foi visto.
- Não editar o Obsidian nem substituir o mecanismo de organização.
- Só considerar recurso concluído após demonstrar qualidade real do modelo e das referências; não construir agora.

## 9. Regras de trabalho para agentes e futuras conversas

1. **Ler integralmente este documento antes de planejar ou modificar o TRAMA.** Conferir README, código e branch atual: o documento pode estar desatualizado; discrepâncias precisam ser explicitadas, nunca encobertas.
2. **Não inferir que uma conversa autoriza implementação.** Discussão de ideias não equivale a pedido de mudança. Respeitar o escopo e pedir autorização quando necessário.
3. **Não antecipar prioridade 2 ou 3 para entregar algo vistoso.** A ordem acordada é documentação → Obsidian → automação → IA Professor.
4. **Atualizar este arquivo junto de mudanças relevantes** (arquitetura, comportamento, segurança, regra de negócio, estado de testes, liberação, decisão de escopo). Editar a seção adequada, não apenas acrescentar cronologia.
5. Marcar itens com estado preciso: previsto / em andamento / testado na branch / integrado à main / disponível no instalador / validado no PC.
6. **Não inventar provas, dados ou métricas.** Não alegar testes Windows, verificações de IA ou arquivos reais sem resultados observados.
7. **Preservar dados do usuário e evitar escrita destrutiva.** Preferir alterações incrementais e reversíveis. Nunca colocar tokens, dados de aulas pessoais ou cofres reais no GitHub.
8. Proteger a release pública: branch de trabalho para código, testes antes de integrar, versão nova para instalador; não sobrescrever tags/assets.
9. Na entrega, explicar: o que mudou, os arquivos alterados, testes realizados e pendências, o que continua fora da versão pública.
10. Código e fatos técnicos prevalecem sobre a narrativa do documento. Se houver divergência, apontar e corrigir a documentação.

## 10. Registro de decisões e atualizações

| Data | Decisão/registro | Estado |
| --- | --- | --- |
| 31/10/2026 | Publicação da versão Windows 1.9.0; smoke tests de release aprovados. | Publicado |
| 31/10/2026 | Três correções críticas em fix/critical-audit-20261031: conceitos, integridade e ocultação de segredos. | Testadas na branch; ainda não publicadas |
| 31/10/2026 | Definido que o TRAMA **automatiza** a criação/manutenção de um Obsidian voltado primeiro ao estudo humano; consumo por IA externa é secundário. | Decisão de produto |
| 31/10/2026 | Ordem de prioridades: 1) Obsidian excelente; 2) automação confiável; 3) IA Professor depois. | Decisão de produto |
| 31/10/2026 | Criar o MD mestre antes de iniciar a etapa 1, para evitar perda de contexto e confusão entre estados. | Esta entrega |
| 31/10/2026 | Possibilidade de produto genérico e mais integrações comentada, **sem inclusão no escopo ativo**. | Ideia estacionada |

**Próxima ação aprovada nesta conversa:** somente documentação do estado atual. Implementação das melhorias das etapas 1, 2 ou 3 requer decisão/autorização posterior.

---

**Este documento é uma especificação viva.** Não é evidência de funcionamento por si só. Antes de avançar, confronte-o com a branch, os testes, a release e amostras reais do Obsidian.
