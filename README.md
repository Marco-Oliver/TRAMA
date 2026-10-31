<div align="center">

<img src="assets/trama-logo-64.png" width="66" alt="Logotipo do TRAMA" />

# TRAMA

### Seu conhecimento, organizado. Seu aprendizado, conectado.

**Um aplicativo Windows para transformar aulas, transcrições e código em uma memória pessoal consultável.**

[![Windows](https://img.shields.io/badge/Windows-10%2F11-2D6A59?logo=windows&logoColor=white)](https://github.com/Marco-Oliver/TRAMA/releases)
[![Python](https://img.shields.io/badge/Python-3.11%2B-2D6A59?logo=python&logoColor=white)](https://www.python.org/)
[![GitHub Actions](https://github.com/Marco-Oliver/TRAMA/actions/workflows/release.yml/badge.svg)](https://github.com/Marco-Oliver/TRAMA/actions/workflows/release.yml)

[**Instalação**](#-instalação) · [**Como funciona**](#-como-funciona) · [**Privacidade**](#-privacidade-e-segurança) · [**Desenvolvimento**](#-desenvolvimento)

</div>

---

## 🖥️ Conheça o aplicativo

<p align="center">
  <img src="docs/screenshots/mapa-evolucao.png" width="100%" alt="Captura real da interface do TRAMA mostrando a biblioteca, aulas e mapa de evolução de conceitos" />
</p>

<sub>Captura da interface renderizada durante testes, com **conteúdo de demonstração**. Não representa uma análise completa de aulas pessoais reais.</sub>

<details>
<summary><b>Ver outra tela: Biblioteca do Obsidian</b></summary>
<br />
<img src="docs/screenshots/biblioteca.png" alt="Captura da Biblioteca do Obsidian dentro do TRAMA" width="100%" />
</details>

## ✨ O que o TRAMA faz

| 🗂️ Minhas Aulas | 🧠 Meu Conhecimento | 💻 Meus Projetos |
| :--- | :--- | :--- |
| Agrupa V01, V02, V03 de uma aula; preserva transcrições, horários, prints e links. | Consolida conceitos e contexto do curso sem perder suas fontes. | Lê código e documentação Git; associa conceitos a arquivos, linhas e commits. |

A proposta é sair de **arquivos isolados** para explicações como:

> “Este conceito apareceu na Aula X, voltou na Aula Y e foi utilizado neste trecho do Projeto Z.”

Essas relações devem apontar **evidências verificáveis**. Encontrar código em um repositório compartilhado não comprova automaticamente quem o escreveu ou o nível de domínio de alguém.

### Do material à biblioteca

```text
Transcrições + prints + links + repositórios GitHub
                       │
                Importar em lote
                       │
          Interpretar, validar e relacionar
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
     Minhas Aulas  Meu Conhecimento  Meus Projetos
         └─────────────┼─────────────┘
                       ▼
                 Obsidian Vault
             (arquivos Markdown locais)
```

- **Sem copiar os vídeos:** as gravações ficam por link, enquanto transcrições e notas podem permanecer no cofre.
- **Fila de importação:** adicione arquivos de várias vezes, cole prints com `Ctrl + V` e só depois clique em **Processar tudo**.
- **Pessoas e contexto:** aulas de apresentação, metodologia e atividades também entram na biblioteca, mesmo sem código.
- **Evolução explicável:** diferencia menção, retomada, aplicação, hipótese e evidência confirmada.
- **Visual de desktop clássico:** biblioteca, busca, notas e painéis relacionados na mesma tela.

## 📦 Instalação

> **Estado da distribuição:** o instalador Windows só estará disponível no link abaixo quando o fluxo de compilação e a primeira publicação do GitHub Actions terminarem com sucesso. Não confunda o código-fonte com um aplicativo instalável.

**[⬇️ Baixar TRAMA para Windows (última versão publicada)](https://github.com/Marco-Oliver/TRAMA/releases/latest/download/TRAMA_Setup.exe)**

1. Baixe `TRAMA_Setup.exe` pela página de [Releases](https://github.com/Marco-Oliver/TRAMA/releases).
2. Execute o instalador e abra **TRAMA** pelo menu Iniciar.
3. Em **Ajustes**, selecione seu cofre local do Obsidian e, opcionalmente, configure uma chave de IA de uma conta gratuita.
4. Adicione materiais à fila e clique em **Processar tudo**.

**Não é necessário instalar Python** para utilizar o aplicativo compilado. Sem assinatura digital de código, o Windows pode apresentar um aviso SmartScreen; confira a origem e os arquivos de verificação do release antes de executá-lo.

### Atualizações

O aplicativo possui um mecanismo para consultar releases e baixar instaladores com verificação de hash SHA-256. **A atualização não é silenciosa:** você confirma a instalação. O fluxo completo de upgrade ainda precisa ser validado entre duas versões públicas sucessivas.

## 🔐 Privacidade e segurança

- **Seus dados ficam na sua máquina:** cofre Obsidian, SQLite, transcrições, vídeos por link e preferências locais **não são armazenados neste repositório**.
- **Chaves de API são configuradas localmente**, com proteção DPAPI no Windows; nunca devem ser commitadas nem incluídas em relatórios.
- O TRAMA não ativa faturamento: a utilização de Gemini/Groq/OpenRouter depende da **conta e dos limites configurados por você**. Serviços externos aplicam as próprias políticas de privacidade.
- A análise de conteúdo por IA exige sua autorização antes de enviar materiais ao provedor configurado.
- Notas editadas manualmente não devem ser sobrescritas silenciosamente. Guarde backups do cofre.

Leia [SECURITY.md](SECURITY.md).

## 🛠️ Desenvolvimento

| Camada | Tecnologias |
| --- | --- |
| Interface | HTML, CSS, JavaScript — tema clássico |
| Desktop Windows | Python + pywebview / WebView2 |
| Backend e processamento | Python 3.11+, Git, SQLite |
| Base de conhecimento | Markdown em cofre Obsidian local |
| IA opcional | APIs gratuitas configuradas por usuário |
| Empacotamento | PyInstaller + Inno Setup 6 |
| CI/CD | GitHub Actions em runner Windows |

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python qa_adversarial.py
python main.py gui
```

### Testes do aplicativo instalável

O fluxo em [`.github/workflows/release.yml`](.github/workflows/release.yml) executa:

1. Auditoria de arquivos e possíveis credenciais.
2. Testes de regressão e casos adversariais.
3. Compilação do **TRAMA.exe** com todos os recursos locais.
4. Teste do executável compilado com `--self-test`.
5. Geração do **TRAMA_Setup.exe**, instalação silenciosa em ambiente Windows de CI, novo teste do executável instalado e desinstalação.
6. Verificação SHA-256 antes de disponibilizar o release.

**Limite dos testes:** essa automação não substitui a validação visual da janela, do WebView2 em diferentes PCs, nem a avaliação factual de respostas reais do Gemini com suas aulas e projetos.

---

<div align="center">
<sub>TRAMA é uma ferramenta pessoal de aprendizagem em evolução. O Obsidian permanece independente — o seu conhecimento não fica preso ao aplicativo.</sub>
</div>
