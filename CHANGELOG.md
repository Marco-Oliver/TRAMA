# Histórico de versões do TRAMA

## [2.2.8] — 2026-11-09

### Importar e organizar como fonte principal
- Tela nova no visual do TRAMA, em duas colunas: **1. Arquivos e prints** e **2. Texto do Classroom e links** (posts de aula, posts de atividade, gravações e GitHub, tudo no mesmo campo).
- **Prévia ao vivo** enquanto você cola: aulas, atividades/trabalhos/provas com prazo, repositórios, links de gravação e linhas não reconhecidas, antes de processar e sem IA.
- Resultado em lista (arquivos, aulas, atividades novas/atualizadas, repositórios, chamadas à IA) e pendências recolhíveis.
- Todo link do GitHub que entra pelo Importar também aparece em **Projetos**.

### Corrigido — importar post de atividade
- Colar o post de uma atividade/trabalho/prova (ex.: `[M01] Atividade 01 - Hello World em C#`) em **Importar e organizar** agora cadastra a atividade em Resumos → Atividades, em vez de virar pendência "texto fora de um post".
- Lê o professor na linha logo após o título, a data solta ("3 de mar.") e ignora o título repetido do Classroom. Datas sem ano ficam no passado (post de março lido em novembro = março deste ano).
- Com uma única atividade no lote, o link do GitHub colado em "Repositórios" vai para ela e a versão entregue é congelada. Colar de novo completa a mesma atividade, sem duplicar.

## [2.2.7] — 2026-11-09

### Novo — Atividades, trabalhos e provas (Resumos)
- Pasta **Atividades, trabalhos e provas** em Resumos, com CRUD. Cadastro colando o post do Classroom: título, módulo ([M01]), professor e prazo são lidos sozinhos; o tipo é sugerido e editável. Prova aceita nota e link.
- Uma atividade guarda vários repositórios (o seu, o da dupla e o do professor). A **versão entregue** é o último commit até o prazo, congelada por SHA.
- **Resumo da entrega por IA** (1 chamada) a partir do código da versão entregue: o que foi pedido, o que foi feito, estrutura, conceitos das aulas no código e o que falta. Arquivos e trechos são conferidos no código antes de publicar.
- **Aulas de desenvolvimento**: aulas só com post (ex.: "Dúvidas e ajudas") aparecem em Resumos e se ligam ao trabalho em andamento pela data/prazo ou pelo nome.
- Módulos mostram as entregas, e o resumo do módulo pela IA passa a considerá-las.
- **Lacunas retomadas**: uma lacuna da aula vira "retomada na Aula X" quando uma gravação posterior trata do assunto (sem IA).

### Novo — aba Projetos
- Repositórios agrupados em **Meus / Dupla / Professor**, com os pares lado a lado (professor × nosso).
- Navegação de arquivos estilo GitHub dentro do TRAMA, com número de linha e seletor de **versão**: entregue, main, branches, tags e pastas V0/V1/V2.
- Donos dos repositórios editáveis em **Ajustes**.
- Somente leitura via API REST (sem clone, sem commit). Arquivos são lidos pelo endereço raw do SHA e não gastam a cota da API.

### Obsidian, Biblioteca e Grafo
- Notas em `04-Resumos/Atividades/` e uma nota por repositório em `03-Meus-Projetos/Repositorios/`, com links da versão entregue e do repositório atual e a seção **Contexto para IA**. O código não é copiado para o cofre.
- Biblioteca: notas de Resumos e Projetos ganham o botão para abrir na tela própria do TRAMA.
- Grafo: resumos ligados às gravações e aos conceitos da aula, com cor e filtro próprios.
- Resumos e Projetos no visual da Biblioteca (mesmos ícones e tipografia).

## [2.2.6] — 2026-11-09

