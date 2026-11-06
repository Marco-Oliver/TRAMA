# Histórico de versões do TRAMA

## [2.2.0] — 2026-11-06

### Adicionado
- Associação automática de aulas às versões congeladas dos repositórios GitHub, com SHA, arquivos, linhas e escolha manual de versão.
- Identificação de branches `v0` a `vN` e da branch padrão quando não coincide com a última `vN`; diferenças extensas calculadas por hashes das árvores Git.
- Revisão local de dúvidas de transcrição usando somente a versão congelada da aula, sem consumir novas chamadas de IA.
- Pistas técnicas com trechos de código literais, links imutáveis e indicação explícita de que não comprovam o áudio.

### Corrigido
- URL de metadados GitHub sem barra final, evitando falso erro de repositório inexistente.
- Redução de falsos positivos: consulta apenas dúvidas técnicas ou conceitos distorcidos marcados; textos explicativos fora de aspas, `using`, `namespace`, strings, URLs, comentários e nomes genéricos não geram correspondências.
- Conceitos corretos em português não recebem estados de dúvidas. `DB Contact`, quando validado como grafia distorcida pelo código congelado, gera **um único link** para `DbContext` em Conhecimentos relacionados, preservando a grafia do TXT nas observações.
- Sem trechos repetidos de evidência e sem HTML escaping de parâmetros genéricos C# em blocos de código.

### Atualização da 2.1.0
- Mesmo AppId, pasta e canal oficial do instalador 2.1.0.
- `TRAMA_Setup.exe` e `SHA256SUMS.txt` na release pública; download com SHA-256 conferido e instalação mediante confirmação do usuário.
- Teste automatizado no Windows com upgrade 2.1.0 → 2.2.0, preservando SQLite, nota manual do Obsidian, ajustes e chave DPAPI **fictícia**. Nenhuma chave real entra no repositório nem no CI.
- Recomendado realizar backup local antes de reprocessar aulas.

## [2.1.0] — 2026-11-03

- Pesquisa local em transcrições, melhorias na IA Professor, evidência extraída de materiais originais e reprocessamento individual.
- Atualização oficial a partir de 2.0.1 e verificações de persistência de dados locais.
