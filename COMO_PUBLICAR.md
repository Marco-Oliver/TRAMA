# Como publicar o TRAMA

O código-fonte do projeto já está no GitHub. A **v2.0.1 foi publicada e testada** em [Releases](https://github.com/Marco-Oliver/TRAMA/releases/tag/v2.0.1).

## Fluxo para as próximas versões

1. Desenvolva em branch própria e abra um pull request para a `main`.
2. Execute os testes de regressão e segurança e, para releases Windows, a auditoria completa (incluindo instalador, navegador e migração da versão pública anterior).
3. Atualize a versão de forma consistente no Python, no instalador Inno Setup e na interface. Revise o teste de upgrade para partir da versão oficial anterior.
4. Após os testes, integre o pull request. A publicação oficial é iniciada por uma alteração deliberada em `tools/release-trigger.txt` na `main`.
5. O workflow `.github/workflows/release.yml` compila, verifica o SHA-256, testa instalação/upgrade e cria a tag e os artefatos. **Ele não sobrescreve uma versão já publicada.**
6. Confirme o resultado em [GitHub Actions](https://github.com/Marco-Oliver/TRAMA/actions) e [Releases](https://github.com/Marco-Oliver/TRAMA/releases).

**Nunca publique** chaves de API reais, vaults do Obsidian, transcrições pessoais, bancos SQLite, arquivos de configuração local ou credenciais.

O usuário pode baixar o [instalador mais recente](https://github.com/Marco-Oliver/TRAMA/releases/latest/download/TRAMA_Setup.exe) sem usar Python ou terminal. O programa mantém credenciais e materiais localmente; APIs externas só recebem conteúdo autorizado.
