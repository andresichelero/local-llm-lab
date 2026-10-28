# Monitor local de LLM no Windows

A campanha `practical-agent-limits-skills-v8-recovery` tem três episódios
selecionados da v5, que mantém 42 concluídos em seu histórico. O painel deve
mostrar o progresso da recuperação sobre 3; não somar os protocolos como se fossem
uma única medição nem confundir os 42 concluídos anteriores com novos episódios.

O monitor scripts/Monitor-LocalLLM.bat abre um painel Windows e acompanha a
máquina sem iniciar, pausar ou alterar campanhas.

    D:\Usuario\Downloads\LLM\.worktrees\practical-agent-v2\scripts\Monitor-LocalLLM.bat

Para uma captura única, use Monitor-LocalLLM.bat -Once. A frequência e a
quantidade de execuções recentes podem ser ajustadas:

    Monitor-LocalLLM.bat -RefreshSeconds 3 -RecentRuns 10

O padrão é Ubuntu-24.04 e /home/foxtrot/local-llm-benchmark/results. Para outra
instalação, passe -Distro e -LinuxResultsRoot.

Para acompanhar a comparação de quantizações Qwen, use
`scripts/Monitor-QwenQuant.bat`. O painel compacto atualiza a fila v4, modelo
ativo, GPU, RAM e principais contadores de aplicativos; omite histórico e logs.
Ele consulta o estado v4 via `benchmark.qwen_status`, pois essa campanha mantém
`state.json` em vez de `status.json`. `Ctrl+C` encerra somente o monitor.

## O que aparece

- As quatro campanhas mais recentes por padrao, ordenadas por updated_at_utc, com protocolo, etapa,
  progresso, repetição e último modelo/tarefa.
- Denominador da campanha derivado da agenda do `manifest.json`:
  `immutable.repair_schedule` para campanhas repair, ou a soma de
  `stage_schedules` nas demais. `status.json` só é usado quando o manifest não
  contém agenda. Se o total do status divergir, o painel sinaliza a diferença e
  mantém o total do manifest para o progresso; nenhum arquivo de campanha é
  alterado.
- Alerta stale? quando o status diz running, mas não há runner correspondente.
- A correlação do runner usa o caminho exato de `--output` de cada execução;
  um runner r2 não mantém r1 como ativo. Se o comando não expõe um caminho
  correlacionável, o estado fica `unverified?` em vez de afirmar que está parado.
- A coluna `STATUS WRITE` mostra quando `status.json` foi gravado. Para cada
  run com runner correlacionado, o painel também mostra o PID, uptime do
  processo, hora em que o monitor o observou e a idade do último status.
  Uptime é tempo de vida do processo, não duração exata do episódio; a amostra
  do monitor indica presença do runner, não um heartbeat gravado pela campanha.
- CPU, RAM e principais processos do Windows; CPU, RAM, swap, cgroup e disco
  livre do WSL.
- O monitor também coleta os contadores Windows `GPU Process Memory` por PID,
  separando os valores Dedicated e Shared relatados pelo Windows. Eles são
  indícios por processo, não uma decomposição exata do total da placa: a
  Microsoft documenta casos em que esses contadores mostram valores incorretos.
  PID 0 é uso não atribuído a um processo. Não some esses valores para inferir o
  total nem atribua a diferença ao `llama-server`; compare separadamente com a
  memória total do dispositivo e, quando a atribuição exata for necessária,
  confirme em uma captura Windows Performance Recorder/Analyzer. [Documentação
  Microsoft](https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/gpu-process-memory-counters-report-wrong-value).
- GPU via nvidia-smi: utilização, VRAM, temperatura, potência instantânea e
  limite, ventoinha, clocks, estado de energia, versão do driver/KMD e versão
  CUDA UMD informada pelo cliente WSL. O cliente atual não informa um teto de
  compatibilidade CUDA no mesmo campo dos clientes antigos.
- Processos compute: PID do WSL é cruzado com `/proc` para revelar o processo
  mesmo quando NVML responde `[Not Found]`. O driver WSL pode não expor VRAM
  dedicada por processo; nesses casos o painel mostra `n/d` em vez de inventar
  um valor.
- Os contadores Windows são amostras do momento em que o monitor roda; eles não
  reconstroem a atribuição por processo de capturas históricas. Se uma medição
  antiga só guardou VRAM livre do dispositivo, registre a alocação por Steam ou
  navegador como informada pelo operador, não como telemetria histórica
  verificada. Uma tentativa incompleta por contenção de recursos não equivale a
  uma qualificação válida nem a uma falha de raciocínio do modelo.
