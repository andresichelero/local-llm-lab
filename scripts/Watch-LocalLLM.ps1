[CmdletBinding()]
param(
    [ValidateRange(1, 60)]
    [int]$RefreshSeconds = 5,
    [ValidateRange(1, 20)]
    [int]$RecentRuns = 4,
    [string]$Distro = 'Ubuntu-24.04',
    [string]$LinuxResultsRoot = '/home/foxtrot/local-llm-benchmark/results',
    [switch]$Once
)

$ErrorActionPreference = 'Continue'
$script:EnergyWh = 0.0
$script:LastPowerW = $null
$script:LastPowerTime = $null
. (Join-Path $PSScriptRoot 'Get-WindowsGpuProcessMemory.ps1')

function Get-TerminalWidth {
    try {
        $width = [Console]::WindowWidth
        if ($width -gt 0) { return [Math]::Min(240, [Math]::Max(72, $width)) }
    } catch {}
    try {
        $width = $Host.UI.RawUI.WindowSize.Width
        if ($width -gt 0) { return [Math]::Min(240, [Math]::Max(72, $width)) }
    } catch {}
    return 120
}

function Limit-Text([string]$Text, [int]$Width) {
    if ($Width -le 0) { return '' }
    if ($null -eq $Text) { $Text = '' }
    if ($Text.Length -le $Width) { return $Text }
    if ($Width -le 3) { return $Text.Substring(0, $Width) }
    return $Text.Substring(0, $Width - 3) + '...'
}

function Write-PanelLine([string]$Text, [ConsoleColor]$Color = [ConsoleColor]::Gray) {
    Write-Host (Limit-Text $Text (Get-TerminalWidth)) -ForegroundColor $Color
}

function Write-PanelRule {
    Write-Host ('-' * (Get-TerminalWidth)) -ForegroundColor DarkGray
}

function Get-HostSnapshot {
    $cpuInfo = $null
    $osInfo = $null
    try { $cpuInfo = @(Get-CimInstance Win32_Processor) } catch {}
    try { $osInfo = Get-CimInstance Win32_OperatingSystem } catch {}

    $cpu = $null
    if ($cpuInfo.Count -gt 0) {
        $oneCpu = $cpuInfo[0]
        $cpu = [pscustomobject]@{
            name = [string]$oneCpu.Name
            cores = [int]$oneCpu.NumberOfCores
            threads = [int]$oneCpu.NumberOfLogicalProcessors
            load_percent = [Math]::Round((($cpuInfo | Measure-Object LoadPercentage -Average).Average), 1)
            max_clock_mhz = [int]$oneCpu.MaxClockSpeed
        }
    }

    $memory = $null
    if ($osInfo) {
        $total = [double]$osInfo.TotalVisibleMemorySize * 1KB
        $free = [double]$osInfo.FreePhysicalMemory * 1KB
        $memory = [pscustomobject]@{
            total_gib = [Math]::Round($total / 1GB, 2)
            free_gib = [Math]::Round($free / 1GB, 2)
            used_gib = [Math]::Round(($total - $free) / 1GB, 2)
            used_percent = if ($total -gt 0) { [Math]::Round(100 * ($total - $free) / $total, 1) } else { $null }
        }
    }

    $top = @()
    try {
        $top = @(Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 4 |
            ForEach-Object {
                [pscustomobject]@{
                    name = $_.ProcessName
                    pid = $_.Id
                    ram_mib = [Math]::Round($_.WorkingSet64 / 1MB, 0)
                    cpu_seconds = if ($_.CPU -ne $null) { [Math]::Round($_.CPU, 1) } else { $null }
                }
            })
    } catch {}
    $gpuProcessSnapshot = Get-WindowsGpuProcessMemorySnapshot
    return [pscustomobject]@{
        cpu = $cpu
        memory = $memory
        top_processes = $top
        gpu_processes = $gpuProcessSnapshot.processes
        gpu_process_error = $gpuProcessSnapshot.error
        gpu_process_source = $gpuProcessSnapshot.source
    }
}

