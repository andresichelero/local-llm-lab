function Get-WindowsGpuProcessMemorySnapshot {
    [CmdletBinding()]
    param(
        [ValidateRange(1, 5)]
        [int]$SampleIntervalSeconds = 1
    )

    $sampledAt = [DateTimeOffset]::UtcNow.ToString('o')
    try {
        $processNames = @{}
        foreach ($process in Get-Process -ErrorAction SilentlyContinue) {
            $processNames[[string]$process.Id] = $process.ProcessName
        }

        $counterPaths = @(
            '\GPU Process Memory(*)\Dedicated Usage',
            '\GPU Process Memory(*)\Shared Usage'
        )
        $sampleSet = $null
        $sampleError = $null
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                $sampleSet = Get-Counter -Counter $counterPaths `
                    -SampleInterval $SampleIntervalSeconds -MaxSamples 1 -ErrorAction Stop
                $sampleError = $null
                break
            } catch {
                $sampleError = $_.Exception.Message
                if ($attempt -lt 3) { Start-Sleep -Milliseconds 250 }
            }
        }
        if (-not $sampleSet) {
            if ($sampleError) { throw $sampleError }
            throw 'GPU Process Memory counter returned no sample'
        }
        $byPid = @{}
        foreach ($sample in $sampleSet.CounterSamples) {
            if ($sample.InstanceName -notmatch '^pid_(\d+)') { continue }
            $pidValue = [int]$Matches[1]
            $key = [string]$pidValue
            if (-not $byPid.ContainsKey($key)) {
                $processName = if ($pidValue -eq 0) {
                    'System/unattributed'
                } elseif ($processNames.ContainsKey($key)) {
                    $processNames[$key]
                } else {
                    'Unknown process'
                }
                $byPid[$key] = [pscustomobject]@{
                    name = $processName
                    pid = $pidValue
                    dedicated_bytes = 0.0
                    shared_bytes = 0.0
                }
            }

            $bytes = [double]$sample.CookedValue
            if ($sample.Path -match 'Dedicated Usage$') {
                $byPid[$key].dedicated_bytes += $bytes
            } elseif ($sample.Path -match 'Shared Usage$') {
                $byPid[$key].shared_bytes += $bytes
            }
        }

        $processes = @($byPid.Values | ForEach-Object {
            [pscustomobject]@{
                name = $_.name
                pid = $_.pid
                dedicated_mib = [Math]::Round($_.dedicated_bytes / 1MB, 1)
                shared_mib = [Math]::Round($_.shared_bytes / 1MB, 1)
            }
        } | Where-Object {
            $_.dedicated_mib -gt 0 -or $_.shared_mib -gt 0
        } | Sort-Object dedicated_mib -Descending)

        return [pscustomobject]@{
            sampled_at_utc = $sampledAt
            source = 'Windows GPU Process Memory counters (reported per PID; may disagree with device total)'
            processes = $processes
            error = $null
        }
    } catch {
        return [pscustomobject]@{
            sampled_at_utc = $sampledAt
            source = 'Windows GPU Process Memory counters (reported per PID; may disagree with device total)'
            processes = @()
            error = $_.Exception.Message
        }
    }
}
