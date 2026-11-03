# Privacidade e segurança do TRAMA

Este repositório contém somente o aplicativo, documentação técnica e testes fictícios.

- Chaves de API são informadas **pelo usuário no próprio Windows**, protegidas localmente via DPAPI.
- O cofre Obsidian, PDFs, transcrições, prints, links privados, bancos SQLite, logs e preferências **não** são publicados aqui.
- O compilador no GitHub Actions usa dependências públicas e **não precisa de nenhuma chave Gemini**.
- O aplicativo não ativa faturamento; o usuário deve configurar um projeto gratuito sem billing. Serviços externos têm suas próprias políticas e cotas.
- Testes públicos usam apenas material sintético. Não adicione dados reais de aulas sem autorização.
- Se uma credencial tiver sido exposta, revogue-a no provedor e crie outra.
- O instalador ainda não possui assinatura de código; o Windows pode mostrar aviso SmartScreen.
- O arquivo SHA256SUMS.txt verifica integridade do download, mas não equivale a assinatura digital de autor.

## Proteções adicionais em revisão (ainda não publicadas)

A branch `fix/security-hardening-20261102`, construída sobre a revisão de qualidade, inclui:

- Abertura de anexos permitida **somente se o caminho estiver dentro do cofre E cadastrado no SQLite** como material, transcrição ou vídeo; a API da janela não deve funcionar como explorador arbitrário de arquivos.
- Páginas de atualização devem ter URL canônica de tag de versão dentro do repositório oficial; caminhos de aparência semelhante, parâmetros e fragmentos são recusados.
- Links de vídeo rejeitam URLs inválidas, credenciais embutidas e caracteres de controle.
- ZIPs de restauração recusam nomes reservados no Windows, duplicatas sem distinção de maiúsculas/minúsculas, compressão extremamente suspeita e restaurações com espaço insuficiente.
- Testes simulam payload HTML em resposta da IA, tentativas de acesso indevido ao cofre e arquivos ZIP manipulados.
- GitHub Actions executa testes de regressão, cenários adversariais, navegador, instalação Windows, `pip-audit` e análise estática `bandit`.

### Limites que continuam importantes

- **Sem assinatura de código:** SHA-256 hospedado junto ao instalador verifica integridade, não prova a identidade do autor. Confira a origem da release e não execute instaladores de terceiros.
- **IA externa:** somente envie conteúdos que esteja disposto a revelar ao provedor escolhido. Máscaras de credenciais podem falhar para formatos desconhecidos.
- **Arquivos locais e backups:** ZIPs não têm criptografia. Qualquer pessoa com acesso ao seu Windows e aos seus arquivos pode conseguir ler o cofre e backups.
- **Notas não confiáveis:** renderização em HTML é protegida por escape e testes anti-injeção, mas uma interface desktop conectada a arquivos locais não é uma sandbox universal. Não importa material executável suspeito nem dê permissões extras ao aplicativo.
- **Verificação:** análises estáticas e testes não demonstram ausência total de vulnerabilidades; revisões independentes e testes em Windows real continuam úteis.

A branch está separada da versão pública 2.0.0; não afirmar que os ajustes estão disponíveis no instalador até haver publicação.

## CSP da interface Windows (revisão ainda não publicada)

O HTML da janela Windows inclui CSP restritiva com hashes SHA-256 calculados para
cada script e folha de estilos locais incorporados. Isso impede a execução de
scripts inline não autorizados e carregamento de código remoto pela página,
sem abrir exceções como `unsafe-inline` ou `unsafe-eval`.
O aplicativo mantém API nativa explícita e validações de dados separadas da CSP.

## Provedores e arquivos não confiáveis

- O tráfego de IA exige HTTPS para um dos três hosts oficiais permitidos
  (Gemini, Groq ou OpenRouter), sem credenciais na URL, portas incomuns ou
  redirecionamentos HTTP. As respostas são limitadas a 2 MB.
- Arquivos DOCX utilizam um parser XML protegido (defusedxml) para recusar
  entidades XML hostis; seu conteúdo é lido localmente antes do consentimento
  de envio à IA.
- Notas do Professor usam somente as três pastas de estudo, sem enviar caminhos
  nem nomes de arquivos; tokens e identificadores comuns são ocultados.
- Essas medidas reduzem riscos conhecidos, mas não prometem isolamento contra
  software malicioso executado com as mesmas permissões do usuário.