function Get-WslSnapshot {
    $helper = Join-Path $PSScriptRoot 'local_llm_snapshot.py'
    try {
        $linuxHelper = & wsl.exe --distribution $Distro --exec wslpath -u $helper 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $linuxHelper) {
            return [pscustomobject]@{ error = 'Nao foi possivel localizar o coletor dentro do WSL.' }
        }
        $raw = & wsl.exe --distribution $Distro --exec python3 $linuxHelper --results-root $LinuxResultsRoot --recent $RecentRuns 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $raw) {
            return [pscustomobject]@{ error = 'O WSL/Python nao retornou um snapshot valido.' }
        }
        $json = $raw -join [Environment]::NewLine
        return ($json | ConvertFrom-Json)
    } catch {
        return [pscustomobject]@{ error = $_.Exception.Message }
    }
}

function Format-LocalTime([string]$Utc) {
    if (-not $Utc) { return '-' }
    try { return ([DateTimeOffset]::Parse($Utc).ToLocalTime().ToString('dd/MM HH:mm:ss')) }
    catch { return $Utc }
}

function Format-Elapsed($Seconds) {
    if ($null -eq $Seconds -or "$Seconds" -eq '') { return 'n/d' }
    try { $span = [TimeSpan]::FromSeconds([Math]::Max(0, [double]$Seconds)) }
    catch { return 'n/d' }
    if ($span.TotalDays -ge 1) { return ('{0}d {1:hh\:mm\:ss}' -f [int]$span.TotalDays, $span) }
    return $span.ToString('hh\:mm\:ss')
}

function Update-EnergyEstimate($Gpu, [DateTime]$Now) {
    if ($null -eq $Gpu -or $null -eq $Gpu.power_w) { return }
    $power = [double]$Gpu.power_w
    if ($null -ne $script:LastPowerW -and $null -ne $script:LastPowerTime) {
        $hours = ($Now - $script:LastPowerTime).TotalHours
        if ($hours -gt 0 -and $hours -lt 1) {
            $script:EnergyWh += (($script:LastPowerW + $power) / 2.0) * $hours
        }
    }
    $script:LastPowerW = $power
    $script:LastPowerTime = $Now
}

function Write-RunTable($Runs, [int]$Width) {
    if (-not $Runs -or $Runs.Count -eq 0) {
        Write-PanelLine 'Nenhum status.json encontrado no diretorio de resultados.' Yellow
        return
    }
    if ($Width -lt 108) {
        foreach ($run in $Runs) {
            $progress = if ($run.scheduled -gt 0) { '{0}/{1} ({2}%)' -f $run.completed, $run.scheduled, $run.progress_percent } else { '{0}/?' -f $run.completed }
            $line = '{0} | {1} | {2} | {3} | {4}' -f $run.name, $run.display_status, $progress, $run.stage, (Format-LocalTime $run.updated_at_utc)
            Write-PanelLine $line
            $e = $run.latest_episode
            Write-PanelLine ('  recente: {0} / {1} r{2} ({3})' -f $e.model, $e.task, $e.repetition, $e.episode_status) DarkGray
        }
        return
    }

    $nameW = [Math]::Min(38, [Math]::Max(26, [int]($Width * 0.30)))
    $lastW = [Math]::Max(18, $Width - ($nameW + 10 + 13 + 12 + 17 + 8))
    $header = ('{0,-' + $nameW + '} {1,-10} {2,13} {3,-12} {4,-17} {5}') -f 'RUN', 'STATE', 'EPISODES', 'STAGE', 'STATUS WRITE', 'LATEST MODEL / TASK'
    Write-PanelLine $header DarkCyan
    foreach ($run in $Runs) {
        $progress = if ($run.scheduled -gt 0) { '{0}/{1} ({2}%)' -f $run.completed, $run.scheduled, $run.progress_percent } else { '{0}/?' -f $run.completed }
        $e = $run.latest_episode
        $latest = '{0} / {1} r{2} {3}' -f $e.model, $e.task, $e.repetition, $e.episode_status
        $line = ('{0,-' + $nameW + '} {1,-10} {2,13} {3,-12} {4,-17} {5}') -f (Limit-Text $run.name $nameW), (Limit-Text $run.display_status 10), $progress, (Limit-Text $run.stage 12), (Format-LocalTime $run.updated_at_utc), (Limit-Text $latest $lastW)
        Write-PanelLine $line
    }
}

