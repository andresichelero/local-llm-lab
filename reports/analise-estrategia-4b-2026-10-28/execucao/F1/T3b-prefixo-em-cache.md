# T3b — prefixo em cache para o worker F3

Data: 29/10/2026. Implementação e validação offline no worktree `feat/4b-worker-v2`. Nenhuma inferência, servidor ou acesso à GPU foi iniciado para esta tarefa. A campanha não foi executada; não há resultados de qualidade ou desempenho.

## Desenho

São 12 tarefas dos hosts `bottle-0.13.2` e `ms-2.1.3`, três repetições por tarefa e por braço, totalizando 108 unidades. O controle é Qwen3.5-4B Q4_K_M bartowski, KV q4_0, cache de prompt ligado, temperatura zero, seed 42 e thinking desligado. P-W16 usa ctx 16384; P-WL-cold e P-WL-warm usam ctx 65536. O modelo é chamado pelo worker F3, que aceita SEARCH/REPLACE e até um reparo. Continuação tem duas entregas condicionais e compartilha o limite de um reparo entre as duas.

- P-W16 mantém um servidor por host e envia o pacote curto.
- P-WL-cold reinicia o servidor para cada episódio. A contagem de tokens usa endpoints de template/tokenização, sem geração nem preenchimento do cache. O TTFT mede o primeiro preenchimento; a inicialização do processo fica fora do tempo do episódio.
- P-WL-warm mantém o servidor por host e faz uma geração de um token com o prefixo antes da primeira tarefa. O custo de aquecimento fica em `warmup.json`, separado dos episódios.

Todos os braços recebem o mesmo método de seleção de trechos: para cada arquivo regular listado em `relevant_files`, em ordem lexicográfica, selecionar um único trecho contíguo de até 12000 caracteres divididos pelo número de entradas relevantes. Para arquivo longo, a linha que mais compartilha palavras com o objetivo público determina o centro; empates escolhem a primeira linha. Diretórios e arquivos ausentes são ignorados. Não se lê patch de referência ou oráculo para selecionar contexto. O prefixo WL é o prefixo congelado e redigido do corpus, não o snapshot original; o trecho também fornece o código com o bug específico.

O coordenador verifica o manifesto do corpus e os hashes configurados de servidor e modelo antes de iniciar. Obtém a contagem real do template/tokenizer para todos os pacotes iniciais de cada host e, se necessário, reduz o prefixo por busca binária em limites de linha, usando o mesmo prefixo escolhido em ambos os braços WL e todas as tarefas do host. A decisão, tamanhos e hashes são gravados em `prefix-<host>.json`. A busca pressupõe contagens aproximadamente monotônicas e garante que a opção escolhida foi testada, sem prometer prefixo matematicamente máximo. Reservam-se 2048 tokens de saída e 4096 de margem para reparo e follow-up; o runner volta a contar a entrada em cada geração e rejeita entrada acima do orçamento. Um reparo ou follow-up extraordinariamente grande pode ainda ultrapassar essa margem; a janela de contexto não é garantia de que esse segundo pedido caiba.

O builder F3 só aceita o arquivo congelado integral como `prefix`; o adaptador valida o corpus pelo manifesto, seleciona o trecho inicial desse arquivo e atribui ao pacote o hash do trecho efetivamente usado. O runner confere esse hash antes de gerar. O `--dry-run` prepara workspaces temporários com os patches de bug e estima texto por caracteres/3,5, incluindo uma estimativa de prefixo reduzido; essa estimativa não substitui o tokenizer real e não contabiliza exatamente o template nem reparos.

## Verificação e resultados

A verificação visível decide se há reparo. O verificador privado é chamado apenas para nota final, depois de encerradas as gerações; se a entrega final foi rejeitada, a nota privada ainda é medida sem retorno ao modelo. Em continuação, o follow-up só é liberado após o aceite visível da primeira fase. O supervisor compõe `WorkerRunner`, `worker_contract`, `practical_worker_guard` e os helpers do baseline de preparação, servidor, recursos, classificação e grader. Testes e grader rodam em subprocesso com Landlock/seccomp do guard; falha de isolamento é infraestrutura. O grader do baseline precisa ler o oráculo dentro do mesmo processo em que importa o candidato: essa restrição não prova proteção do arquivo do oráculo contra código candidato malicioso durante a correção. A nota deve ser interpretada sob essa limitação, como no baseline; a saída privada não é inserida no prompt.

