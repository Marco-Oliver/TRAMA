# TRAMA — Como o sistema funciona

**Estado documentado:** 31 de outubro de 2026  
**Versão pública:** 1.9.0 (Windows)  
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

## 7. O que já existe e o que ainda não existe?

| Capacidade | Situação |
| --- | --- |
| Importar transcrições, imagens e documentos suportados | **Disponível na v1.9.0** |
| Registrar links de aulas e organizar gravações | **Disponível na v1.9.0** |
| Importar/indexar repositórios Git | **Disponível na v1.9.0** |
| Gerar resumos estruturados com IA opcional | **Disponível na v1.9.0**, sujeito ao provedor e à qualidade da fonte |
| Gerar Markdown, índices, links e mapa temporal | **Disponível na v1.9.0** |
| Consultar biblioteca e grafo na janela do TRAMA | **Disponível na v1.9.0** |
| Comparar transcrições e evidências de código | **Disponível parcialmente**, com relações e hipóteses a conferir |
| Guardar dúvidas apontadas na análise | **Disponível de forma simples** |
| Reabrir automaticamente uma dúvida antiga com evidências da Aula 37 ou 50 | **Ainda não implementado como ciclo completo** |
| Corrigir transcrição automaticamente por áudio/vídeo original | **Não implementado** |
| Entrar no Classroom e baixar todas as aulas automaticamente | **Não implementado** |
| Navegar numa árvore completa de arquivos Git como numa IDE | **Não implementado** |
| Conversar com uma IA Professor dentro do TRAMA | **Não implementado** |
| Virar uma plataforma genérica de estudos de qualquer área | **Possibilidade distante, não é foco atual** |

## 8. O que já foi validado?

A versão **1.9.0** foi publicada com instalador Windows produzido pelo GitHub Actions. O processo de publicação passou por testes automatizados de código, criação do executável, instalação, reinstalação e desinstalação no Windows de CI.

Isso **não equivale a testes completos no computador do estudante**. Ainda faltam observações de uso real com WebView2, o cofre do Obsidian, aulas pessoais e limites das contas de IA.

### Correções que ainda não estão no instalador

Uma branch separada, [`fix/critical-audit-20261031`](https://github.com/Marco-Oliver/TRAMA/tree/fix/critical-audit-20261031), contém três melhorias:

1. Evitar que conceitos diferentes como `C`, `C#` e `C++` sejam fundidos.
2. Detectar anexos alterados mesmo quando têm o mesmo tamanho.
3. Ampliar a ocultação de formatos comuns de credenciais em trechos de código.

Essas alterações passaram em **97 testes de regressão e 10 cenários adversariais em Linux**, e os mesmos resultados em **Windows**. **Não estão incorporadas à versão pública 1.9.0.**

## 9. Limitações conhecidas

- **Fidelidade do conteúdo:** uma IA pode interpretar errado um trecho de fala ou produzir uma explicação incompleta. Referências existentes não comprovam por si só a correção pedagógica.
- **Dúvidas antigas:** o mapa relaciona conceitos entre aulas, mas ainda não investiga e atualiza automaticamente hipóteses antigas quando chegam novas evidências.
- **Privacidade:** o Obsidian, dados SQLite e chaves ficam locais; contudo, material enviado por escolha do usuário a uma IA externa segue as políticas daquele provedor. A ocultação automática de segredos não é infalível.
- **Notas editadas:** há mecanismos para não sobrescrever silenciosamente edições humanas, mas backups e testes de conflito continuam importantes.
- **Atualizações:** o instalador não tem assinatura digital. SHA-256 ajuda na integridade do download; a migração completa entre versões com bibliotecas reais ainda precisa de testes.
- **Escala e desempenho:** o comportamento com um conjunto grande, na ordem de 100–200 aulas e vários repositórios, ainda precisa de medição controlada.
- **Interface:** testes de backend e instalador não substituem testes visuais em diferentes computadores Windows.

## 10. Próximas evoluções do TRAMA

As melhorias serão avaliadas nesta ordem. **Elas estão planejadas e não devem ser confundidas com o que já foi entregue.**

### 1. Obsidian excelente

Aperfeiçoar a qualidade, a completude, a legibilidade e a navegação das notas: aulas, módulos, conceitos, códigos, links, horários e mapa de relações. O resultado deve ser útil para revisão manual sem depender de nenhuma IA conectada.

### 2. Automação confiável

Melhorar integridade, segurança, preservação de dados, desempenho e validação no Windows. Evoluir o cruzamento de fontes para guardar dúvidas, encontrar novas evidências em aulas posteriores e registrar revisões **sem modificar as fontes originais**.

### 3. IA Professor (futura)

Estudar uma ferramenta de conversa dentro do TRAMA que **apenas leia** a biblioteca, explique tópicos conforme as aulas, proponha desafios e ajude na revisão. Ela não deve editar o cofre e só fará sentido se a qualidade das respostas for realmente útil.

### Ideias comentadas, sem desenvolvimento previsto agora

Um explorador de arquivos dos repositórios dentro do TRAMA e, no futuro, uma versão de estudos aplicável a outras áreas. Essas ideias não alteram o foco atual.

---

**Resumo:** o TRAMA automatiza a transformação de materiais de estudo em um Obsidian organizado. A biblioteca deve continuar acessível, compreensível e útil para o estudante independentemente do próprio TRAMA. Este documento pode ser atualizado conforme as funcionalidades do sistema evoluírem.