function Write-ProcessDetails($Snapshot) {
    $processes = @($Snapshot.processes)
    if (-not $processes -or $processes.Count -eq 0) {
        Write-PanelLine 'Nenhum runner, servidor llama.cpp ou OpenCode detectado no WSL.' DarkGray
    } else {
        foreach ($proc in $processes) {
            if ($proc.kind -eq 'llama-server') {
                $matches = [regex]::Matches([string]$proc.command, '(?:^|\s)(--[\w-]+)(?:\s+("[^"]+"|\S+))?')
                $argsMap = @{}
                foreach ($match in $matches) {
                    $key = $match.Groups[1].Value
                    $value = $match.Groups[2].Value.Trim('"')
                    if ($key) { $argsMap[$key] = $value }
                }
                $model = 'modelo sem identificar'
                if ($argsMap['--model']) { $model = [IO.Path]::GetFileName($argsMap['--model']) }
                if ($argsMap['--alias']) { $model = '{0} | alias {1}' -f $model, $argsMap['--alias'] }
                $kv = ''
                if ($argsMap['--cache-type-k'] -or $argsMap['--cache-type-v']) {
                    $kv = ' | KV K/V {0}/{1}' -f $argsMap['--cache-type-k'], $argsMap['--cache-type-v']
                }
                $description = 'llama-server PID {0} | {1} | contexto {2} | camadas GPU {3}{4}' -f $proc.pid, $model, $argsMap['--ctx-size'], $argsMap['--n-gpu-layers'], $kv
                $resourceLine = '  CPU {0}% | RSS {1} MiB | tempo ativo {2}' -f $proc.cpu_percent, $proc.rss_mib, $proc.elapsed
            } else {
                $description = '{0} PID {1} | CPU {2}% | RAM {3} MiB | {4}' -f $proc.kind, $proc.pid, $proc.cpu_percent, $proc.rss_mib, $proc.elapsed
                $resourceLine = ''
                if ($proc.cwd) { $description += ' | ' + $proc.cwd }
            }
            Write-PanelLine $description
            if ($resourceLine) { Write-PanelLine $resourceLine DarkGray }
        }
    }
    $apps = @($Snapshot.gpu.compute_processes)
    if ($apps.Count -gt 0) {
        $processById = @{}
        foreach ($proc in $processes) { $processById[[string]$proc.pid] = $proc }
        $appText = ($apps | ForEach-Object {
            $gpuPid = [string]$_[0]
            $memoryText = if ($_[2] -match '^\d+(\.\d+)?$') { '{0} MiB relatados pelo driver' -f $_[2] } else { 'VRAM por processo n/d' }
            if ($processById.ContainsKey($gpuPid)) {
                $matched = $processById[$gpuPid]
                'WSL PID {0} {1} | {2}' -f $gpuPid, $matched.kind, $memoryText
            } else {
                'PID {0} {1} ({2}) | {3}' -f $gpuPid, $_[1], 'nao mapeado em /proc WSL', $memoryText
            }
        }) -join ' | '
        Write-PanelLine ('GPU compute processes (WSL view): ' + $appText) DarkGray
    }
}

