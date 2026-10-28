param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [int]$Windows = 5,
    [int]$IntervalSeconds = 300,
    [int]$CaptureSeconds = 120,
    [int]$SampleSeconds = 5
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-WindowsGpuProcessMemory.ps1')
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$started = [DateTimeOffset]::UtcNow
$statusFile = Join-Path $OutputDirectory 'status.json'
$query = 'timestamp,name,driver_version,pstate,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,power.limit,clocks.gr,clocks.mem'
for ($window = 0; $window -lt $Windows; $window++) {
    $due = $started.AddSeconds($window * $IntervalSeconds)
    while ([DateTimeOffset]::UtcNow -lt $due) { Start-Sleep -Seconds 1 }
    $captureEnd = [DateTimeOffset]::UtcNow.AddSeconds($CaptureSeconds)
    $csv = Join-Path $OutputDirectory ('window-{0:D2}.csv' -f ($window + 1))
    $processCsv = Join-Path $OutputDirectory ('gpu-processes-window-{0:D2}.csv' -f ($window + 1))
    $processErrors = 0
    'timestamp,name,driver_version,pstate,gpu_percent,memory_percent,vram_used_mib,vram_total_mib,temperature_c,power_w,power_limit_w,core_mhz,memory_mhz' | Set-Content -LiteralPath $csv -Encoding UTF8
    'sampled_at_utc,process_name,pid,dedicated_mib,shared_mib,counter_source' | Set-Content -LiteralPath $processCsv -Encoding UTF8
    while ([DateTimeOffset]::UtcNow -lt $captureEnd) {
        $sample = & "$env:WINDIR\System32\nvidia-smi.exe" "--query-gpu=$query" '--format=csv,noheader,nounits' 2>&1
        $ok = $LASTEXITCODE -eq 0
        if ($ok) { $sample | Add-Content -LiteralPath $csv -Encoding UTF8 }
        $processSample = Get-WindowsGpuProcessMemorySnapshot
        if ($processSample.error) { $processErrors++ }
        foreach ($process in $processSample.processes) {
            [pscustomobject]@{
                sampled_at_utc = $processSample.sampled_at_utc
                process_name = $process.name
                pid = $process.pid
                dedicated_mib = $process.dedicated_mib
                shared_mib = $process.shared_mib
                counter_source = $processSample.source
            } | Export-Csv -LiteralPath $processCsv -Append -NoTypeInformation -Encoding UTF8
        }
        @{
            status = 'observing'
            window = ($window + 1)
            updated_utc = [DateTimeOffset]::UtcNow.ToString('o')
            started_utc = $started.ToString('o')
            telemetry_ok = $ok
            process_telemetry_ok = (-not $processSample.error)
            process_telemetry_errors = $processErrors
            gpu_processes = $processSample.processes
            gpu_process_source = $processSample.source
            gpu_process_error = $processSample.error
            latest = ($sample -join "`n")
            note = 'Read-only telemetry; device total and Windows-reported per-process Dedicated/Shared counters are separate. Per-process counters may disagree with device total; PID 0 is unattributed. This script never starts inference or changes GPU settings.'
        } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statusFile -Encoding UTF8
        Start-Sleep -Seconds $SampleSeconds
    }
}
@{
    status = 'complete'
    windows = $Windows
    started_utc = $started.ToString('o')
    updated_utc = [DateTimeOffset]::UtcNow.ToString('o')
    inference_started = $false
    process_telemetry = 'Windows GPU Process Memory counters'
    process_telemetry_errors = $processErrors
} | ConvertTo-Json | Set-Content -LiteralPath $statusFile -Encoding UTF8
