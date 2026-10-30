# Corpus v2 — desenho

O corpus tem 36 tarefas: 10 python_fix, 5 javascript_fix, 6 continuation, 5 mcp, 5 tool_recovery e 5 authored_tests. As 12 originais permanecem intactas. A tabela cobre as 24 novas. As linhas do bug contam linhas originais alteradas; `1→2` substitui uma linha por duas. Em authored_tests não há patch de bug: o modelo escreve uma suíte, que o oráculo executa na referência e em dois mutantes distintos.

| ID | Classe | Área | Linhas do bug | Causa → sintoma | Visível | Só oráculo |
|---|---|---|---:|---|---|---|
| py_route | python_fix | filtros de rota | 1 | conversão do filtro → parâmetro da rota | inteiro positivo | negativo, zero e entrada inválida |
| py_template | python_fix | precedência de variáveis | 1 | render → resultado do template | keyword sobre dicionário | múltiplos dicionários e escape/raw |
| py_cookie | python_fix | cookies assinados | 1 | leitura do cookie → resultado por nome | nome diferente | assinatura, segredo errado e ausente |
| py_config | python_fix | ConfigDict | 1 | carga de namespace → chaves criadas | chave aninhada simples | prefixo e múltiplos ramos |
| py_multi | python_fix | MultiDict | 1 | busca indexada → valor retornado | primeiro valor | índice ausente, conversão e padrão |
| py_headers | python_fix | HeaderDict | 1 | normalização de busca → cabeçalho retornado | nome minúsculo | caixa mista, índice e padrão |
| py_auth | python_fix | Basic auth | 1 | separação de credenciais → senha | senha com dois pontos | senha vazia, entrada inválida e esquema |
| py_urlbuild | python_fix | construção de URL | 1 | montagem → URL e query | valor e espaço | conversão, parâmetros e rota posicional |
| js_units | javascript_fix | unidades e formatação | 4 | constantes e limites → API ms | ano | semanas, decimais e limites longo/curto |
| js_decimal | javascript_fix | parsing decimal | 2 | parser → API ms | decimal positivo | negativo, espaços e unidade implícita |
| js_invalid | javascript_fix | entradas inválidas | 2 | despacho → retorno/erro | infinito e espaços | outros tipos, NaN e entradas válidas |
| cont_forms | continuation | FormsDict e codificação | 2 | _fix → getunicode/decode | caractere acentuado e decode | múltiplos valores, fallback e latin1 |
| cont_redirect | continuation | redirecionamento | 2 | status e URL → resposta | relativo no HTTP/1.1 | HTTP/1.0, absoluto e status explícito |
| cont_plugins | continuation | precedência de plugins | 2 | all_plugins → callback da rota | precedência e exclusão por tipo | exclusão por nome, global e todos |
| cont_cache | continuation | cache HTTP | 2 | comparações → status do arquivo | data igual e ETag distinta | data anterior/posterior, inválida e ETag exata |
| mcp_render | mcp | interpolação HTML | 2 | process_inline → template | escape padrão | interpolação raw e escape |
| mcp_import | mcp | carregamento de objetos | 2 | load → objeto ou expressão | literal com maiúsculas | classe com nome em caixa mista |
| mcp_groups | mcp | grupos de expressão regular | 2 | _re_flatten → padrão convertido | grupo comum | grupo nomeado e parênteses escapados |
| recover_hvalue | tool_recovery | valor de cabeçalho | 2 | normalização → valor retornado | espaços preservados | controles LF, CR e NUL |
| recover_httpdate | tool_recovery | formatação de data HTTP | 2 | formatação → valor do cabeçalho | epoch em GMT | dia seguinte e string preservada |
| recover_cookieformat | tool_recovery | detecção de formato de cookie | 1→2 | detecção → reconhecimento | prefixo e separador | espaço inicial e ausência de marcador |
| tests_escape | authored_tests | escape HTML | — | suíte escrita → regressões de escape | suíte passa na referência | mutantes de ampersand e aspas |
| tests_list | authored_tests | normalização de listas | — | suíte escrita → conversão de valores | suíte passa na referência | mutantes de coleção e escalar falso |
| tests_compare | authored_tests | comparação de strings | — | suíte escrita → igualdade | suíte passa na referência | mutantes de conteúdo e comprimento |

Os stubs são determinísticos. Fornecem evidência externa local. Não medem transporte MCP real. Os casos de duas ou mais linhas e as duas fases aumentam a necessidade de investigar. A dificuldade média é uma hipótese até a calibração. As oito python_fix do lote 1 alteram uma linha na mesma função do sintoma; podem saturar.

Em `py_range`, o objetivo menciona extremidades explícitas, mas não descreve o caso de sufixo que o oráculo também testa. Essa lacuna é uma hipótese para a dificuldade observada, não uma causa comprovada.

## Manifesto e histórico

Os prefixos e o manifesto foram regenerados para o corpus ampliado. Os resultados históricos continuam válidos para o corpus de 12, com seus hashes e prefixos originais; não devem ser misturados com novas execuções. `benchmark/configs/qwen-4b-prefix-cache.json` lista os 12 IDs antigos. O T3b agora seleciona pelos IDs do config e rejeita IDs ausentes, mas uma retomada de campanha com manifesto antigo deve manter seu snapshot original. As campanhas T3b de prefixo e os runners OpenCode baseline, combined, stage5, stage5-rep3 e long-tasks registram ou conferem hashes do corpus no manifesto de saída. Seus configs antigos e resultados existentes não são convertidos para v2; execução nova exige protocolo e diretório novos.

## Próximo passo

Calibrar na GPU, sem escalada: controle Q4_K_M, KV q4_0, 64K, cache e temperatura zero; comparar a configuração recomendada com MTP n-max 2 e checkpoints, thinking desligado. Fazer duas repetições nas 24 tarefas novas. Manter as tarefas com acerto aproximadamente entre 20% e 80%. Não há calibração executada nesta mudança.
