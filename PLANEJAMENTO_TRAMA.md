# TRAMA — Como o sistema funciona

**Estado documentado:** 2 de novembro de 2026  
**Versão pública atual:** 2.0.0 (Windows), publicada em 31/10/2026. **Versão anterior:** 1.9.0. [Instalador e SHA-256](https://github.com/Marco-Oliver/TRAMA/releases/tag/v2.0.0)  
**Projeto:** [GitHub — TRAMA](https://github.com/Marco-Oliver/TRAMA)

Este documento descreve a finalidade do TRAMA, as funcionalidades existentes, o caminho dos materiais até o Obsidian e as melhorias previstas. **Recursos disponíveis hoje e ideias futuras estão separados.**

## 1. O que é o TRAMA?

O **TRAMA é um aplicativo de automação de estudos**. Ele reúne materiais de aulas, analisa o conteúdo, relaciona informações e cria uma biblioteca de conhecimento em arquivos Markdown compatíveis com o Obsidian.

Seu objetivo inicial é organizar o conhecimento adquirido na **Academia do Programador** para que o estudante consiga revisar o curso mesmo meses ou anos depois.

O TRAMA não é o destino final do conhecimento: **o resultado principal é o cofre do Obsidian**, que permanece útil mesmo sem abrir o TRAMA ou conversar com uma IA.

O fluxo que o TRAMA automatiza poderia ser feito manualmente: baixar a transcrição, pedir a uma IA que faça um resumo, copiar as explicações, localizar o código do professor, associar fontes, escrever notas Markdown e criar links no Obsidian.

O sistema reduz esse trabalho repetitivo, mantendo a participação do estudante na seleção dos materiais.

## 2. Para quem ele foi feito?

A primeira versão é especializada nos estudos da Academia do Programador. O percurso informado pelo estudante inclui:

1. Lógica de Programação;
2. Programação Orientada a Objetos;
3. Desenvolvimento Web;
4. Banco de Dados;
5. Testes;
6. APIs e Backend;
7. Frontend (Angular e React);
8. Desenvolvimento Agêntico;
9. TCC.

Esses nomes ajudam a organizar a biblioteca. **O sistema não pode concluir que determinado assunto foi ensinado somente porque faz parte de um módulo.** O conteúdo precisa aparecer nas fontes cadastradas.

O foco é preservar **como o professor ensinou**, incluindo exemplos de código, sequência de aprendizado, atividades registradas e referências originais — não substituir tudo por explicações genéricas de programação.

## 3. O caminho dos materiais até o Obsidian

```text
MATERIAIS SELECIONADOS PELO ESTUDANTE
Transcrições, prints, documentos, links de aulas, repositórios
                         |
                         v
                  IMPORTAÇÃO TRAMA
Identificação de aula, gravação, tipo de fonte e armazenamento
                         |
                         v
                ANÁLISE E ORGANIZAÇÃO
Python prepara trechos e contexto; IA opcional extrai resumos
                         |
                         v
                 CRUZAMENTO DE FONTES
Aula + conceitos + materiais do Classroom + código do GitHub
                         |
                         v
                    COFRE OBSIDIAN
Módulos, aulas, projetos, conceitos, links internos e referências
                         |
             +-----------+-----------+
             v                       v
    ESTUDO MANUAL          CONSULTA POR IA EXTERNA
      NO OBSIDIAN             (fora do TRAMA)
```

O TRAMA **não acessa automaticamente o Classroom e não baixa os vídeos**. Nesta fase, o estudante escolhe os arquivos e fornece os links. Isso também evita que a automação dependa de credenciais ou de técnicas de acesso não implementadas.

### 3.1 O que pode ser informado

| Material | Comportamento atual |
| --- | --- |
| Transcrições `.txt` e `.md` | Importadas, preservadas e analisadas em trechos |
| Prints `.png`, `.jpg`, `.jpeg`, `.webp` | Importados; leitura visual automatizada quando houver Gemini configurado e autorizado |
| PDF e DOCX | Importados como materiais; alguns dados podem ser extraídos conforme o fluxo e o provedor disponível |
| Links de Classroom, Meet e Drive | Registrados como referências às aulas |
| Repositórios GitHub ou Git locais | Indexação de arquivos, trechos de código e referências |
| Vídeos | Mantidos por **link**; o TRAMA não copia nem transcreve automaticamente o arquivo de vídeo |

Os materiais podem ser enviados em lote, colocados numa fila de importação e associados a aulas. A interface também aceita colagem de imagens no fluxo previsto.

### 3.2 Como as aulas são identificadas

O sistema reconhece padrões de nomes como `Aula 01` e associa marcadores `V01`, `V02`, `V03` a gravações distintas da mesma aula, quando o nome permite essa interpretação.

Não inventa números de aulas pela posição do arquivo na lista. Materiais sem identificação suficiente podem ficar pendentes de revisão.

## 4. O que o Python faz?

O backend Python é responsável pelas tarefas estruturadas e repetitivas:

- Identificar e catalogar as fontes, impedindo reimportações desnecessárias.
- Copiar os arquivos permitidos para uma área de anexos do cofre.
- Separar transcrições longas em partes menores para análise.
- Selecionar contexto de aulas anteriores e materiais relacionados.
- Consultar repositórios, localizar evidências de código e armazenar caminhos, linhas e referência de commit.
- Conferir a estrutura das respostas da IA e descartar horários ou referências inválidos, conforme as verificações disponíveis.
- Registrar o progresso e reaproveitar análises de trechos que não mudaram.
- Gerar e reconstruir as notas Markdown, índices e links do Obsidian.
- Manter um banco SQLite local para o catálogo, o progresso e os resultados intermediários.

**O Python organiza e verifica aquilo que é verificável por código.** Ele não compreende, sozinho, todas as explicações do professor.

## 5. Para que a IA é usada hoje?

A IA é **opcional** e ajuda a interpretar o conteúdo recebido. Os provedores previstos na versão atual são **Gemini, Groq e OpenRouter**, mediante configuração de chaves e disponibilidade dos respectivos serviços.

O sistema pode solicitar à IA que extraia:
- Resumo do trecho/aula e tipo de encontro.
- Conceitos ensinados ou mencionados e explicações presentes na fonte.
- Ferramentas, atividades, exemplos e acontecimentos relevantes.
- Trechos incertos ou termos que precisam de revisão.
- Possíveis relações entre a fala da aula e evidências localizadas no repositório.

**A IA não é a fonte de verdade.** Um conceito pode ter sido interpretado incorretamente; uma coincidência entre a transcrição e um trecho de código não prova que o professor utilizou aquele código naquela aula.

Quando não há chave, permissão ou cota, o sistema preserva os materiais e sinaliza trabalho pendente. Uma assinatura ChatGPT Plus ou Claude Pro não é necessária para o processamento atualmente implementado.

## 6. O que o Obsidian recebe?

O TRAMA produz arquivos Markdown organizados, em geral, nas seguintes áreas:

| Área | Conteúdo |
| --- | --- |
| `01-Meu-Conhecimento` | Conceitos, módulos, índices e mapa da evolução |
| `02-Minhas-Aulas` | Notas por aula e gravação, resumos e contexto |
| `03-Meus-Projetos` | Repositórios, arquivos e referências de código |
| `90-Sistema` | Estado do processamento e pendências |
| `99-Anexos` | Transcrições originais, documentos e materiais de apoio |

As notas podem conter links internos do Obsidian (`[[conceito]]`), informações de origem e relações entre aulas. Isso permite navegar manualmente pelo conhecimento e utilizar o **Graph View**, além de pesquisar aulas e conceitos.

O mapa de evolução atual mostra a primeira menção **entre as fontes já cadastradas**, possíveis retomadas e vínculos candidatos com código. Ele não comprova domínio do assunto nem representa automaticamente todo o percurso curricular.

A interface do TRAMA também permite consultar uma biblioteca de notas, buscar materiais relacionados e visualizar uma representação do grafo. Isso **não significa que o aplicativo Obsidian completo esteja embutido no TRAMA**.

### Exemplo do resultado esperado

Ao revisar **construtores em C#**, o estudante deve conseguir localizar a aula em que o tema apareceu, o resumo fiel à explicação, exemplos do código realmente registrado, conceitos relacionados e, quando disponível, o link e o minuto da gravação.

Se uma referência não existe nas fontes disponíveis, a nota não deve inventá-la.

O Obsidian precisa ser bom para **leitura humana**. A eventual consulta por ChatGPT, Claude ou outra IA é um uso adicional da biblioteca, não o motivo único de sua organização.

## 6.1 Validação da versão 2.0.0

O instalador Windows foi publicado em 31/10/2026, com `TRAMA_Setup.exe` e `SHA256SUMS.txt`. A execução oficial [GitHub Actions](https://github.com/Marco-Oliver/TRAMA/actions/runs/41180507545) aprovou os testes, gerou o instalador e validou a atualização da 1.9.0 para 2.0.0 com banco e notas de demonstração preservados.

**Pendente:** avaliar a navegação no computador pessoal, o funcionamento com um cofre de aulas reais e a qualidade pedagógica das respostas em um provedor externo. Testes automáticos não garantem interpretação correta de transcrições pelo modelo.

## 7. O que já existe e o que ainda não existe?

| Capacidade | Situação |
| --- | --- |
| Importar transcrições, imagens e documentos suportados | **Disponível na v1.9.0** |
| Registrar links de aulas e organizar gravações | **Disponível na v1.9.0** |
| Importar/indexar repositórios Git | **Disponível na v1.9.0** |
| Gerar resumos estruturados com IA opcional | **Disponível na v1.9.0**, sujeito ao provedor e à qualidade da fonte |
| Gerar Markdown, índices, links e mapa temporal | **Disponível na v1.9.0** |
| Consultar biblioteca e grafo na janela do TRAMA | **Disponível na v1.9.0** |
| Comparar transcrições e evidências de código | **Disponível**, como pistas e hipóteses que precisam de conferência |
| Guardar dúvidas apontadas na análise | **Disponível na v2.0.0**, com histórico de revisões |
| Reabrir automaticamente uma dúvida antiga com evidências da Aula 37 ou 50 | **Implementado parcialmente na v2.0.0**: detecta termos técnicos relacionados e registra pistas, sem confirmar a resolução |
| Corrigir transcrição automaticamente por áudio/vídeo original | **Não implementado** |
| Entrar no Classroom e baixar todas as aulas automaticamente | **Não implementado** |
| Navegar numa árvore completa de arquivos Git como numa IDE | **Não implementado** |
| Conversar com uma IA Professor dentro do TRAMA | **Implementado na v2.0.0** (experimental; qualidade dependente das fontes/modelo) |
| Virar uma plataforma genérica de estudos de qualquer área | **Possibilidade distante, não é foco atual** |

## 8. O que já foi validado?

A versão **1.9.0** foi publicada com instalador Windows produzido pelo GitHub Actions. O processo de publicação passou por testes automatizados de código, criação do executável, instalação, reinstalação e desinstalação no Windows de CI.

Isso **não equivale a testes completos no computador do estudante**. Ainda faltam observações de uso real com WebView2, o cofre do Obsidian, aulas pessoais e limites das contas de IA.

### Correções incorporadas na v2.0.0 (ausentes na v1.9.0)

Três melhorias desenvolvidas originalmente na branch [`fix/critical-audit-20261031`](https://github.com/Marco-Oliver/TRAMA/tree/fix/critical-audit-20261031) agora integram a versão publicada:

1. Evitar que conceitos diferentes como `C`, `C#` e `C++` sejam fundidos.
2. Detectar anexos alterados mesmo quando têm o mesmo tamanho.
3. Ampliar a ocultação de formatos comuns de credenciais em trechos de código.

As três correções estão incorporadas ao instalador público 2.0.0 e passaram por testes em Windows e Linux. **Não estão no instalador anterior, 1.9.0.**

## 9. Limitações conhecidas

- **Fidelidade do conteúdo:** uma IA pode interpretar errado um trecho de fala ou produzir uma explicação incompleta. Referências existentes não comprovam por si só a correção pedagógica.
- **Dúvidas antigas:** a v2.0.0 procura evidências posteriores para termos técnicos reconhecidos e registra o histórico, mas não resolve automaticamente dúvidas semânticas nem confere o áudio original.
- **Privacidade:** o Obsidian, dados SQLite e chaves ficam locais; contudo, material enviado por escolha do usuário a uma IA externa segue as políticas daquele provedor. A ocultação automática de segredos não é infalível.
- **Notas editadas:** há mecanismos para não sobrescrever silenciosamente edições humanas, mas backups e testes de conflito continuam importantes.
- **Atualizações:** o instalador não tem assinatura digital. SHA-256 ajuda a conferir a integridade do download. O upgrade automatizado de v1.9.0 para v2.0.0 passou com cofre de teste e nota manual preservada; bibliotecas pessoais reais ainda devem ser conferidas.
- **Escala e desempenho:** um cenário sintético de 150 aulas passou, mas ainda faltam medições de carga com muitas aulas reais e vários repositórios num computador de recursos limitados.
- **Interface:** testes de backend e instalador não substituem testes visuais em diferentes computadores Windows.

## 9.1 Obsidian excelente — disponível na v2.0.0

As funcionalidades abaixo integram a **v2.0.0 publicada**, após validação automatizada:

- **Guias de revisão por módulo:** páginas organizadas por aula e gravação, com resumos completos guardados na análise, exemplos relatados, dúvidas e conceitos explicados com links para as fontes. Antes, a página do módulo era predominantemente um índice com recortes curtos.
- **Fidelidade e incerteza:** notas de conceitos e o contexto da biblioteca distinguem extrações da IA de termos literalmente encontrados na transcrição. A presença literal de um termo não é tratada como prova de ensino, atividade prática ou domínio do aluno.
- **Explicações preservadas:** diferentes usos ou explicações do mesmo conceito em trechos distintos da gravação são mantidos durante a consolidação, em vez de apenas reter a primeira aparição.
- **Navegação para evidências:** notas de conceitos e guias de revisão direcionam a trechos da própria nota de aula por âncoras temporais extraídas da transcrição; não afirmam que o minuto foi verificado diretamente no vídeo.
- **Código consultável:** correspondências com repositórios GitHub públicos incluem links para a linha no commit analisado e pequenos exemplos de código nas notas de aula; repositórios locais conservam caminho e linha.
- **Busca e links do cofre:** pesquisa de notas mais extensa e tratamento de nomes de notas duplicados sem resolver arbitrariamente a referência para outra aula.
- **Edições manuais protegidas:** quando uma nota do estudante diverge da gerada, o TRAMA mantém a nota e publica uma proposta; propostas idênticas não precisam se multiplicar a cada reconstrução.

**Limites:** resumos e classificação por módulo ainda dependem das fontes e da interpretação da IA. O Obsidian pessoal e o conteúdo real das aulas não foram utilizados nos testes automatizados. A nova geração de notas ainda precisa de validação prática no computador do estudante, mesmo depois da publicação.

A versão 2.0.0 também inclui a automação confiável e a IA Professor experimental, descritas nas seções seguintes.

## 9.2 Automação confiável — disponível na v2.0.0

As funcionalidades abaixo integram a **v2.0.0 publicada**, construída sobre as melhorias anteriores. A versão 1.9.0 não as inclui:

### Dúvidas antigas e novas evidências

- Dúvidas apontadas na análise são guardadas separadamente no banco SQLite, com status, origem, hash da transcrição e histórico de revisões.
- Quando uma gravação posterior cita um termo técnico reconhecido ou o índice do repositório contém código relacionado, o sistema adiciona a **evidência identificada** à dúvida anterior.
- A dúvida muda para **nova evidência para revisar**, e não para resolvida. Repetir o mesmo termo mal transcrito não é considerado nova comprovação; o objetivo é facilitar a investigação.
- Cada atualização significativa conserva um registro próprio, com o estado anterior e as fontes presentes naquela revisão. Reconstruir o cofre repetidamente sem novas evidências não deve gerar histórico duplicado.
- O Obsidian recebe um **Índice de Dúvidas** e páginas individuais com fonte original, termo candidato quando identificável, evidências posteriores e histórico. São notas auxiliares, sem alteração das transcrições.
- Quando uma dúvida desaparece após nova análise, o registro antigo é arquivado, não apagado.

**Limitação importante:** a identificação automática de termos depende de um vocabulário técnico limitado e de menções verificáveis. Questões sem correspondência suficiente continuam pendentes; não existe garantia de resolução semântica e não há verificação automática do áudio original.

### Integridade, processamento e recuperação

- A integridade das transcrições guardadas no cofre é verificada por SHA-256 antes do processamento, inclusive quando existe análise em cache. Se um arquivo estiver corrompido ou alterado, o TRAMA interrompe a operação e pede revisão, sem enviar a fonte modificada à IA.
- A reconstrução automática de Markdown também verifica as transcrições antes de modificar notas.
- Trechos já analisados permanecem salvos no SQLite; uma interrupção por cota permite continuar sem repetir os trechos concluídos, quando o contexto das fontes não mudou.
- A geração global do Markdown é realizada após a análise do lote, evitando reconstruções repetitivas para cada gravação. As análises e estados continuam persistidos progressivamente.
- As três correções críticas de integridade, distinção entre linguagens e ocultação de credenciais permanecem incluídas por herança da branch anterior.

### Backup e restauração

- Em **Ajustes**, o usuário pode autorizar a criação de um **ZIP local verificado**, contendo as notas Markdown, anexos e uma cópia consistente do banco SQLite, inclusive configurações locais do Obsidian quando presentes no cofre.
- O sistema gera um manifesto com tamanhos e hashes SHA-256 dos arquivos; verifica que não houve alteração durante a cópia. Um backup pré-existente não deve ser sobrescrito.
- Em **Ajustes**, também é possível **Restaurar backup em uma pasta nova**, selecionando o ZIP e a pasta que receberá o cofre restaurado. O arquivo é verificado e restaurado primeiro em área temporária; o cofre ativo não é substituído.
- Backup e restauração também têm comandos de linha de comando, úteis para manutenção. A restauração exige uma pasta nova, nunca um cofre existente.
- **Os backups não são criptografados e não são enviados ao GitHub**; a pessoa precisa guardá-los em local privado.

Comandos disponíveis para uso técnico:

```powershell
python main.py backup --vault "C:\\Meu-Obsidian" --backup "C:\\Backups\\TRAMA_Backup.zip"
python main.py restore --backup "C:\\Backups\\TRAMA_Backup.zip" --restore-to "C:\\Meu-Obsidian-Restaurado"
```

### O que estes avanços não significam

- A IA não confirma sozinha que o professor realmente falou um termo.
- A biblioteca pode continuar contendo classificações por módulo baseadas em palavras-chave, sujeitas a revisão.
- Testes com acervos fictícios não provam desempenho nem fidelidade do conteúdo real no computador pessoal.
- A restauração sempre cria uma nova pasta; **não é migração automática ou atualização do instalador**.
- A versão 2.0.0 foi publicada após auditoria, testes de regressão, adversariais, compilação do executável, instalação, reinstalação, desinstalação e teste de atualização real a partir da 1.9.0 em ambiente Windows de CI.

## 9.3 IA Professor — disponível na v2.0.0 (experimental)

A **v2.0.0 publicada** acrescenta uma aba de **IA Professor**, separada da automação que produz notas. Não está presente no instalador anterior, 1.9.0.

### O que faz

- **Explicar e revisar:** o aluno pergunta sobre um conteúdo que aparece nas notas do Obsidian. O TRAMA procura trechos relevantes e um modelo de IA produz uma explicação em português.
- **Criar desafios:** o modelo propõe atividades progressivas ligadas ao material encontrado, sem entregar a solução completa imediatamente.
- **Corrigir código:** o aluno cola um trecho e recebe observações, pistas e explicações, sem que o aplicativo execute esse código.
- **Continuar a conversa:** perguntas e respostas recentes são utilizadas apenas enquanto a janela permanece aberta. O aluno pode iniciar uma nova conversa; o histórico não vira arquivo no Obsidian.
- **Consultar as fontes:** cada resposta traz referências às notas realmente selecionadas para aquela consulta, com botão para abri-las na biblioteca. O sistema rejeita respostas sem uma referência válida ao conjunto fornecido.

### Como funciona

1. O aluno seleciona um modo, escreve uma pergunta e, se necessário, cola um trecho de código.
2. O Python **consulta somente arquivos Markdown do cofre selecionado**, sem utilizar serviços externos para realizar a busca. A seleção usa termos do assunto, título, caminho e conteúdo das notas, com contexto limitado.
3. O aplicativo solicita **autorização explícita a cada envio**. Apenas então envia a pergunta e os trechos selecionados a um provedor gratuito configurado.
4. Gemini, Groq ou OpenRouter, conforme as chaves e cotas configuradas pelo estudante, gera a resposta. O modelo deve tratar as fontes como dados não confiáveis, respeitar o conteúdo documentado e declarar limitações.
5. O aplicativo verifica se as referências devolvidas pelo modelo pertencem às notas efetivamente recuperadas. Se não houver fonte apropriada, não solicita resposta à IA e informa que falta material.
6. A resposta aparece em uma conversa dentro do TRAMA. **Nenhuma nota, transcrição, repositório ou banco de dados é alterado pela IA Professor.**

### Segurança, privacidade e limites

- Chaves continuam protegidas pelo Windows DPAPI; o recurso não depende de ChatGPT Plus ou Claude Pro e não usa uma assinatura dessas ferramentas como API.
- O envio de dados à IA depende de consentimento explícito; os provedores externos têm suas próprias políticas, cotas e condições de cobrança.
- A conversa existe apenas na memória da sessão do aplicativo. Não há armazenamento automático de histórico no Obsidian.
- Código colado **não é executado**. O TRAMA oculta formatos comuns de credenciais do contexto enviado, mas isso não detecta todos os segredos: o usuário deve remover tokens e senhas antes de enviar.
- O sistema confirma que uma referência de nota existe entre as fontes consultadas; **isso não comprova que cada afirmação produzida pelo modelo esteja correta**. O aluno deve conferir as evidências em casos importantes.
- A qualidade pedagógica depende do material presente no cofre e do modelo gratuito disponível. A IA Professor não garante equivalência ao ChatGPT ou Claude.
- Não há treinamento de um modelo próprio; o Python faz busca, seleção e validações, e o provedor de IA redige a resposta.

**Objetivo de aceitação:** explicar Hello World com as aulas reais, gerar desafios compatíveis com o conteúdo registrado, comentar um exercício de C# sem utilizar recursos não estudados e citar notas realmente presentes. Esses testes de qualidade pedagógica com material pessoal ainda precisam de avaliação humana.

## 10. Próximas evoluções e validação prática do TRAMA

As três prioridades **já foram implementadas na versão 2.0.0**. O foco seguinte é validar a experiência com material real e aperfeiçoar pontos que apresentarem dificuldades. Não confundir melhorias entregues com validação pedagógica ainda pendente.

### 1. Obsidian excelente

**Disponível na v2.0.0.** Os pontos de revisão e navegação foram implementados, mas exigem conferência com material real.

A v2.0.0 já aprimora a qualidade, a legibilidade e a navegação das notas de aulas, módulos, conceitos e projetos. A revisão com transcrições e exemplos reais continua necessária para aferir a fidelidade e a completude.

### 2. Automação confiável

**Implementação disponível na v2.0.0.** A validação com o cofre real do estudante ainda depende do Windows pessoal.

A v2.0.0 já verifica integridade das transcrições, guarda evidências e revisões de dúvidas, permite backup e recuperação e foi validada automaticamente no Windows. O fluxo completo com dados reais ainda exige teste prático e observação de desempenho.

### 3. IA Professor (experimental na v2.0.0)

O recurso experimental de conversa, explicações, desafios e revisão de código integra a v2.0.0 publicada. Sua qualidade ainda depende de respostas com o cofre real e da avaliação visual no Windows. A IA Professor não escreve no cofre e não substitui o processo de organização do Obsidian.

### Ideias comentadas, sem desenvolvimento previsto agora

Um explorador de arquivos dos repositórios dentro do TRAMA e, no futuro, uma versão de estudos aplicável a outras áreas. Essas ideias não alteram o foco atual.

---

**Resumo:** o TRAMA automatiza a transformação de materiais de estudo em um Obsidian organizado. A biblioteca deve continuar acessível, compreensível e útil para o estudante independentemente do próprio TRAMA. Este documento pode ser atualizado conforme as funcionalidades do sistema evoluírem.

## 11. Revisão de qualidade após o lançamento 2.0.0

Esta seção descreve o funcionamento da **revisão ainda não publicada**, guardada na branch
[`fix/quality-personas-ui-security-20261031`](https://github.com/Marco-Oliver/TRAMA/tree/fix/quality-personas-ui-security-20261031).
A versão pública permanece **2.0.0** até a revisão ser integrada e uma nova distribuição ser aprovada.

### 11.1 Estudo com a IA Professor

O Professor é um recurso opcional de **leitura do Obsidian**. Na revisão, ele continua com os três modos:
explicação/revisão, desafios progressivos e revisão de código colado. O Python escolhe trechos
das aulas, conceitos e projetos; uma IA externa produz a explicação. A consulta só acontece
com consentimento para enviar dados ao provedor, sem executar código ou modificar o cofre.

A seleção de fontes foi reforçada para **não enviar a pasta de anotações pessoais à API**
e para **não escolher aulas aleatórias quando um desafio cita um assunto ausente**.
Perguntas e respostas antigas utilizadas como contexto recebem novamente a ocultação
de credenciais antes do envio. Esses filtros reduzem o risco, mas não substituem a revisão
do material pelo próprio estudante.

A IA pode interpretar uma nota incorretamente ou citar um documento sem provar a conclusão.
As referências identificam notas consultadas, não uma garantia de veracidade. As
conversas persistem somente na memória da janela e podem ser limpas com "Nova conversa".

### 11.2 Navegação e aparência

A interface da revisão mantém a aparência de aplicativo Windows compacto, com seções claras:
Início, Aulas, Conhecimento, Projetos, Biblioteca, IA Professor e Ajustes.

- A página Início orienta a sequência **conectar cofre → importar materiais → estudar**.
- A busca principal tem botão **Buscar** e abre a Biblioteca com a consulta.
- A lista de aulas tem filtros funcionais **Todas**, **Recentes** e **Favoritas**;
  favoritos marcados na biblioteca refletem na lista.
- Links internos `[[nota]]` com títulos repetidos **não são direcionados arbitrariamente
  para outra aula**: o link ambíguo permanece sem destino até haver referência específica.
- A árvore de pastas e controles utilizam classes CSS compatíveis com a política
  de segurança do aplicativo. Os estilos não requerem liberar CSS inline.
- A interface possui rótulos de navegação e foco visível para teclado, além de
  ajustes para janelas de tamanhos diferentes.
- A aba IA Professor exibe fontes consultadas para abertura na biblioteca;
  mostra claramente quando consentimento, código ou conteúdo de aula estão ausentes.

### 11.3 Instalar e atualizar

Para uso normal no Windows, não é necessário Python nem terminal:
baixa-se o `TRAMA_Setup.exe` da página oficial do GitHub e instala-se pelo assistente.

Em **Ajustes → Verificar atualizações**, o usuário consulta uma nova versão.
Quando disponível, **Baixar e instalar nova versão** baixa a distribuição oficial,
verifica seu SHA-256 e pergunta antes de iniciar o instalador. Não há atualização silenciosa.
É recomendável usar **Criar backup local (.zip)** antes de migrar. **Restaurar backup**
usa uma pasta nova e não sobrescreve o cofre aberto.

O instalador ainda **não tem assinatura digital**. O aviso de editor desconhecido no
Windows é esperado, mas o usuário deve confirmar a origem e o SHA-256 antes de executar.
O ZIP de backup não é criptografado; mantenha-o em local privado.

### 11.4 Qualidade e testes

A revisão contém cenários com alunos fictícios de C#, Angular, revisão de código,
desafios, conteúdo ausente, tentativas de instruções maliciosas, proteção de segredos
em histórico e validação de citações. Os modelos nesses testes são **simulados**:
avaliam o comportamento do sistema, não a qualidade pedagógica de um Gemini real.

A validação automatizada também executa a bateria de `unittest` em Linux e Windows,
cenários adversariais, auditoria de arquivos, navegador automatizado com telas e botões
e o ciclo de compilação, instalação, reinstalação e desinstalação do Windows.

**Limite de aceitação:** mesmo que o aplicativo passe nesses testes,
a qualidade das explicações com aulas reais e o acabamento visual no Windows do
estudante exigem avaliação manual. Não apresentar resposta simulada como certificação
pedagógica nem prometer ausência total de bugs ou vulnerabilidades.


## 12. Segurança adicional — revisão após a v2.0.0

Esta revisão **ainda não integra o instalador público**. O código fica em
[`fix/security-hardening-20261102`](https://github.com/Marco-Oliver/TRAMA/tree/fix/security-hardening-20261102),
sobre a auditoria de interface e automação anterior.

### Proteção de arquivos e atualização

- Abrir um anexo pelo aplicativo exige que o arquivo esteja **dentro do cofre** e que seu
  caminho esteja registrado no catálogo SQLite como vídeo, material ou transcrição. Um
  arquivo arbitrário do cofre não pode ser aberto só porque possui extensão aceita.
- Páginas de atualização abrem exclusivamente endereços canônicos de releases por
  versão do repositório configurado. URLs manipuladas ou malformadas são recusadas.
- Links externos cadastrados são validados antes da abertura, incluindo rejeição de
  caracteres de controle e credenciais no endereço.
- Backups ZIP são extraídos somente em pasta nova e recebem inspeção adicional de
  nomes reservados no Windows, duplicações de caminho e compressão suspeita, além
  de verificar o espaço disponível e o SHA-256 de cada arquivo.

### Como a segurança é testada

Os testes incluem tentativas de abrir arquivos privados não cadastrados, links com rotas
maliciosas, endereços de vídeo malformados, arquivos ZIP com nomes especiais do Windows
e respostas de IA contendo HTML perigoso. Nada disso é executado deliberadamente;
os testes conferem se o aplicativo rejeita ou exibe o material como texto.

O GitHub Actions também executa verificações de dependências e análise estática.
**Não há garantia de ausência total de vulnerabilidades**. As chamadas para modelos
externos podem revelar o contexto autorizado ao provedor, mesmo quando não contêm
credenciais óbvias; o próprio aluno deve selecionar fontes adequadas.

**Status de distribuição:** ainda não publicado; a v2.0.0 permanece como última
versão estável enquanto a revisão aguarda testes automatizados e avaliação manual.

### 12.1 Cobertura visual contra falsos resultados

A auditoria visual foi reforçada após inspecionar as capturas geradas: o simulador de API
do navegador continha uma referência não definida, mas a interface tratava a exceção
como aviso e o teste anterior passava apesar de a nota ficar vazia. O simulador foi
corrigido e agora **o teste falha se a nota não aparecer ou se houver aviso de erro**
no aplicativo. A busca global deve selecionar uma nota correspondente ao filtro,
e o botão Recentes ordena corretamente as datas reais em formato DD/MM/AAAA.
As verificações são executadas tanto no arquivo HTML de desenvolvimento quanto
no HTML empacotado na janela Windows. Elas não substituem testes manuais com dados reais.


### 12.2 Navegação em janelas compactas

Na janela de aproximadamente 800–980 px, o menu mantém rótulos legíveis e os
conteúdos permanecem disponíveis. Os botões de abas podem rolar horizontalmente.
Os testes visuais incluem uma verificação de que o texto "Conhecimento" não fica
cortado pelos limites do botão, além dos controles e conteúdos já validados.


### 12.3 Política de segurança da janela instalada

O aplicativo Windows reúne CSS e JS locais no HTML embutido, mas não precisa deixar
a janela sem política de segurança. A montagem passou a incluir uma **Content Security
Policy restritiva** com hashes SHA-256 para os estilos e scripts próprios do TRAMA,
bloqueando scripts externos e inline não autorizados e conexões de rede diretas da
página. A interface continua usando sua API local permitida. Os testes cobrem
tanto a janela empacotada quanto a página de desenvolvimento, incluindo tentativas
de injetar HTML malicioso por respostas da IA.

Essa proteção é uma barreira adicional, não garantia contra qualquer exploração do
WebView ou de componentes nativos; por isso o usuário continua responsável por
evitar materiais ou links suspeitos e o código deve manter suas validações de entrada.

