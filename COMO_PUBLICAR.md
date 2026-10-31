# Como publicar o TRAMA

A automação de compilação está preparada, mas o código-fonte completo ainda precisa ser importado.

## Importação única
1. Baixe o pacote TRAMA_GitHub_Source_1_9.tar.gz disponível na conversa.
2. Acesse este repositório e escolha Add file > Upload files.
3. Envie o pacote sem extrair, na raiz do repositório, e confirme o commit.
4. O GitHub Actions verifica o SHA-256 do pacote, extrai o código auditado, roda os testes, publica as fontes e dispara a compilação Windows.
5. Se a compilação e os testes passarem, um release disponibilizará TRAMA_Setup.exe.

Link permanente depois da publicação bem-sucedida:
https://github.com/Marco-Oliver/TRAMA/releases/latest/download/TRAMA_Setup.exe

O link NÃO funciona antes da primeira publicação de release.

Nunca envie: chaves de API, cofre Obsidian, transcrições privadas, banco SQLite, arquivos .env ou credenciais.
