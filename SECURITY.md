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
