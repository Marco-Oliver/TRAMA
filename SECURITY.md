# Privacidade e segurança do TRAMA

Este repositório publica exclusivamente código e testes fictícios.

- As chaves de IA são configuradas no Windows do usuário e protegidas localmente com DPAPI.
- Obsidian, transcrições reais, arquivos pessoais, caminhos locais e bancos SQLite ficam apenas na máquina de cada pessoa.
- O GitHub Actions compila sem acessar nenhuma chave Gemini, Groq ou OpenRouter.
- O aplicativo deve conferir o hash SHA-256 do instalador e pedir autorização antes de executar a atualização. Um hash não substitui assinatura digital de editor.
- Não habilitar faturamento nem selecionar serviços pagos automaticamente.
- Se uma chave for exposta, revogue-a no provedor e gere outra.
