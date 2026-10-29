# Correções da revisão do PR 45

## Mudanças

- O proxy emite apenas `text/event-stream` ou `application/json`.
- O baseline executa o teste visível e o oráculo em bubblewrap separado, sem rede. O workspace é gravável; scripts e oráculo são somente leitura. HOME e temporários são isolados. Sem bubblewrap, o resultado é infraestrutura. O T2 usa o mesmo avaliador.
- No T3b, Landlock concede ao teste visível apenas cópias dos scripts necessários. O oráculo tem sua própria cópia privada. O workspace e um diretório temporário dedicado são graváveis; o journal fica protegido.
- Erros de importação e sintaxe provenientes do workspace durante a coleta são falhas do modelo. Indisponibilidade do avaliador continua infraestrutura. Uma rejeição visível comprovada não é apagada por falha posterior do oráculo.
- O orçamento de parede do worker tem motivo próprio. Um timeout não sobrescreve falha de servidor já identificada. O follow-up recebe o saldo de reparos da primeira fase.
- O agregado v3 contém resumo, manifesto e 36 unidades. Os rótulos de VRAM e as contagens documentais foram corrigidos.

## Revalidação sem GPU

Os dados brutos foram apenas lidos. Os workspaces foram copiados para diretórios temporários antes da avaliação. Não houve inferência. A evidência por avaliação está em [pr45-regrade.jsonl](../../../../results/3070-benchmark/pr45-regrade.jsonl).

Foram reavaliados **425 workspaces**, em **453 avaliações privadas**: 170 tentativas da etapa 4, 103 da etapa 5, 36 objetivos privados aplicáveis dos 8 workspaces do T2, 108 unidades T3b v2 e 36 unidades T3b v3. Nenhuma avaliação nova retornou infraestrutura. As notas privadas disponíveis da etapa 4 (170), etapa 5 (103) e T2 (36) coincidiram com as publicadas. No T2, fases sem oráculo privado e objetivos não iniciados não foram comparados.

No T3b, 9 de 102 notas comparáveis na v2 e 5 de 35 na v3 mudaram de falha para aprovação. As outras 7 unidades não tinham nota privada comparável. As 14 divergências têm erro histórico do Node/OpenSSL no oráculo. Todas as entregas terminaram rejeitadas; o regrade não reconstrói a interação que teria ocorrido com o verificador saudável.

O oráculo histórico registrou erro de infraestrutura JavaScript em 18 unidades v2 e 6 v3. Destas, quatro eram `P-W16/js_sign`: três repetições v2 e uma v3. Foram rejeitadas por ausência de novo diagnóstico visível após erro ambiental, sem falha de modelo comprovada. Excluindo essa tarefa, a taxa por tarefas do P-W16 muda de **2/12 para 2/11**, tanto na v2 quanto na v3. README e RESULTS apresentam essa correção ao lado das contagens históricas. As demais 20 unidades com esse erro também registram rejeição de edição ou saída. Ainda assim, o erro ambiental pode ter influenciado reparos; não se pode reconstruir o resultado contrafactual.

Os últimos diagnósticos visíveis preservados continham erro OpenSSL em 12 unidades v2 e 6 v3. Em 14 delas, o único evento de verificação foi seguido por nova geração: o diagnóstico foi devolvido ao modelo. Nas outras quatro, houve mais de uma verificação e o journal não preserva o texto intermediário. Não é possível provar qual texto foi devolvido. A comparação de qualidade do T3b permanece inconclusiva.

### Outros pontos da revisão

- **Importação e coleta:** zero unidades classificadas como infraestrutura com erro de importação ou sintaxe do candidato nos artefatos pesquisados. A busca cobriu os logs e journals preservados; não prova eventos que não foram registrados.
- **Vazamento de oráculo ou patch:** zero coincidências de caminhos privados ou trechos exatos com pelo menos 30 caracteres nos diagnósticos visíveis preservados: 199 registros da etapa 4, 119 da etapa 5, 44 do T2, 48 da v2 e 18 da v3. Fragmentos menores ou parafraseados não foram descartados. Diagnósticos intermediários do T3b não foram todos preservados.
- **Orçamento de parede:** zero registros de `wall_budget` classificados como infraestrutura nos journals e saídas T3b v2/v3 pesquisados.
- **Código 124 e servidor:** 11 tentativas das etapas 4 e 5 terminaram em timeout e registraram `ConnectionResetError` no último pedido. A aplicação literal da prioridade nova daria infraestrutura a quatro resultados finais da etapa 4, cinco finais da etapa 5 e duas tentativas intermediárias de cascata. Não há horário por pedido que permita determinar se o reset precedeu o timeout ou foi consequência do cancelamento. Não foram encontrados HTTP 500, `server_exited` ou conexão recusada nesses logs. As tabelas preservam as classificações históricas, com essa ressalva.

## Verificação do código

Os testes cobrem mounts, ausência de bubblewrap, isolamento real, erros de importação e sintaxe, falha do avaliador, proteção do journal, orçamento de reparos e prioridade de falhas. O Ruff passou nos arquivos Python alterados. O projeto não define comando de typecheck; nenhum typechecker estava disponível no PATH. A suíte completa passou: **326 testes e 47 subtestes**, com o Python solicitado, `PYTHONDONTWRITEBYTECODE=1` e `pytest -p no:cacheprovider`.

**Desvio da restrição:** a suíte inclui dois casos parametrizados que iniciam o OpenCode real com `debug config`. Eles foram executados por engano durante a suíte, apesar da proibição de iniciar o OpenCode real. Não houve execução de servidor real, inferência ou uso de GPU nesses casos. Uma nova execução, excluindo esses dois casos, passou com **324 testes e 47 subtestes**, com 2 casos desmarcados.
