[CmdletBinding()]
param(
    [ValidateRange(5, 60)]
    [int]$RefreshSeconds = 10,
    [string]$Distro = 'Ubuntu-24.04',
    [string]$LinuxResultsRoot = '/home/foxtrot/local-llm-benchmark/results',
    [string]$LinuxWorktree = '/mnt/d/Usuario/Downloads/LLM/.worktrees/practical-agent-v2'
)

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'Get-WindowsGpuProcessMemory.ps1')

function Get-JsonFromWsl([string[]]$Arguments) {
    try {
        $raw = & wsl.exe --distribution $Distro @Arguments 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $raw) {
            return [pscustomobject]@{ error = 'WSL snapshot indisponivel.' }
        }
        return (($raw -join [Environment]::NewLine) | ConvertFrom-Json)
    } catch {
        return [pscustomobject]@{ error = 'Nao foi possivel ler o estado do WSL.' }
    }
}

function Get-PanelData {
    $helperPath = Join-Path $PSScriptRoot 'local_llm_snapshot.py'
    $linuxHelper = (& wsl.exe --distribution $Distro --exec wslpath -u $helperPath 2>$null) -join ''
    if ($LASTEXITCODE -ne 0 -or -not $linuxHelper) {
        return [pscustomobject]@{ error = 'Nao encontrei o coletor WSL.' }
    }

    $snapshot = Get-JsonFromWsl @(
        '--exec', 'python3', $linuxHelper,
        '--results-root', $LinuxResultsRoot,
        '--recent', '1'
    )
    $qwen = Get-JsonFromWsl @(
        '--cd', $LinuxWorktree,
        '--exec', '/home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python',
        '-m', 'benchmark.qwen_status',
        '--output', '/home/foxtrot/local-llm-benchmark/results/qwen-quant-harness-optimization-final-oom-v2'
    )
    $gpuProcesses = Get-WindowsGpuProcessMemorySnapshot
    $hostMemory = $null
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $hostMemory = [Math]::Round(([double]$os.FreePhysicalMemory * 1KB) / 1GB, 1)
    } catch {}

    return [pscustomobject]@{
        snapshot = $snapshot
        qwen = $qwen
        gpu_processes = $gpuProcesses
        host_ram_free_gib = $hostMemory
    }
}

function Format-GiB([double]$MiB) {
    return ('{0:N1}' -f ($MiB / 1024))
}

while ($true) {
    $data = Get-PanelData
    Clear-Host
    Write-Host ('QWEN FINAL  |  {0}' -f (Get-Date -Format 'HH:mm:ss')) -ForegroundColor Cyan
    Write-Host ''

    if ($data.error -or $data.qwen.error -or $data.snapshot.error) {
        $message = $data.error
        if (-not $message) { $message = $data.qwen.error }
        if (-not $message) { $message = $data.snapshot.error }
        Write-Host $message -ForegroundColor Yellow
        Write-Host 'Ctrl+C fecha apenas o monitor; a inferencia nao e alterada.' -ForegroundColor DarkGray
        Start-Sleep -Seconds $RefreshSeconds
        continue
    }

    $q = $data.qwen
    $s = $data.snapshot
    $stateColor = if ($q.status -eq 'running') { 'Green' } elseif ($q.status -eq 'waiting_for_resources') { 'Yellow' } else { 'Gray' }
    $done = [int]$q.finished_records
    $total = [int]$q.scheduled_units
    $percent = if ($total -gt 0) { [Math]::Round(100 * $done / $total, 1) } else { 0 }
    $waitCount = @($q.resource_waiting.PSObject.Properties).Count
    Write-Host ('FILA   {0}  |  {1}/{2} ({3}%)  |  {4} aguardando recurso' -f `
        $q.status.ToUpperInvariant(), $done, $total, $percent, $waitCount) -ForegroundColor $stateColor

    $runner = @($s.processes | Where-Object { $_.kind -eq 'benchmark-runner' } | Select-Object -First 1)[0]
    $server = @($s.processes | Where-Object { $_.kind -eq 'llama-server' } | Select-Object -First 1)[0]
    $modelName = $null
    if ($server) {
        $match = [regex]::Match([string]$server.command, '(?:^|\s)--model\s+("[^"]+"|\S+)')
        if ($match.Success) {
            $modelPath = $match.Groups[1].Value.Trim('"')
            $modelName = [IO.Path]::GetFileName($modelPath)
        }
    }
    if ($modelName) {
        Write-Host ('ATIVO  {0}  |  contexto {1}  |  llama PID {2}' -f `
            $modelName, $q.current.context, $server.pid) -ForegroundColor White
        Write-Host ('       CPU {0}%  |  RAM {1} GiB  |  ativo {2}' -f `
            $server.cpu_percent, (Format-GiB $server.rss_mib), $server.elapsed) -ForegroundColor DarkGray
    } elseif ($q.current.attempt_status -eq 'running') {
        Write-Host ('ATIVO  preparando modelo {0}  |  {1}' -f `
            $q.current.model, $q.current.engine) -ForegroundColor White
    } else {
        Write-Host 'ATIVO  sem inferencia neste momento' -ForegroundColor DarkGray
    }
    if ($runner) {
        Write-Host ('FILA   supervisor PID {0}' -f $runner.pid) -ForegroundColor DarkGray
    }

    $gpu = $s.gpu
    if ($gpu) {
        Write-Host ('GPU    {0}  |  {1}/{2} GiB usada  |  {3} GiB livre  |  {4}%  |  {5} C' -f `
            $gpu.name, (Format-GiB $gpu.vram_used_mib), (Format-GiB $gpu.vram_total_mib), `
            (Format-GiB $gpu.vram_free_mib), $gpu.gpu_util_percent, $gpu.temperature_c) -ForegroundColor Green
    }

    $wslRam = $s.memory
    $hostRam = if ($null -ne $data.host_ram_free_gib) { $data.host_ram_free_gib } else { 'n/d' }
    $disk = if ($s.disk) { $s.disk.free_gib } else { 'n/d' }
    Write-Host ('RAM    WSL {0} GiB livre  |  Windows {1} GiB livre  |  disco WSL {2} GiB livre' -f `
        $wslRam.available_gib, $hostRam, $disk) -ForegroundColor Gray

    $appRows = @($data.gpu_processes.processes | Where-Object {
        $_.name -match '(?i)steam|brave|chrome|msedge|firefox|opera|dwm|system/unattributed'
    } | Sort-Object dedicated_mib -Descending | Select-Object -First 4)
    if ($appRows.Count -gt 0) {
        $appSummary = ($appRows | ForEach-Object {
            '{0} {1} MiB' -f $_.name, $_.dedicated_mib
        }) -join '  |  '
        Write-Host ('APPS*  ' + $appSummary) -ForegroundColor DarkGray
        Write-Host '* Contadores Windows estimados; podem divergir do total da placa.' -ForegroundColor DarkGray
    }

    Write-Host ''
    Write-Host 'Ctrl+C fecha apenas o monitor; a inferencia continua.' -ForegroundColor DarkGray
    Start-Sleep -Seconds $RefreshSeconds
}
