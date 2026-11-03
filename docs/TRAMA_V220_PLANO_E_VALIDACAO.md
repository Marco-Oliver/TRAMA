# TRAMA 2.2.0 — Plano vivo de implementação e validação

> **Estado: em desenvolvimento.** Esta branch é um rascunho e não altera o instalador
> 2.1.0 instalado, a branch `main`, o cofre Obsidian real nem chaves de API.

## Missão e ordem de prioridade

TRAMA é, antes de tudo, uma **automação de materiais de estudo**: arquivos TXT,
documentos, imagens e links públicos de código são associados a aulas e
transformados em notas Markdown locais e verificáveis no Obsidian. A IA Professor
é uma consumidora dessa base, não seu objetivo principal.

1. **Automação incremental:** importar poucas aulas por sessão, sem reprocessar
   todas as análises antigas ou duplicar material.
2. **Qualidade das notas:** sínteses claras, conteúdo da fonte preservado,
   explicações com evidência de horários e código, dúvidas e lacunas explícitas.
3. **Conexões específicas:** uma aula futura pode fornecer evidência para uma
   questão de outra aula, sem revisar indiscriminadamente todo o histórico.
4. **Segurança e integridade:** backups restauráveis, propostas de alteração para
   notas editadas pelo usuário, consentimento revogável, nenhum envio implícito.
5. **UX desktop clássica:** ações compreensíveis no próprio TRAMA, avisos legíveis,
   nenhum popup `prompt/confirm` do navegador e nenhuma janela CMD de Git.
6. **IA Professor:** preservar e corrigir falhas importantes, sem deslocar
   recursos das prioridades anteriores.

## Decisões implementadas nesta branch

- Janela interna para incluir repositórios GitHub públicos ou pastas Git locais.
- Avisos e confirmações internas com visual coerente.
- Consoles ocultos para comandos Git no Windows.
- Preferência revogável de autorização para envio à API, ativada somente em
  **Ajustes**; operações continuam exigindo acionamento pelo usuário.
- Resumo mais didático no prompt do extrator e remoção do prefixo desnecessário
  de parte única.
- Registros de pendências em notas originais enriquecidos com evidências
  posteriores verificáveis. **Evidência não implica resolução automática.**
- Referências de código GitHub clicáveis apenas quando o commit, o arquivo e a
  linha constam no índice local, com validação também no backend.
- Restauração de backup com suporte inicial a caminhos longos Windows.
- Botão Atualizar visível e notas/conversa mais legíveis, mantendo o estilo TRAMA.

## Testes de regressão previstos

- Reimportação de aulas com reutilização de análises já registradas.
- Curso fictício de **150 aulas cadastradas em 25 sessões de seis**.
- Questionamento da Aula 031 que só encontra indício de esclarecimento na
  Aula 050; a Aula 049 não deve alterar a pendência.
- Backup e restauração de ZIP com diretórios GitHub longos, preservando o cofre
  original; rejeição de caminho malicioso e destino existente.
- API de consentimento: ativar, revogar, impedir autorização em caso de falha
  de persistência.
- Git: subprocesso no Windows sem janela de console.
- GitHub: URLs externas arbitrárias, caminhos escapados, SHA divergente e linhas
  não indexadas não podem ser abertas por comandos privilegiados do TRAMA.
- Revisão de regressões e testes adversariais da versão 2.1.0, incluindo
  varredura de segredos e qualidade das dependências.

## Critérios obrigatórios antes de disponibilizar instalador

- [ ] CI automatizado aprovado em Linux **e** Windows.
- [ ] Teste do executável Windows compilado e do instalador local.
- [ ] Restauração real em Windows com caminhos longos e cofre independente.
- [ ] Teste de uso visual das janelas GitHub, confirmação, notas e chat.
- [ ] Revisão humana da qualidade de resumos produzidos por IA em materiais
      consentidos ou inteiramente fictícios.
- [ ] Verificação de importação incremental, proteção `.PROPOSTA` e ausência
      de chamadas externas quando não houver autorização.
- [ ] Documentação final, versão e fluxo de atualização alinhados.
- [ ] Revisão explícita antes de merge, tag ou publicação de release.

## Limitações e honestidade da validação

Testes sintéticos verificam consistência, segurança e estrutura, mas **não
comprovam por si só** que um modelo externo produzirá resumos excelentes. Isso
exige uma amostra avaliada por critérios de fidelidade, utilidade didática e
evidência de código. Links de gravações não implicam leitura do vídeo. Sem áudio
do original, uma transcrição ambígua permanece identificada como incerta.

A restauração com prefixo de caminho longo no Windows é uma primeira correção
técnica; a causa exata do erro observado pelo usuário ainda requer confirmação
no ambiente Windows. O cofre original não deve ser usado como destino de teste.

## Fluxo de desenvolvimento

Todas as mudanças de código ficam em `feat/v2.2.0-automation-foundations`
e em Pull Request **draft**. A `main` continua estável.
Não cadastrar dados do usuário nem chaves no GitHub; usar fixtures artificiais
no CI. Nenhum instalador deve ser publicado automaticamente a partir desta branch.