function Show-MonitorFrame {
    $now = [DateTime]::Now
    $hostInfo = Get-HostSnapshot
    $snapshot = Get-WslSnapshot
    $width = Get-TerminalWidth
    $gpu = $snapshot.gpu
    Update-EnergyEstimate $gpu $now

    if (-not $Once) { Clear-Host }
    Write-PanelLine ('LOCAL LLM LAB | monitor ao vivo | {0}' -f $now.ToString('dd/MM/yyyy HH:mm:ss')) Cyan
    Write-PanelRule

    if ($hostInfo.cpu) {
        $c, $m = $hostInfo.cpu, $hostInfo.memory
        $hostLine = 'HOST CPU {0}% | {1} | {2} cores/{3} threads | max {4} MHz' -f $c.load_percent, $c.name, $c.cores, $c.threads, $c.max_clock_mhz
        $ramLine = 'HOST RAM {0}/{1} GiB ({2}%) | {3} GiB livre | temperatura CPU n/d (ACPI/WMI sem sensor confiavel)' -f $m.used_gib, $m.total_gib, $m.used_percent, $m.free_gib
        Write-PanelLine $hostLine White
        Write-PanelLine $ramLine White
    } else {
        Write-PanelLine 'HOST CPU/RAM indisponiveis via CIM.' Yellow
    }

    if ($snapshot.error) {
        Write-PanelLine ('WSL ' + $snapshot.error) Yellow
    } else {
        $w, $disk, $cuda = $snapshot.memory, $snapshot.disk, $snapshot.cuda_toolkit
        $cgroupText = ''
        if ($snapshot.cgroup_memory -and $snapshot.cgroup_memory.limit_gib) {
            $cgroupText = ' | cgroup {0}/{1} GiB' -f $snapshot.cgroup_memory.current_gib, $snapshot.cgroup_memory.limit_gib
        }
        $diskText = if ($disk) { ' | disco WSL livre {0} GiB' -f $disk.free_gib } else { '' }
        $wslLine = 'WSL CPU {0}% | RAM {1}/{2} GiB usada ({3}%) | disponivel {4} GiB | swap {5}/{6} GiB' -f $snapshot.cpu_percent, $w.used_gib, $w.total_gib, $w.used_percent, $w.available_gib, $w.swap_used_gib, $w.swap_total_gib
        $wslDetail = 'WSL recursos{0}{1}' -f $cgroupText, $diskText
        Write-PanelLine $wslLine White
        Write-PanelLine $wslDetail DarkGray

        $cudaText = if ($cuda.version) { 'nvcc {0}' -f $cuda.version } else { 'nvcc nao detectado (PATH/locais CUDA)' }
        if ($gpu) {
            $throttle = if ($gpu.throttle_reasons -and $gpu.throttle_reasons -ne '0x0000000000000000') { ' | throttle flags ' + $gpu.throttle_reasons } else { '' }
            $gpuLine = 'GPU {0} | utilizacao {1}% | VRAM {2}/{3} MiB | livre {4} MiB | memoria ativa {5}%' -f $gpu.name, $gpu.gpu_util_percent, $gpu.vram_used_mib, $gpu.vram_total_mib, $gpu.vram_free_mib, $gpu.memory_util_percent
            $gpuDetail = 'GPU {0} C | potencia {1}/{2} W | fan {3}% | {4} | clocks core/mem {5}/{6} MHz{7}' -f $gpu.temperature_c, $gpu.power_w, $gpu.power_limit_w, $gpu.fan_percent, $gpu.pstate, $gpu.graphics_clock_mhz, $gpu.memory_clock_mhz, $throttle
            $gpuColor = if ($gpu.gpu_util_percent -gt 0) { [ConsoleColor]::Green } else { [ConsoleColor]::Gray }
            Write-PanelLine $gpuLine $gpuColor
            Write-PanelLine $gpuDetail
            $driver = if ($gpu.driver) { $gpu.driver } else { 'n/d' }
            $kmd = if ($gpu.kernel_driver_version) { $gpu.kernel_driver_version } else { 'n/d' }
            if ($gpu.cuda_driver_max) {
                $cudaVersion = 'compatibilidade CUDA max {0}' -f $gpu.cuda_driver_max
            } elseif ($gpu.cuda_umd_version) {
                $cudaVersion = 'CUDA UMD {0} (WSL)' -f $gpu.cuda_umd_version
            } else {
                $cudaVersion = 'versao CUDA n/d'
            }
            $cudaLine = 'Driver NVIDIA {0} | KMD {1} | {2} | {3} | energia GPU estimada nesta sessao: {4:N3} Wh' -f $driver, $kmd, $cudaVersion, $cudaText, $script:EnergyWh
            Write-PanelLine $cudaLine DarkGray
        } else {
            Write-PanelLine ('GPU nvidia-smi indisponivel | ' + $cudaText) Yellow
        }
    }

    Write-PanelRule
    Write-PanelLine ('RUNS MAIS RECENTES | ordenadas por atualizacao do status | ate {0}' -f $RecentRuns) Cyan
    if ($snapshot.error) {
        Write-PanelLine 'Sem leitura de resultados ate o WSL responder.' Yellow
    } else {
        $runs = @($snapshot.recent_runs)
        foreach ($run in $runs) {
            if (-not $run.PSObject.Properties['display_status']) {
                $run | Add-Member -NotePropertyName display_status -NotePropertyValue $run.status
            }
        }
        Write-RunTable $runs $width
        foreach ($run in $runs) {
            if ($run.schedule_mismatch) {
                $warning = 'AGENDA MISMATCH {0}: manifest {1}; status.json {2}; progresso usa manifest.' -f $run.name, $run.manifest_scheduled, $run.status_scheduled
                Write-PanelLine $warning Yellow
            }
            if ($run.runner_active -eq $true) {
                $activity = 'RUNNER PRESENTE {0}: PID {1} uptime {2} | amostra {3} | status.json gravado {4} (idade {5})' -f $run.name, $run.runner_pid, $run.runner_elapsed, (Format-LocalTime $run.runner_observed_at_utc), (Format-LocalTime $run.updated_at_utc), (Format-Elapsed $run.status_age_seconds)
                Write-PanelLine $activity Green
            } elseif ($run.display_status -eq 'stale?') {
                $stale = 'SEM RUNNER CORRESPONDENTE {0}: status.json gravado {1} (idade {2})' -f $run.name, (Format-LocalTime $run.updated_at_utc), (Format-Elapsed $run.status_age_seconds)
                Write-PanelLine $stale DarkYellow
            }
        }
        if ($runs.Count -gt 0) {
            $latest = $runs[0]
            $episode = $latest.latest_episode
            $failure = if ($episode.failure) { ' | falha ' + $episode.failure } else { '' }
            $runLabel = if ($latest.runner_active) { 'RUN ATUAL' } else { 'RUN MAIS RECENTE' }
            $latestLine = '{0}: {1} | protocolo {2} | progresso {3}/{4} ({5}%) | etapa {6}' -f $runLabel, $latest.name, $latest.protocol, $latest.completed, $latest.scheduled, $latest.progress_percent, $latest.stage
            $episodeLine = 'ULTIMO EPISODIO: {0} | {1} | perfil {2} | r{3} | {4}{5}' -f $episode.model, $episode.task, $episode.profile, $episode.repetition, $episode.episode_status, $failure
            Write-PanelLine $latestLine Yellow
            Write-PanelLine $episodeLine Yellow
            $stageDetails = @($latest.episodes_by_stage.PSObject.Properties | ForEach-Object {
                '{0}: {1} executados / {2} bloqueados / {3} interrompidos / {4} revisao / {5} pulados' -f $_.Name, $_.Value.complete, $_.Value.blocked, $_.Value.interrupted, ([int]$_.Value.review_required), ([int]$_.Value.skipped_review)
            })
            if ($stageDetails.Count -gt 0) { Write-PanelLine ('ETAPAS: ' + ($stageDetails -join ' | ')) DarkGray }
            if ($latest.last_completed_budget) {
                $budget = $latest.last_completed_budget
                Write-PanelLine ('ULTIMO ORCAMENTO FINALIZADO: main {0}/{1}; titulo {2}/{3}; compactacao {4}/{5}; motivo {6}' -f $budget.used.main, $budget.ceilings.main, $budget.used.title, $budget.ceilings.title, $budget.used.compaction, $budget.ceilings.compaction, $budget.limit_reason) DarkGray
            }
            if ($latest.task_quarantines) {
                foreach ($item in $latest.task_quarantines.PSObject.Properties) {
                    Write-PanelLine ('REVISAO: {0} | {1}' -f $item.Name, $item.Value.reason) Yellow
                }
            }
            if ($null -ne $latest.agenda_denominator) {
                Write-PanelLine ('DENOMINADOR DA AGENDA IMUTAVEL: {0} episodios' -f $latest.agenda_denominator) DarkGray
            }
            if ($latest.capacity_wait) {
                $wait = $latest.capacity_wait
                $waitText = 'PREPARACAO/ESPERA DE CAPACIDADE: {0} | {1} | {2:N1}s aguardados (janela {3}s, intervalo {4}s, {5} amostras)' -f $wait.outcome, $wait.note, [double]$wait.waited_seconds, 120, [double]$wait.poll_seconds, $wait.stable_samples_required
                $waitColor = if ($wait.ready) { [ConsoleColor]::Green } else { [ConsoleColor]::Yellow }
                Write-PanelLine $waitText $waitColor
            }
            if ($latest.active_error) {
                Write-PanelLine ('ERRO ATIVO: {0}' -f $latest.active_error) Yellow
            }
            $resolvedCount = 0
            if ($null -ne $latest.resolved_errors) { $resolvedCount = [int]$latest.resolved_errors }
            if ($resolvedCount -gt 0) {
                Write-PanelLine ('ERROS RESOLVIDOS EM ARQUIVO: {0}' -f $resolvedCount) DarkGray
            }
            $authorizationColor = if ($latest.operator_retry_blocked) { [ConsoleColor]::Cyan } else { [ConsoleColor]::DarkGray }
            $authorizationText = if ($latest.operator_retry_blocked) { 'concedida nesta invocacao (--retry-blocked); um retry unico' } else { 'ausente (run comum)' }
            Write-PanelLine ('AUTORIZACAO RETRY-BLOCKED: {0}' -f $authorizationText) $authorizationColor
        }
    }

    Write-PanelLine 'O QUE ESTA RODANDO NO WSL' Cyan
    if (-not $snapshot.error) { Write-ProcessDetails $snapshot }

    Write-PanelLine 'MAIORES PROCESSOS WINDOWS POR RAM (CPU acumulada desde o inicio)' DarkCyan
    if ($hostInfo.top_processes.Count -gt 0) {
        for ($i = 0; $i -lt $hostInfo.top_processes.Count; $i += 2) {
            $first = $hostInfo.top_processes[$i]
            $appText = '{0} PID {1}: {2} MiB RAM, {3}s CPU' -f $first.name, $first.pid, $first.ram_mib, $first.cpu_seconds
            if (($i + 1) -lt $hostInfo.top_processes.Count) {
                $second = $hostInfo.top_processes[$i + 1]
                $appText += ' | {0} PID {1}: {2} MiB RAM, {3}s CPU' -f $second.name, $second.pid, $second.ram_mib, $second.cpu_seconds
            }
            Write-PanelLine $appText DarkGray
        }
    }

    Write-PanelLine 'CONTADORES WINDOWS GPU POR PROCESSO (estimativa Dedicated / Shared)' DarkCyan
    if ($hostInfo.gpu_process_error) {
        Write-PanelLine ('GPU Process Memory indisponivel: ' + $hostInfo.gpu_process_error) Yellow
    } elseif ($hostInfo.gpu_processes.Count -gt 0) {
        $topGpu = @($hostInfo.gpu_processes | Select-Object -First 8)
        $namedApps = @($hostInfo.gpu_processes | Where-Object {
            $_.name -match '(?i)steam|chrome|msedge|firefox|brave|opera'
        })
        $displayGpu = @($topGpu + $namedApps | Sort-Object pid -Unique)
        foreach ($proc in $displayGpu) {
            $line = '{0} PID {1}: {2} MiB dedicada relatada, {3} MiB compartilhada relatada' -f `
                $proc.name, $proc.pid, $proc.dedicated_mib, $proc.shared_mib
            Write-PanelLine $line DarkGray
        }
        Write-PanelLine ('Fonte: ' + $hostInfo.gpu_process_source + '; amostra atual, nao historica.') DarkGray
        Write-PanelLine 'Os valores por PID podem divergir do total da placa; PID 0 significa uso sem processo atribuivel.' Yellow
    } else {
        Write-PanelLine 'GPU Process Memory nao retornou processos com uso.' DarkGray
    }

    Write-PanelRule
    Write-PanelLine ('Refresh {0}s | coleta {1:HH:mm:ss} | Ctrl+C encerra somente o monitor; a fila continua.' -f $RefreshSeconds, $now) DarkGray
}

do {
    Show-MonitorFrame
    if (-not $Once) { Start-Sleep -Seconds $RefreshSeconds }
} while (-not $Once)