Cada `result.json` registra estados e fases, nota visível e privada, categoria de `opencode_baseline.classify`, motivo, TTFT da primeira geração, `prompt_n`, `cache_n`, fração `cache_n/(prompt_n+cache_n)`, tokens gerados, mediana de decode, tempo total, pico de VRAM amostrado, reparos e eventos de requisição. Métricas ausentes no servidor ficam `null`; o TTFT é até o primeiro conteúdo recebido, e não uma medição direta no GPU. O tempo total inclui verificações, mas exclui preparo do workspace e inicialização do servidor. Pico é amostrado, não uma medição contínua.

`summary.json` agrega episódios válidos por braço com sucesso e IC95 Wilson, medianas das métricas e contagem de infraestrutura. O pareamento por tarefa/repetição registra acertos concordantes e discordantes e tempos dos dois braços. Episódios de infraestrutura não entram no denominador nem no pareamento. Wilson é descritivo; repetições da mesma tarefa não são observações independentes. Ao detectar infraestrutura, o driver preserva os resultados e para; não há retomada automática. O diretório de saída precisa ainda não existir. Não há comparação inferencial nem correção para múltiplas comparações.

## Execução futura

A execução real usa GPU e precisa ocorrer apenas depois de encerrada a campanha atual e mediante autorização específica para inferência. O driver recusa executar se `pgrep -x llama-server` detectar outro processo ou se a inspeção falhar. A verificação não é um bloqueio global contra outra aplicação que inicie servidor depois da checagem.

```sh
cd /mnt/d/Usuario/Downloads/LLM/.worktrees/4b-worker-v2
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.prefix_cache_campaign --dry-run
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.prefix_cache_campaign
```

Saída futura: `/home/foxtrot/local-llm-benchmark/results/qwen-4b-prefix-cache-v1`. O segundo comando não foi executado. A implementação do cliente de streaming e os endpoints de tokenização foram avaliados com fakes e leitura do código local do servidor, sem validação com servidor real; isso permanece uma aceitação pendente antes de interpretar dados.

## Verificação offline desta implementação

O dry-run listou 108 unidades com estimativas numéricas de pacote e prefixo. Testes com servidor/modelo falsos verificam seleção de trechos, redução, ciclo frio/quente, recusa, classificação, métricas de streaming, resumo, reparo e continuação; um teste adicional executou o verificador visível sob guard no WSL. O detector real recusou porque havia `llama-server` ativo. A comparação do manifesto congelado encontrou 320 arquivos correspondentes. Os testes selecionados do worker e os novos passaram; Ruff passou nos arquivos novos. Nenhum typecheck está configurado ou instalado no ambiente observado. Não foi executada a suíte inteira.

Commit do driver/config/testes: `a9a6dc0`. Verificação final: 94 testes selecionados passaram; após o último ajuste de tratamento de erro, os 13 testes T3b passaram novamente e o Ruff ficou limpo.

## Correções do orquestrador (29/10, 10h30)

- **O Landlock não protege nem libera caminhos em `/mnt/d` (drvfs/9p).** Com o guard ativo, até `corpus/support` e `pytest.ini` deram permissão negada. Por isso a 1ª execução abortou: o avaliador falhou e o reparo recebeu o erro de permissão, gerando prosa (`malformed_output`). A campanha passa a rodar de um snapshot no ext4 (`/home/foxtrot/local-llm-benchmark/src/4b-worker-v2-31a1d4b`, commit `31a1d4b`), onde o probe confirma que as regras funcionam.
- **`pytest.ini` do repositório liberado** só para leitura no sandbox do verificador: o pytest o procura subindo a partir do caminho do oráculo.
- **Quebra de linha final restaurada** depois do último marcador `>>>>>>> REPLACE`: o servidor a remove no fim da geração, e a gramática exige cada marcador numa linha terminada por LF.
- **Saída em `qwen-4b-prefix-cache-v2`.** A tentativa abortada a partir de `/mnt/d` foi arquivada como `-v2-drvfs-aborted`.
- **No ext4, mais dois bloqueios (commit `c05d697`, 13h25).**
  - O pytest abre `/dev/null` para escrita, porque é o arquivo de log padrão. Agora `/dev/null` tem permissão de escrita.
  - O pytest também lista cada diretório desde a raiz do repositório, definida pelo `pytest.ini`, até o oráculo. O sandbox ganhou `listable_paths`, que libera só a listagem de diretórios (nomes), sem leitura de conteúdo.
  - A tentativa abortada foi arquivada como `-v2-ext4-aborted-devnull`.

