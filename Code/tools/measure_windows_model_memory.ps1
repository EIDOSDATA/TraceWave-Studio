<#
@brief 100만 삼각형 합성 시험의 전용 Windows 프로세스 자원을 별도 실행에서 관찰한다.
#>
param(
    [Parameter(Mandatory)] [string] $Fixture,
    [Parameter(Mandatory)] [string] $Trace,
    [Parameter(Mandatory)] [string] $Report,
    [string] $Probe = "$PSScriptRoot/../build/windows-release/bin/tracewave_canvas_display_probe.exe"
)

$ErrorActionPreference = 'Stop'
$start = [Diagnostics.ProcessStartInfo]::new((Resolve-Path -LiteralPath $Probe).Path)
$start.UseShellExecute = $false
$tracePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Trace)
$reportPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Report)
foreach ($path in @($tracePath, $reportPath))
{
    if (Test-Path -LiteralPath $path)
    {
        throw "새 시험 출력 경로가 필요합니다. $path"
    }
}
if ($tracePath -eq $reportPath)
{
    throw '원시 시각과 자원 보고서는 별도 경로가 필요합니다.'
}
$start.ArgumentList.Add($tracePath)
$start.ArgumentList.Add('--model')
$start.ArgumentList.Add((Resolve-Path -LiteralPath $Fixture).Path)

$counters = @(
    '\GPU Process Memory(*)\Dedicated Usage',
    '\GPU Process Memory(*)\Shared Usage',
    '\GPU Process Memory(*)\Total Committed'
)
$points = [Collections.Generic.List[object]]::new()
$gpuNames = @('dedicated usage', 'shared usage', 'total committed')
$clock = [Diagnostics.Stopwatch]::StartNew()
$process = [Diagnostics.Process]::Start($start)
try
{
    $owner = '^pid_' + $process.Id + '_'
    while (-not $process.HasExited -and $clock.Elapsed.TotalSeconds -lt 60)
    {
        $observed = Get-Counter -Counter $counters
        $process.Refresh()
        if ($process.HasExited)
        {
            break
        }
        $samples = @($observed.CounterSamples | Where-Object { $_.InstanceName -match $owner -and $_.Status -eq 0 })
        $gpu = [ordered]@{}
        foreach ($name in $gpuNames)
        {
            $byCounter = @($samples | Where-Object { $_.Path.EndsWith("\" + $name, [StringComparison]::OrdinalIgnoreCase) })
            $value = $null
            if ($byCounter.Count -gt 0)
            {
                $value = [long]($byCounter | Measure-Object -Property RawValue -Sum).Sum
            }
            $gpu[$name.Replace(' ', '_') + '_bytes'] = $value
        }
        $points.Add([ordered]@{
            elapsed_ms = $clock.Elapsed.TotalMilliseconds
            private_commit_bytes = $process.PrivateMemorySize64
            working_set_bytes = $process.WorkingSet64
            peak_working_set_bytes = $process.PeakWorkingSet64
            handles = $process.HandleCount
            gpu = $gpu
        })
        [void]$process.WaitForExit(1000)
    }
    if (-not $process.HasExited -or $process.ExitCode -ne 0 -or $points.Count -lt 10)
    {
        throw '전용 창의 3D 자원 실행을 완료하지 못했습니다.'
    }
    $handle = [IO.FileStream]::new($reportPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try
    {
        $json = [ordered]@{
            probe_pid = $process.Id
            sample_interval_ms_requested = 1000
            sample_scope = 'ModelView and DXGI marker capture in the same process'
            points = $points
        } | ConvertTo-Json -Depth 8
        $data = [Text.Encoding]::UTF8.GetBytes($json + [Environment]::NewLine)
        $handle.Write($data)
    }
    finally
    {
        $handle.Dispose()
    }
}
finally
{
    if (-not $process.HasExited)
    {
        $process.Kill()
        $process.WaitForExit()
    }
    $process.Dispose()
}
