# TRAMA — Etapa 2b: relatório para auditoria do Claude

**Escopo:** integração do GitHub por aula, sem merge na `main` e sem release.  
**Base autorizada:** `b9c5fa022f9ccec5e13a7abef76647e033b5d817`  
**Branch:** `feat/github-por-aula`  
**Regra de validação:** consultar os workflows deste branch/commit em [GitHub Actions](https://github.com/Marco-Oliver/TRAMA/actions); verificar os três resultados verdes do SHA final (os links individuais são informados na entrega).

## 1. Implementações

### 1.1 Acesso somente por SHA congelado

- `Bridge._lesson_code_binding()` valida a aula, o papel, o ID e o slot, consulta `github_lesson_refs` no SQLite e compara a referência com `aulas-github.json`.
- O leitor **não resolve branches/tags** durante listagem, leitura, comparação ou diffs. Na ausência do SHA: **“congele a versão desta aula”**.
- Os métodos públicos somente leitura são `lesson_code_files`, `lesson_code_read_file`, `lesson_code_compare` (anterior × atual) e `lesson_code_diff_folders` (duas pastas no mesmo commit).
- `PublicApi` possui entradas explícitas na lista branca; não há método público que aceite diretamente um repositório arbitrário ou SHA de consulta.
- `GithubCodeReader(cache=GithubCache(vault=vault))` mantém o cache fora do Obsidian; conteúdo privado segue a política DPAPI da Etapa 2.
- Respostas grandes de diffs são limitadas antes de chegar ao WebView, com indicador de truncamento.

### 1.2 Reprocessamento e publicação

- `Bridge.process_lesson` retorna a lista de SHAs atuais congelados em `code_shas`. A rotina não recongela nem busca a ponta da branch.
- Sem vínculo congelado, `code_pending_freeze` e a mensagem de processamento orientam o usuário a congelar a versão.
- `Application.enrich_context` ignora evidências GitHub cujo commit não coincide com o SHA congelado da aula.
- `Publishing` aplica o mesmo filtro nas relações com código das páginas de aula e nas relações projeto/aula. Um índice global atualizado para a ponta da branch não deve substituir evidência de aula.
- O índice global de repositórios e as pastas Git locais são fluxos distintos; não foram convertidos em checkout automático para commits por aula.

### 1.3 Descongelar e recongelar

- `unfreeze_lesson_code(lesson, role, repository_id, slot, confirmed)` exige `confirmed is True`, remove apenas a referência SQLite selecionada e preserva JSON/notas.
- A janela GitHub oferece ações separadas para a revisão atual e a anterior.
- Teste com branch simulada: congelar SHA A, descongelar explicitamente, recongelar SHA B.

### 1.4 Consistência JSON/SQLite

- `github_lesson_state.py` identifica os locks cujo repositório, tipo de ref, valor de ref ou pasta mudaram ou foram retirados.
- A interface consulta `lesson_code_changes` antes de salvar e informa quantos SHAs serão descongelados; o backend exige `confirm_unfreeze=True` quando há locks afetados.
- Na gravação, SQLite executa os `DELETE` **antes** da substituição do JSON, dentro de transação ainda não confirmada. Erro na gravação JSON gera rollback SQLite.
- Caso um erro de commit SQLite ocorra após substituir o JSON, o módulo tenta restaurar atomicamente os bytes JSON anteriores, seguido do rollback.
- A exclusão integral do cadastro usa o mesmo procedimento; o mapeamento em lote também passa pelo serviço de persistência coordenada.
- A operação de descongelar explicitamente continua separada, sem modificar os dados do cadastro.

### 1.5 Desempenho

- `GithubCache._touch` mantém em memória o último timestamp utilizado, sem `glob`/varredura a cada **leitura**. A remoção LRU ainda varre a pasta quando ocorre escrita, para manter o limite global.
- `GithubCodeReader.diff_folders` ignora blobs idênticos e limita a 40 chamadas de leitura de arquivos por operação; marca `truncated=True` quando a comparação fica incompleta.
- `Git Trees` continua com uma consulta recursiva por instância/leitura do mesmo SHA (sem clone local).

## 2. Arquivos alterados

**Código:** `knowledge_bridge/bridge.py`, `github_lesson_state.py`, `store.py`, `pipeline.py`, `publishing.py`, `github_code.py`, `github_cache.py`.  
**Interface:** `knowledge_bridge/ui/index.html`, `knowledge_bridge/ui/lesson_code.js`.  
**CI:** `.github/workflows/v220-foundations.yml` (inclui sintaxe de `lesson_code.js`).

## 3. Testes

**Arquivos novos:**
- `tests/test_github_lesson_bridge.py`: chamadas PublicApi → Bridge → SQLite → leitor/cache → HTTP simulado; ausência de lock; escopo de pasta; reprocessamento sem avançar SHA.
- `tests/test_github_lesson_consistency.py`: mudanças de pasta/referência/remoção, confirmação extra e falhas simuladas no salvamento do JSON, remoção de cadastro e commit SQLite.
- `tests/test_github_lesson_pipeline.py`: código GitHub permitido apenas por SHA da aula; branch simulada avança; reprocessamento preserva SHA A e exige congelamento na ausência dele.

**Arquivos de testes atualizados:** `tests/test_github_lesson_stage2.py`, `tests/test_github_code_reader.py`, `tests/test_github_cache.py`, `tests/test_native_boot.py`, `tests/ui_smoke.mjs`.

**Executar nas duas plataformas:** `python -m unittest discover -s tests -q`.  
**Complementos da CI:** `qa_adversarial.py`, `tools/audit_release.py`, `compileall`, verificações Node, auditoria estática/de dependências, smoke visual e compilação/teste de instalador sem publicação.

## 4. Pontos para auditoria independente

1. Verificar que todas as operações **por aula** exigem `github_lesson_refs`, inclusive as relações geradas no processamento e na publicação. Comparar com o fluxo legado de indexação global.
2. Verificar normalização de URL de repositório e correspondência de SHA, inclusive mudança de branch sem recongelamento.
3. Avaliar transação JSON/SQLite em falhas injetadas e em queda abrupta do processo. Não há garantia de atomicidade distribuída contra perda súbita de energia entre a substituição do JSON e o commit SQLite; o código trata erros recuperáveis e restaura estado por melhor esforço.
4. Acesso privado ao GitHub e DPAPI real de máquina Windows **não foram testados com credenciais pessoais**; os testes de integração usam HTTP/DPAPI simulados. O cache privado não grava texto puro como fallback em plataformas sem DPAPI.
5. Avaliar limites de retorno de diffs, entradas de caminhos, arquivos simbólicos, respostas truncadas do GitHub e proteção contra conteúdo HTML malicioso.
6. Conferir a saída e conclusão dos workflows do **commit final**; uma CI verde não substitui o teste manual de UX no Windows.

**Sem merge na `main` e sem release desta etapa.**
