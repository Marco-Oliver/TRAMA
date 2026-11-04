# TRAMA Preview — atualizações sem ZIP

## Como funciona para quem usa

A Preview tem AppId, atalhos, instalador e preferências separados do TRAMA estável.
Não acessa as chaves nem as configurações da versão estável.

- Ao abrir Ajustes, uma Preview nova consulta o canal experimental do GitHub.
- Se houver uma versão mais recente publicada, o botão de atualização permite baixar o EXE.
- O instalador é verificado por SHA-256 e só é aberto após autorização do usuário.
- A instalação não é silenciosa: o Windows continua pedindo confirmação.
- O cofre de teste e as notas originais permanecem no dispositivo.

**Primeira atualização:** a Preview instalada antes desta alteração tem o canal experimental desativado.
Ela precisará de uma última instalação manual da primeira Preview com este recurso.
Depois, as próximas versões publicadas poderão ser obtidas dentro do aplicativo.

## Contrato para publicação do canal Preview

O GitHub Actions produz arquivos temporários (artifacts), que expiram.
Para o atualizador baixar sem ZIP e sem token GitHub do usuário, é preciso
publicar manualmente a versão já validada como GitHub Release *prerelease*.

- Repositório exclusivo: Marco-Oliver/TRAMA.
- Tag: v2.2.0-preview.N, sendo N o github.run_number da CI que gerou o instalador.
- Release: prerelease=true, draft=false. Nunca publicar como release estável.
- Asset: TRAMA_Preview_Setup.exe.
- Manifesto: SHA256SUMS-Preview.txt, referente ao mesmo EXE.
- Fonte de listagem: API pública /repos/Marco-Oliver/TRAMA/releases?per_page=40.
- Verificar os quatro jobs da CI aprovados, inclusive instalador Windows.
- Não publicar um artefato antigo sob a tag de um build novo.

A Preview só seleciona tags compatíveis maiores que sua versão instalada.
Releases estáveis, versões de outros produtos e drafts nunca são elegíveis.

## Publicação exige aprovação

Este fluxo de trabalho gera um artefato para QA, não uma release.
Somente com aprovação explícita deve-se criar a tag/release prerelease
e anexar EXE + SHA-256 do mesmo build validado.
Uma Preview publicada será visível para qualquer usuário desse canal público.

## Limitações ainda a validar

Os testes automatizados simulam a API GitHub, download, integridade, atualização
e bloqueio de canais mistos. A CI exercita instalação e reinstalação isoladas.
O fluxo completo com uma release experimental REAL ainda depende da autorização
para publicar essa release e de um teste final no Windows do usuário.