### Novo — aba Resumos (camada de estudo)
- Nova aba **Resumos** no menu, no visual da Biblioteca, com árvore **Aulas / Módulos**.
- **Resumo de cada aula** juntando todas as gravações em 9 partes: em uma frase, mapa mental, o que você precisa saber, comandos e código, ligação com outras aulas, lacunas (agenda × gravações), para fazer, dúvidas em aberto e revisão rápida.
- Fidelidade conferida localmente antes de publicar: cada ponto cita o vídeo de origem (V01, V02…) que existe de verdade; comandos só entram se aparecerem literalmente no TXT ou num bloco de código do material oficial; dúvidas em aberto vêm do catálogo local, não da IA. A IA recebe apenas os resumos já validados de cada gravação, nunca o TXT inteiro.
- Botão **Gerar resumos** para aulas já processadas (com pausa entre chamadas para respeitar 15 req/min) e geração automática ao processar aulas novas no app (+1 chamada por aula).
- **Módulos com CRUD**: os 9 módulos do curso vêm cadastrados; criar, editar, reordenar e excluir (aulas e resumos nunca são apagados). Cada aula se encaixa sozinha (IA ou palavras-chave) e a escolha manual sempre vence.
- **Página viva do módulo**, atualizada a cada aula sem IA, e **resumo do módulo pela IA** gerado após 3 aulas e atualizado a cada 5 aulas novas (ou pelo botão).
- Pasta **04-Resumos/** no Obsidian (índice, aulas e módulos), com a mesma proteção de edições manuais (.PROPOSTA).

### Corrigido — auditoria do front
- Links de materiais registrados na aula (Whimsical, docs da Academia, arquivo no SHA congelado) agora abrem pelo TRAMA; antes só links de vídeo eram aceitos. URLs não registradas continuam bloqueadas.
- Botão de **favoritar** também nas abas Aulas e Conhecimento (o filtro "Favoritas" dependia de favoritar pela Biblioteca).
- "Notas relacionadas → Por tags" deixa de aparecer vazio quando a nota não tem tags.
- "Gerar Resumos" da barra superior, dentro da aba Resumos, gera os resumos de estudo pendentes.

## [2.2.5] — 2026-11-09

### Corrigido — consistência de conceitos e nomes nas aulas
- Conceitos canônicos da aula usados de forma consistente na nota da gravação, visão geral, mapa de evolução, módulos e índices do Obsidian, sem links para páginas antigas de conceitos já unificados (por exemplo, Extensão C# Dev Kit → C# Dev Kit; Arquivo .cs/Extensão .cs → .cs).
- Nome do autor do Classroom, **Tiago Santini de Athayde**, prevalece sobre o nome reduzido **Thiago Santini**, que permanece como alias. Menções incertas, como Thago Rover, apontam para o nome canônico sem afirmar equivalência sem evidência.
- Página antiga de pessoa gerada automaticamente é arquivada quando elegível, preservando notas editadas manualmente.
- Rebuild local aproveita dados e análises já existentes: sem novas chamadas à IA, sem alterar TXT originais nem segredos.

### Distribuição
- App e instalador Windows 2.2.5, mantendo AppId, cofre, SQLite, configurações e chaves locais.
- Release condicionada a testes de regressão e adversariais, instalação/reinstalação/desinstalação e upgrades de v2.1.0, v2.2.0, v2.2.1, v2.2.2, v2.2.3 e v2.2.4 para v2.2.5, com dados sintéticos.


## [2.2.4] — 2026-11-08

### Fidelidade local da Aula 02 (sem reprocessar IA)
- Reconhecimento de autores do Classroom com partículas minúsculas (de, da, do, dos, das, e), e reimportação do mesmo post quando somente a extração do parser mudou, preservando histórico.
- Nomes canônicos de professores/pessoas conhecidas têm prioridade sobre apelidos e grafias imprecisas, mantendo a indicação de identidade provável e prevenção de falsos positivos.
- Páginas de Pessoas reservadas para autores de posts ou nomes que aparecem em pelo menos três aulas distintas; notas humanas preservadas e páginas automáticas não qualificadas arquivadas.
- Conceitos duplicados dentro da aula unificados com aliases, sem perder explicações nem horários distintos; C, C# e C++ continuam diferentes.
- Exemplos verificados literalmente em blocos de código da documentação oficial passam para "Exemplos do material oficial", com arquivo e SHA congelado; a transcrição original não é alterada.
- Rebuild local atualiza aulas antigas sem reprocessar as análises nem chamar IA.

### Distribuição
- Instalador 2.2.4 com o mesmo AppId e dados locais preservados.
- Testes offline Ubuntu/Windows e smokes reais do instalador, incluindo upgrade de 2.1.0, 2.2.0, 2.2.1, 2.2.2 e 2.2.3 para 2.2.4 com dados sintéticos.


## [2.2.3] — 2026-11-08

### Adicionado — documentação oficial da Academia como terceira fonte
- Links oficiais de https://academiadoprogramador-fullstack.github.io/docs/ são resolvidos para arquivos Markdown por slug ou rota Docusaurus e vinculados a um SHA GitHub congelado por aula.
- Evidências de conteúdo têm proveniência e limites; dúvidas podem receber a indicação EXPLICADA_PELO_MATERIAL sem serem confundidas com prova do áudio. Nenhum trecho dos documentos é enviado à IA.
- **Recuperação de contextos antigos:** importação ou rebuild encontra URLs oficiais existentes em 99-Anexos/Contexto-Classroom/*.json e vincula apenas à aula explícita no JSON e no nome do arquivo, mantendo intactos os contextos originais, análises e SHAs já congelados. Se o GitHub ficar indisponível ou atingir a cota, a operação não bloqueia o rebuild e é retomada na próxima tentativa.
- **Sugestões sem aula:** URLs oficiais sem aula explícita podem apresentar uma provável Aula-0XX usando correspondências conservadoras entre título, tags, termos e TXT previamente analisados. A sugestão nunca cria vínculo automaticamente e exige confirmação do usuário.

### Testes e atualização
- Testes locais sintéticos, sem IA, abrangem material já salvo, repetição do rebuild, falha de acesso GitHub, sugestões e ausência de associações sem evidência.
- Atualização 2.2.2 → 2.2.3 mantém o mesmo AppId, cofre Obsidian, banco SQLite, ajustes e chave local. A CI Windows também simula o upgrade do instalador oficial 2.2.2 com dados fictícios; testes Ubuntu/Windows e instalador são pré-requisitos para publicação.


## [2.2.2] — 2026-11-07

### Corrigido — Aula 01 e organização de pessoas
- **Apresentadores em gravações:** o nome no título é apenas uma pista. Se a transcrição contém uma autoapresentação com primeiro nome compatível, a nota apresenta o possível palestrante explicitando que o sobrenome ainda precisa de conferência; nome completo confirmado no TXT ou no contexto mantém evidência mais forte. Um título isolado não cria pessoas.
- **Grafias similares de nomes completos:** divergências pequenas como `Tiago Santini` / `Thiago Santini`, com o mesmo sobrenome, deixam de gerar avisos redundantes como `Thiago Santini (possivelmente Santini)`. Nenhum nome é corrigido no TXT original.
- **Perfis de pessoas e siglas:** siglas e nomes com formato institucional (ex.: `FCVest`) passam à seção de termos, siglas e instituições para conferir; não viram páginas de pessoas. Preserva a hipótese legítima `Rash (possivelmente Rech)` sem criar identidade nova.
- **Classroom colado:** linhas de cabeçalho de data abreviada, como `2 de mar.`, são ignoradas sem avisos ou mudança da data `Agenda: dd/mm/aaaa`.

### Compatibilidade e segurança
- Correções locais nas notas; não consomem chamadas extras de IA e não reprocessam automaticamente aulas já analisadas. O texto original, contextos do Classroom, preferências e chaves locais são preservados.
- Testes sintéticos cobrem nomes completos/abreviados, ausência de evidências, siglas, importação de datas e preservação do cache.
- Instalação e atualização com `TRAMA_Setup.exe` e `SHA256SUMS.txt`. Smokes Windows de instalação/reinstalação e upgrade das versões oficiais 2.1.0, 2.2.0 e 2.2.1 usam somente dados fictícios.

## [2.2.1] — 2026-11-06

### Corrigido — Aula 01
- **Apresentador ausente:** usar o título da gravação e a autoria do Classroom como pistas, incluindo uma pessoa somente quando o nome completo também consta na transcrição ou no contexto disponível.
- **Nomes distorcidos:** evitar criar perfis para variantes fonéticas como `Rash`; registrar `Rash (possivelmente Rech)` em **Nomes e apelidos para conferir**.
- **Aulas não técnicas:** conceitos de apresentações, organização e atividades ficam na nota da própria aula, sem gerar páginas em `01-Meu-Conhecimento` nem marcos no mapa da evolução.
- **Avisos fora de contexto:** exibir hipóteses vinculadas a SHA apenas quando existe versão congelada; não exigir congelamento do GitHub se a aula não possui repositório associado.
- **Post do Classroom no lote:** aceitar conteúdo colado como contexto local (título, autor, agenda, conteúdo, atividades, links e gravações), separar múltiplos posts e tratar o texto como dado não confiável, sem utilizar IA para interpretar a colagem.

### Corrigido — auditoria da PR #8
- **Posts após links:** um contexto já criado somente por URLs não impede salvar o post colado da mesma aula. Fontes permanecem separadas; o mesmo post alterado e arquivos com edição manual não são sobrescritos silenciosamente.
- **Cache e cota da IA:** processamento geral e lotes preservam análises antigas válidas, incluindo aulas com nomes curtos; revisão de regras só invalida a aula solicitada explicitamente (`lesson_filter` ou `force=True`). Importar contexto não reprocessa automaticamente aulas anteriores.

### Instalação e atualização
- Mantidos o AppId, a pasta de instalação e os dados locais da versão 2.2.0.
- Release com `TRAMA_Setup.exe` e `SHA256SUMS.txt`, mediante testes sintéticos de instalação, reinstalação e upgrade no Windows.
- Reprocessar uma aula antiga para incorporar as novas regras requer ação explícita; recomenda-se backup local antes de reprocessar.

## [2.2.0] — 2026-11-06

### Adicionado
- Associação automática de aulas às versões congeladas dos repositórios GitHub, com SHA, arquivos, linhas e escolha manual de versão.
- Identificação de branches `v0` a `vN` e da branch padrão quando não coincide com a última `vN`; diferenças extensas calculadas por hashes das árvores Git.
- Revisão local de dúvidas de transcrição usando somente a versão congelada da aula, sem consumir novas chamadas de IA.
- Pistas técnicas com trechos de código literais, links imutáveis e indicação explícita de que não comprovam o áudio.

### Corrigido
- URL de metadados GitHub sem barra final, evitando falso erro de repositório inexistente.
- Redução de falsos positivos: consulta apenas dúvidas técnicas ou conceitos distorcidos marcados; textos explicativos fora de aspas, `using`, `namespace`, strings, URLs, comentários e nomes genéricos não geram correspondências.
- Conceitos corretos em português não recebem estados de dúvidas. `DB Contact`, quando validado como grafia distorcida pelo código congelado, gera **um único link** para `DbContext` em Conhecimentos relacionados, preservando a grafia do TXT nas observações.
- Sem trechos repetidos de evidência e sem HTML escaping de parâmetros genéricos C# em blocos de código.

### Atualização da 2.1.0
- Mesmo AppId, pasta e canal oficial do instalador 2.1.0.
- `TRAMA_Setup.exe` e `SHA256SUMS.txt` na release pública; download com SHA-256 conferido e instalação mediante confirmação do usuário.
- Teste automatizado no Windows com upgrade 2.1.0 → 2.2.0, preservando SQLite, nota manual do Obsidian, ajustes e chave DPAPI **fictícia**. Nenhuma chave real entra no repositório nem no CI.
- Recomendado realizar backup local antes de reprocessar aulas.

## [2.1.0] — 2026-11-03

- Pesquisa local em transcrições, melhorias na IA Professor, evidência extraída de materiais originais e reprocessamento individual.
- Atualização oficial a partir de 2.0.1 e verificações de persistência de dados locais.
