<div align="center">

<img src="assets/trama-logo-64.png" width="84" alt="Símbolo verde do TRAMA" />

# TRAMA

### Transforme aulas soltas em uma biblioteca que faz sentido.

**Organize seus estudos, encontre o que o professor ensinou e revise seu código — tudo conectado ao Obsidian.**

[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-2B7550?style=flat-square&logo=windows&logoColor=white)](https://github.com/Marco-Oliver/TRAMA/releases/latest)
[![Última versão](https://img.shields.io/github/v/release/Marco-Oliver/TRAMA?style=flat-square&color=2B7550&label=Vers%C3%A3o)](https://github.com/Marco-Oliver/TRAMA/releases/latest)
[![Testes](https://img.shields.io/github/actions/workflow/status/Marco-Oliver/TRAMA/release.yml?style=flat-square&label=Publica%C3%A7%C3%A3o)](https://github.com/Marco-Oliver/TRAMA/actions/workflows/release.yml)
[![Licença](https://img.shields.io/badge/Dados-no%20seu%20Obsidian-336D55?style=flat-square)](#-segurança-e-privacidade)

### [⬇️ **BAIXAR TRAMA PARA WINDOWS**](https://github.com/Marco-Oliver/TRAMA/releases/latest/download/TRAMA_Setup.exe)

**Instalador Windows · Não exige Python · Sem configurar terminal**

[Como instalar](#-instalação-em-4-passos) · [Ver as telas](#-conheça-o-trama) · [IA Professor](#-ia-professor-experimental) · [Como atualizar](#-atualizar-sem-complicação)

</div>

---

## 🖥️ Conheça o TRAMA

<figure>
<img src="docs/screenshots/mapa-evolucao.png" alt="Tela de demonstração do TRAMA com aulas, notas e mapa de relações" width="100%"/>
<figcaption><sub>Interface do aplicativo com conteúdo de demonstração utilizado nos testes.</sub></figcaption>
</figure>

<details>
<summary><strong>📚 Ver a Biblioteca do Obsidian</strong></summary>

<img src="docs/screenshots/biblioteca.png" alt="Tela da biblioteca local de notas Markdown no TRAMA" width="100%" />

</details>

O TRAMA não substitui o Obsidian: ele **organiza, conecta e facilita o estudo** sobre os mesmos arquivos Markdown que você já pode abrir e editar normalmente.

## ✨ Tudo num só lugar

| Recurso | O que você consegue fazer |
| :-- | :-- |
| 📚 **Aulas** | Reunir gravações V01/V02/V03, transcrições, arquivos e links na mesma aula. |
| 🧠 **Conhecimento** | Ler resumos por aula e módulo, consultar conceitos e acompanhar a evolução dos estudos. |
| 💻 **Projetos** | Relacionar explicações com arquivos, exemplos de código e linhas dos repositórios Git. |
| 🔗 **Biblioteca** | Navegar pelas notas e conexões diretamente no TRAMA ou abrir o Obsidian. |
| 🔎 **Busca e filtros** | Encontrar aulas e notas; filtrar itens recentes ou favoritos. |
| 🛟 **Dúvidas** | Guardar hipóteses e localizar possíveis evidências em aulas futuras, sem inventar respostas. |
| 💾 **Backup** | Criar um ZIP local verificado e restaurar em outra pasta sem sobrescrever a biblioteca atual. |
| 🎓 **IA Professor** | Conversar sobre as aulas, receber desafios e revisar código com referências ao material encontrado. |

### Como o conteúdo vira conhecimento

```text
     Transcrições · prints · documentos · links · Git
                            │
                     Importar e organizar
                            │
                 Análise opcional por IA
                            │
           Conferência de trechos e relações
                            │
                        OBSIDIAN
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
           Aulas         Conceitos        Projetos
            └───────────────┼───────────────┘
                            ▼
                     Revisão e estudo
```

**Vídeos permanecem por link:** o TRAMA não baixa automaticamente os arquivos do Classroom ou do Meet. Você seleciona as fontes; o sistema as organiza e preserva suas referências.

## 🎓 IA Professor (experimental)

A IA Professor lê **trechos selecionados das notas do cofre** e solicita uma resposta ao provedor externo que você configurar. O Python faz a busca e prepara o contexto; **não é um modelo treinado pelo TRAMA**.

- **Explicar / revisar:** faça uma pergunta e confira as notas utilizadas.
- **Criar desafios:** pratique somente assuntos encontrados na sua biblioteca.
- **Corrigir meu código:** cole um trecho e peça pistas sobre erros, sem executar o programa.

As respostas mostram referências clicáveis. Se não houver material correspondente, o Professor informa que falta contexto em vez de escolher um assunto não relacionado.

**Privacidade:** o chat é temporário, o Professor não escreve no Obsidian e o envio de cada pergunta exige autorização. Algumas informações podem ser enviadas à API externa; remova dados privados antes de enviar.

**Qualidade:** as citações confirmam *quais notas foram consultadas*, mas não comprovam que o modelo interpretou tudo corretamente. Uma conversa com modelo simulado não substitui avaliação com modelo real.

## 📦 Instalação em 4 passos

<details open>
<summary><strong>Quero só usar o aplicativo (não sou desenvolvedor)</strong></summary>

1. Clique em **[Baixar TRAMA para Windows](https://github.com/Marco-Oliver/TRAMA/releases/latest/download/TRAMA_Setup.exe)**.
2. Abra o arquivo **`TRAMA_Setup.exe`**, siga as telas do instalador e, ao terminar, abra **TRAMA** pelo menu Iniciar.
3. Na aba **Ajustes**, clique em **Selecionar pasta do Obsidian**. Pode escolher um cofre existente ou um cofre preparado para seus estudos.
4. Clique em **Importar e organizar**, adicione suas transcrições, prints e links, confira a fila e selecione **Processar tudo**.

**Não precisa:** clonar GitHub, instalar Python, rodar comandos, configurar Docker ou baixar um ZIP com código-fonte.

</details>

> **Aviso do Windows:** o instalador ainda não tem assinatura digital. O Windows pode alertar sobre aplicativos de editor não reconhecido. Confira sempre que o download veio da [release oficial](https://github.com/Marco-Oliver/TRAMA/releases/latest) e valide o SHA-256 disponibilizado no mesmo release. Não execute um arquivo cuja origem você não consiga verificar.

### 🔄 Atualizar sem complicação

Dentro do TRAMA:

1. Entre em **Ajustes → Verificar atualizações**.
2. Se houver versão nova, clique em **Baixar e instalar nova versão**.
3. O TRAMA baixa o instalador do canal oficial e confere seu **SHA-256**. Você confirma antes de executar a instalação.
4. Reabra o TRAMA e selecione seu cofre, se necessário.

O instalador de uma versão nova **não substitui nem desinstala seu Obsidian**. Recomendamos criar um backup antes de atualizar: **Ajustes → Criar backup local (.zip)**. Para recuperação, escolha **Restaurar backup em nova pasta**.

Caso o verificador do aplicativo esteja indisponível, baixe manualmente pela [página de releases](https://github.com/Marco-Oliver/TRAMA/releases/latest).

**Importante:** a atualização não é automática nem silenciosa; depende de você. O teste automatizado de upgrade valida cofres de demonstração e não substitui a conferência da sua biblioteca real.

## 🔐 Segurança e privacidade

| Dados | Tratamento |
| :-- | :-- |
| Notas e transcrições | Arquivos locais no cofre escolhido. |
| Banco de dados | SQLite local para catalogar fontes, resumos e histórico. |
| Chaves de IA | Configuradas localmente; no Windows, protegidas com DPAPI. |
| IA externa | Só recebe contexto quando você autoriza; valem as políticas do provedor. |
| Código do estudante | Não é executado pela IA Professor. |
| Backup | ZIP com verificação de arquivos, **não criptografado**. Guarde com cuidado. |

O TRAMA aceita provedores opcionais como Gemini, Groq e OpenRouter, sujeitos aos termos e cotas de cada serviço. **ChatGPT Plus e Claude Pro não equivalem a chaves de API gratuitas**; o TRAMA não consegue verificar ou bloquear faturamento de terceiros.

O sistema tenta ocultar formatos comuns de credenciais, mas nenhuma filtragem garante detectar todos os dados sensíveis. Evite importar materiais com senhas, segredos ou informações pessoais desnecessárias.

Leia também [SECURITY.md](SECURITY.md) e a [documentação completa do produto](PLANEJAMENTO_TRAMA.md).

## 🛠️ Para quem quer desenvolver

<details>
<summary><strong>Arquitetura, testes e execução a partir do código-fonte</strong></summary>

| Parte | Tecnologia |
| :-- | :-- |
| Interface desktop | HTML, CSS, JavaScript e pywebview/WebView2 |
| Automação | Python 3.11+, Git e SQLite |
| Conhecimento | Markdown e links internos do Obsidian |
| IA (opcional) | API externa configurada pelo usuário |
| Instalador | PyInstaller e Inno Setup |
| Validação | unittest, cenários adversariais, GitHub Actions e testes automatizados de interface |

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -q
python qa_adversarial.py
python main.py gui
```

A auditoria completa inclui **personagens fictícios**, testes de segurança, fluxo de telas em navegador automatizado e compilação/instalação do executável Windows. Testes simulados não são avaliação de qualidade de um Gemini real.

Veja os workflows na pasta [`.github/workflows`](.github/workflows).

</details>

---

<div align="center">

**TRAMA · Seu conhecimento, organizado.**

<sub>Feito para estudar melhor, mantendo seu material no Obsidian e seu controle sobre dados e atualizações.</sub>

</div>


### Correções de manutenção — 2.0.1

A candidata 2.0.1 reforça a privacidade da IA Professor, impede destinos não autorizados para as APIs, endurece a leitura de documentos e corrige falhas de importação e navegação. O instalador mantém a mesma identidade da versão 2.0.0 para permitir atualização no Windows sem substituir o cofre. Veja a versão publicada no link **Última versão** do topo.
