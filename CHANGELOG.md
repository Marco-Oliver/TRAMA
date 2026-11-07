# Histórico de versões do TRAMA

## [2.2.2] — 2026-11-07

### Corrigido — Aula 01 e organização de pessoas
- **Apresentadores em gravações:** o nome no título é apenas uma pista. Se a transcrição contém uma autoapresentação com primeiro nome compatível, a nota apresenta o possível palestrante explicitando que o sobrenome ainda precisa de conferência; nome completo confirmado no TXT ou no contexto mantém evidência mais forte. Um título isolado não cria pessoas.
- **Grafias similares de nomes completos:** divergências pequenas como `Tiago Santini` / `Thiago Santini`, com o mesmo sobrenome, deixam de gerar avisos redundantes como `Thiago Santini (possivelmente Santini)`. Nenhum nome é corrigido no TXT original.
- **Perfis de pessoas e siglas:** siglas e nomes com formato institucional (ex.: `FCVest`) passam à seção de termos, siglas e instituições para conferir; não viram páginas de pessoas. Preserva a hipótese legítima `Rash (possivelmente Rech)` sem criar identidade nova.
- **Classroom colado:** linhas de cabeçalho de data abreviada, como `2 de mar.`, são ignoradas sem avisos ou mudança da data `Agenda: dd/mm/aaaa`.

### Compatibilidade e segurança
- Correções locais nas notas; não consomem chamadas extras de IA e não reprocessam automaticamente aulas já analisadas. O texto original, contextos do Classroom, preferências e chaves locais são preservados.
- Testes sintéticos cobrem nomes completos/abreviados, ausência de evidências, siglas, importação de datas e preservação do cache.
- Instalação e atualização com `TRAMA_Setup.exe` e `SHA256SUMS.txt`. Smokes Windows de instalação/reinstalação e upgrade das versões oficiais 2.1.0, 2.2.0 e 2.2.1 usam somente dados fictícios.

## [2.2.1] — 2026-11-06

### Corrigido — Aula 01
- **Apresentador ausente:** usar o título da gravação e a autoria do Classroom como pistas, incluindo uma pessoa somente quando o nome completo também consta na transcrição ou no contexto disponível.
- **Nomes distorcidos:** evitar criar perfis para variantes fonéticas como `Rash`; registrar `Rash (possivelmente Rech)` em **Nomes e apelidos para conferir**.
- **Aulas não técnicas:** conceitos de apresentações, organização e atividades ficam na nota da própria aula, sem gerar páginas em `01-Meu-Conhecimento` nem marcos no mapa da evolução.
- **Avisos fora de contexto:** exibir hipóteses vinculadas a SHA apenas quando existe versão congelada; não exigir congelamento do GitHub se a aula não possui repositório associado.
- **Post do Classroom no lote:** aceitar conteúdo colado como contexto local (título, autor, agenda, conteúdo, atividades, links e gravações), separar múltiplos posts e tratar o texto como dado não confiável, sem utilizar IA para interpretar a colagem.

### Corrigido — auditoria da PR #8
- **Posts após links:** um contexto já criado somente por URLs não impede salvar o post colado da mesma aula. Fontes permanecem separadas; o mesmo post alterado e arquivos com edição manual não são sobrescritos silenciosamente.
- **Cache e cota da IA:** processamento geral e lotes preservam análises antigas válidas, incluindo aulas com nomes curtos; revisão de regras só invalida a aula solicitada explicitamente (`lesson_filter` ou `force=True`). Importar contexto não reprocessa automaticamente aulas anteriores.

### Instalação e atualização
- Mantidos o AppId, a pasta de instalação e os dados locais da versão 2.2.0.
- Release com `TRAMA_Setup.exe` e `SHA256SUMS.txt`, mediante testes sintéticos de instalação, reinstalação e upgrade no Windows.
- Reprocessar uma aula antiga para incorporar as novas regras requer ação explícita; recomenda-se backup local antes de reprocessar.

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