## Resultados da campanha (29/10, 13h28–13h58)

A campanha rodou a partir do snapshot ext4, commit `c05d697`, e gravou os resultados em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-prefix-cache-v2`.

- 108 unidades, **0 falhas de infraestrutura**.
- O prefixo usado foi o `bottle-0.13.2` inteiro (179.962 bytes, cerca de 46 mil tokens), sem corte.

**Ressalva:** com temperatura 0, as três repetições de cada tarefa saíram idênticas. A amostra efetiva é de **12 tarefas por braço**, não 36.

### Latência: o cache funciona

| Braço | TTFT (mediana) | Prompt processado | Tokens do cache | Tempo/episódio | Decode | Pico de VRAM |
|---|---:|---:|---:|---:|---:|---:|
| P-W16 (trechos de até 16K, sem prefixo) | 82 ms | 557 | 2.844 | 8,3 s | 85 tok/s | 3.871 MiB |
| P-WL-cold (prefixo de cerca de 46K, cache frio) | **16,1 s** | 46.075 | 0 | 22,1 s | 66 tok/s | 4.510 MiB |
| P-WL-warm (o mesmo prefixo, já no cache) | **158 ms** | 393 | 45.455 (99,5%) | 9,2 s | 67 tok/s | 4.508 MiB |

- Com o prefixo do repositório já no cache, o tempo até o primeiro token cai **cerca de 100 vezes** (de 16 s para 0,16 s). O episódio fica com custo parecido ao do W16, mesmo com 46 mil tokens de contexto.
- O custo do contexto longo aparece no decode: cerca de 22% mais lento (85 → 67 tok/s).
- O contexto longo usa cerca de 640 MiB a mais de VRAM.

### Qualidade: inconclusiva, por dois defeitos de desenho

| Braço | Tarefas aprovadas | Falhas de edição: `zero_occurrences` / `malformed_output` |
|---|---|---|
| P-W16 | 2/12 (`cont_path`, `recover_decode`) | 5 / 1 tarefas |
| P-WL-cold | 1/12 (`recover_decode`) | 6 / 4 tarefas |
| P-WL-warm | 2/12 (`mcp_header`, `recover_decode`) | 6 / 4 tarefas |

O acerto foi muito abaixo dos 68% do OpenCode com o mesmo modelo. Há dois motivos, e nenhum é a capacidade do modelo de resolver a tarefa:

1. **O prefixo mascarado induz o erro.** `corpus/support/prefix.py` troca as linhas tocadas por qualquer tarefa por `# task-specific line withheld`, para não vazar soluções no prefixo comum. O modelo copia esse marcador para o bloco SEARCH, que então não casa com o arquivo real:
   - em P-WL-cold, isso aconteceu em 9 das 18 unidades com `zero_occurrences`;
   - em P-WL-warm, em 12 das 18.
2. **O contrato do worker F3 não dá chance de reparo quando a edição não aplica.** Em `worker_runner.py:234-236`, uma edição rejeitada (`zero_occurrences` ou `malformed_output`) encerra o episódio na hora. O único reparo (`repairs: 1`) só acontece depois de um teste visível falhar.

   Por isso, o T3b mede a capacidade do 4B de copiar um trecho exato na primeira tentativa. O W16 também falha nisso em 5 das 12 tarefas, sem nenhum marcador envolvido. A ferramenta de edição do OpenCode é mais tolerante e devolve o erro para o modelo tentar de novo.

Diferenças curiosas entre cold e warm na mesma tarefa (`mcp_header`, `js_sign`, `cont_path`) indicam que a numérica do prefill muda com o cache: o mesmo prompt, com temperatura 0, gera saídas diferentes.

### Conclusão e próximos passos

- **Comprovado:** o prefixo de repositório em cache é viável na 3070. Com 46 mil tokens mais KV q4_0, o pico ficou em 4,5 GB, e o TTFT cai para cerca de 0,16 s.
- **Não comprovado:** se o contexto longo melhora a qualidade. Para medir isso, seria preciso:
  1. mostrar no pacote WL o trecho real atual das linhas mascaradas (ou montar o prefixo sem máscara, a partir do arquivo de cada tarefa), para o SEARCH ter uma fonte correta;
  2. permitir um reparo também quando a edição é rejeitada, devolvendo ao modelo o diagnóstico `zero_occurrences`;
  3. usar 1 repetição com temperatura 0, ou 3 repetições com amostragem.