- Os contadores Windows `GPU Process Memory` (`Dedicated Usage` e `Shared
  Usage`) são associados ao PID e nome do processo, mas podem superestimar ou
  divergir do total. A lista ajuda a investigar Steam, navegadores, DWM e outros
  consumidores que não aparecem como processos CUDA do WSL; isoladamente, não
  comprova quanta memória física cada aplicação reteve.
- A leitura por processo é contemporânea: ela não permite atribuir
  retroativamente a VRAM de uma execução antiga. Uma execução sem telemetria
  histórica por PID deve permanecer marcada como atribuição não verificada ou
  contenção de recursos, sem ser convertida em sucesso de modelo.
- Runner e servidores llama.cpp do WSL, com PID, CPU, RSS, duração, modelo,
  contexto, camadas GPU e cache KV quando esses argumentos estão disponíveis.
- Watt-hora estimados da GPU durante a sessão do monitor. Isso não mede a CPU
  nem o consumo total da máquina.

Temperatura de CPU não é preenchida com estimativas: nesta máquina, a consulta
ACPI/WMI não expõe sensor confiável. O painel não instala um leitor de sensores
durante a campanha ativa. `nvcc` é procurado no PATH e nos caminhos CUDA comuns;
sua ausência não impede executar um `llama-server` CUDA já compilado. CUDA UMD
é a versão da interface CUDA reportada pelo cliente WSL, não um teto de
compatibilidade nem prova de que o Toolkit de compilação esteja instalado.
CPU seconds dos processos Windows é acumulado.

## Lembrete de manutenção

Ao adicionar ou renomear scripts, protocolos, formatos de status.json, etapas,
fontes de GPU ou métricas, atualizar em conjunto:

1. scripts/local_llm_snapshot.py e scripts/Watch-LocalLLM.ps1;
2. tests/test_local_llm_monitor.py, somente nos casos afetados;
3. esta documentação, incluindo comandos, caminhos e limites das métricas.

Executar apenas os testes alterados/adicionados e fazê-lo depois da campanha
ativa terminar, conforme a instrução do usuário de 21/10/2026. Depois, conferir
o painel com -Once; isso verifica o monitor, não inicia inferência.


A rodada corrected-v3 monta etapas dinamicamente. O painel usa o maior cronograma congelado disponível; mostra episódios executados, em revisão e pulados, com motivo de task_quarantines. Execução concluída não significa tarefa correta. Chamadas principais, título e compactação ficam nos registros e CSV da campanha.
# Política limits-skills-v1

O monitor reconhece também `benchmark.practical_review_replay`, acompanha cobertura
exata e expõe os contadores separados do último orçamento finalizado. Esses contadores
não são telemetria de uma requisição em andamento. `budget_exhausted` não equivale a
erro de raciocínio. A automação recorrente permanece removida; executar `-Once` não
inicia inferência. Contratos e comandos atuais: [LIMITS_SKILLS.md](LIMITS_SKILLS.md).

## Politica limits-skills-v2: espera de capacidade, erro ativo e autorizacao

Para a v8 de revisao (recuperacao do replay de B2/C2/M1), o painel mostra o
denominador de agenda imutavel do manifest (`immutable.schedule.maximum_episodes`)
na linha DENOMINADOR. Ele nao substitui o progresso por etapa; nao some os
protocolos como se fossem uma unica medicao.

Espera de capacidade (capacity-wait.json): antes de qualquer geracao, o
`execute_prepared` aguarda no maximo 120 segundos (janela), com intervalo de 2
segundos, exige tres amostras seguidas prontas e grava `capacity-wait.json` no
diretorio do run. Essa espera e preparacao do episodio, nunca orcamento de
modelo: nenhum prompt e enviado, nenhuma chamada de inferencia acontece, e o
monitor nao fecha aplicacoes nem altera o piso de VRAM. Se a sonda continuar
indisponivel (por exemplo, servo llama-server ativo ou preflight de GPU sem
espaco), o run não começa, o painel mostra o motivo como infraestrutura e o
evento fica marcado `probe_never_ready`.

Estado de autorizacao: a linha ERRO ATIVO mostra o `error` atual do
manifest.json; erros anteriores a retry autorizado sao movidos para
`resolved_errors` (contador ERROS RESOLVIDOS EM ARQUIVO), entao o erro ativo
nunca e um erro ja tratado. A linha AUTORIZACAO RETRY-BLOCKED indica se a
invocacao atual seguiu com `--retry-blocked`. Um manifest bloqueado sem essa
autorizacao nao roda de novo; a autorizacao e concedida uma vez por invocacao,
registrada em `authorization-audit.jsonl` enquanto `authorization-in-use.json`
existe, e o retry retenta apenas episodios bloqueados por infraestrutura,
preservando as tentativas anteriores e sem repetir concluidos nem ignorar
quarentenas.