## v3: desenho corrigido (29/10, 15h53 às 16h09)

Commits `852803f` (implementação, Codex Terra) e `c37ce40` (correção de alinhamento). Snapshot ext4 em `c37ce40`. Resultados em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-prefix-cache-v3`. A 1ª tentativa abortou no primeiro episódio WL e foi arquivada em `-v3-aborted-align`: depois da edição da fase 1, uma linha omitida passou a alinhar como apagada.

### O que mudou

- **Linhas omitidas visíveis.** Os pacotes WL ganham uma seção com o texto atual, no workspace, de todas as linhas mascaradas do host. Cada região vem com 2 linhas de contexto e número de linha. São cerca de 670 tokens no bottle e 180 no ms. O W16 não recebe essa seção.
- **Reparo após edição rejeitada.** O modelo recebe o status e a mensagem do erro e pode tentar de novo. Fica atrás de uma opção (`repair_rejected_edits`), desligada por padrão no worker.
- **Até 2 reparos**, compartilhados entre edição rejeitada e teste visível.
- **1 repetição.** São 36 unidades.

Ressalva: o WL recebe informação que o W16 não recebe. Por isso, a comparação entre W16 e WL não isola só o tamanho do contexto.

### Resultado

Houve zero falhas de infraestrutura.

| Braço | Aprovadas | Episódios com reparo de edição | Última rejeição | TTFT (mediana) | Tempo/episódio |
|---|---|---:|---|---:|---:|
| P-W16 | 2/12 (`cont_path`, `recover_decode`) | 6 | 1 `zero_occurrences` | 1,0 s | 11,9 s |
| P-WL-cold | 2/12 (`cont_path`, `recover_decode`) | 10 | 9 `zero_occurrences`, 1 `malformed_output` | 17,8 s | 32,3 s |
| P-WL-warm | 2/12 (`cont_path`, `recover_decode`) | 9 | 8 `zero_occurrences`, 1 `malformed_output` | 2,1 s | 13,8 s |

As duas aprovações são as mesmas nos três braços. A falha dominante do W16 mudou: em 7 de 12 tarefas, o modelo respondeu `BLOCKED: insufficient_context`, porque a janela selecionada não continha o código do bug.

### Por que a v3 ainda não mede qualidade

1. **O marcador sumiu, mas o SEARCH continua errado.** `marker_in_search` ficou em 0 de 36 unidades. Nos WL, porém, o modelo escreve o SEARCH a partir do que ele imagina que está no arquivo, e não por cópia. Exemplos:
   - em `py_query`, `_parse_qsl` foi indentado como método;
   - em `js_sign`, o SEARCH traz um `Math.abs` que não existe no arquivo;
   - em `mcp_header` (os dois braços WL) e em `recover_date` (só no cold), o modelo copiou os **números de linha** da nova seção (`1606: ...`).
2. **O reparo de edição não ajuda com temperatura 0.** A mensagem diz só "Search block was not found". Com a mesma informação e temperatura 0, o modelo reenvia a mesma saída, idêntica byte a byte: 15 de 17 reparos de edição no WL frio, 14 de 16 no WL quente e 3 de 9 no W16. A ferramenta de edição do OpenCode funciona porque o modelo relê o arquivo depois do erro.

### Conclusão

- **Comprovado de novo:** o custo de latência. O WL quente fica perto do W16 (13,8 s contra 11,9 s), e o WL frio custa quase 3 vezes mais (32,3 s).
- **Qualidade:** neste worker de chamada única com SEARCH/REPLACE, o contexto longo **não melhorou** o acerto (2/12 nos três braços). O gargalo é a cópia exata do SEARCH pelo 4B, e não a falta de contexto. Isso vale tanto para o prefixo comum quanto para a seção de linhas omitidas.
- Para seguir com o T3b, seria preciso mudar o protocolo de edição, e não o contexto. Duas opções:
  - devolver no erro as linhas mais próximas do arquivo real (busca aproximada);
  - aceitar SEARCH com espaços normalizados ou âncoras por número de linha.

  As duas mudam o que está sendo medido. Por isso, recomendo encerrar o T3b com esta conclusão e voltar às direções fortes da etapa 5.

Diagnóstico: `scratchpad/t3bv3_diag.py`, `scratchpad/count_lineno.py` e `scratchpad/show_cands.py` e `scratchpad/count_repeats.py`. A saída está em `scratchpad/t3bv3-diag.txt`.
