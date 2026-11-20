<#
.SYNOPSIS
준비된 Windows Studio와 하위 서비스의 유휴 CPU 및 private commit을 기록한다.
.DESCRIPTION
새로 실행한 빈 작업 영역이 준비된 뒤 사용한다. 계측 전에 UI Automation으로
창을 조회하면 접근성 스레드가 활성화될 수 있다. 화면 확인과 자동화는 표본을
수집한 뒤에 수행한다. 로딩, GPU 메모리 또는 프레임 시간은 이 도구에서 계측하지 않는다.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateRange(1, 2147483647)]
    [int]$StudioProcessId,

    [Parameter(Mandatory)]
    [string]$Output,

    [ValidateRange(30, 300)]
    [int]$DurationSeconds = 30
)

$ErrorActionPreference = 'Stop'

function Get-StudioProcessTree {
    param([int]$RootId)

    $processTable = Get-CimInstance -ClassName Win32_Process |
        Select-Object ProcessId, ParentProcessId
    $remaining = [System.Collections.Generic.Queue[int]]::new()
    $visited = [System.Collections.Generic.HashSet[int]]::new()
    $remaining.Enqueue($RootId)
    while ($remaining.Count -gt 0) {
        $current = $remaining.Dequeue()
        if ($visited.Add($current)) {
            foreach ($child in $processTable) {
                if ($child.ParentProcessId -eq $current) {
                    $remaining.Enqueue([int]$child.ProcessId)
                }
            }
        }
    }
    return $visited | Sort-Object
}

function Get-StudioSample {
    param([int[]]$ProcessIds, [double]$ElapsedSeconds)

    $values = foreach ($processId in $ProcessIds) {
        $process = Get-Process -Id $processId
        [pscustomobject][ordered]@{
            pid = $process.Id
            name = $process.ProcessName
            start_time_utc = $process.StartTime.ToUniversalTime().ToString('o')
            cpu_seconds = $process.TotalProcessorTime.TotalSeconds
            private_commit_bytes = $process.PrivateMemorySize64
            working_set_bytes = $process.WorkingSet64
            handle_count = $process.HandleCount
        }
    }
    return [pscustomobject][ordered]@{
        elapsed_seconds = $ElapsedSeconds
        processes = @($values)
        combined_private_commit_bytes = ($values | Measure-Object -Property private_commit_bytes -Sum).Sum
        combined_working_set_bytes = ($values | Measure-Object -Property working_set_bytes -Sum).Sum
    }
}

# @brief 이미 있는 기록을 덮어쓰지 않고 먼저 빈 GUI와 해당 프로세스 계보를 확인한다.
$target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
if ([IO.File]::Exists($target)) {
    throw '기존 성능 기록을 덮어쓸 수 없습니다.'
}
$studio = Get-Process -Id $StudioProcessId
if ($studio.ProcessName -ne 'tracewave_gui' -or $studio.MainWindowHandle -eq [IntPtr]::Zero) {
    throw '화면이 준비된 tracewave_gui 프로세스 ID를 사용하세요.'
}
$processIds = @(Get-StudioProcessTree -RootId $StudioProcessId)
if ($processIds.Count -lt 2) {
    throw 'Studio에 연결한 Python 프로젝트 서비스를 확인할 수 없습니다.'
}

$start = [DateTimeOffset]::UtcNow
$clock = [Diagnostics.Stopwatch]::StartNew()
$samples = [System.Collections.Generic.List[object]]::new()
$samples.Add((Get-StudioSample -ProcessIds $processIds -ElapsedSeconds $clock.Elapsed.TotalSeconds))
$endTime = $samples[0].elapsed_seconds + $DurationSeconds
while ($samples[$samples.Count - 1].elapsed_seconds -lt $endTime) {
    $targetTime = $samples[0].elapsed_seconds + [Math]::Min($DurationSeconds, $samples.Count * 5)
    do {
        $remaining = $targetTime - $clock.Elapsed.TotalSeconds
        if ($remaining -gt 0) {
            Start-Sleep -Milliseconds ([int][Math]::Ceiling(1000 * $remaining))
        }
    } while ($clock.Elapsed.TotalSeconds -lt $targetTime)
    $samples.Add((Get-StudioSample -ProcessIds $processIds -ElapsedSeconds $clock.Elapsed.TotalSeconds))
}
if (Compare-Object -ReferenceObject $processIds -DifferenceObject @(Get-StudioProcessTree -RootId $StudioProcessId)) {
    throw '측정 중 프로젝트 서비스 프로세스 구성이 바뀌었습니다.'
}
$first = $samples[0]
$last = $samples[$samples.Count - 1]
foreach ($item in $first.processes) {
    foreach ($sample in $samples) {
        $same = $sample.processes | Where-Object { $_.pid -eq $item.pid -and $_.start_time_utc -eq $item.start_time_utc }
        if (-not $same) {
            throw '프로세스가 종료되거나 같은 ID로 다시 시작됐습니다.'
        }
    }
}
$elapsed = $last.elapsed_seconds - $first.elapsed_seconds
$cpuStart = ($first.processes | Measure-Object -Property cpu_seconds -Sum).Sum
$cpuEnd = ($last.processes | Measure-Object -Property cpu_seconds -Sum).Sum
if ($elapsed -lt $DurationSeconds -or $cpuEnd -lt $cpuStart) {
    throw '측정 시간 또는 누적 CPU 표본이 유효하지 않습니다.'
}
$guiPeak = ($samples | ForEach-Object { $_.processes | Where-Object pid -eq $StudioProcessId } |
    Measure-Object -Property private_commit_bytes -Maximum).Maximum
$combinedPeak = ($samples | Measure-Object -Property combined_private_commit_bytes -Maximum).Maximum
if ($guiPeak -le 0 -or $combinedPeak -lt $guiPeak -or $null -eq $cpuStart -or $null -eq $cpuEnd) {
    throw 'private commit과 CPU 합계가 유효하지 않습니다.'
}

$record = [pscustomobject][ordered]@{
    schema = 'rfad.windows-idle-measurement/0.1'
    recorded_utc = $start.ToString('o')
    scope = '초기 연결이 완료된 빈 Windows Studio와 그 하위 프로세스'
    elapsed_seconds = $elapsed
    studio_pid = $StudioProcessId
    executable_sha256 = (Get-FileHash -LiteralPath $studio.Path -Algorithm SHA256).Hash.ToLowerInvariant()
    operating_system = Get-CimInstance -ClassName Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber
    processor = @(Get-CimInstance -ClassName Win32_Processor | Select-Object Name, NumberOfLogicalProcessors)
    display_adapter = @(Get-CimInstance -ClassName Win32_VideoController | Select-Object Name, CurrentHorizontalResolution, CurrentVerticalResolution, CurrentRefreshRate)
    total_cpu_seconds = $cpuEnd - $cpuStart
    percent_of_one_logical_cpu = 100 * ($cpuEnd - $cpuStart) / $elapsed
    peak_sampled_gui_private_commit_bytes = $guiPeak
    peak_sampled_combined_private_commit_bytes = $combinedPeak
    samples = @($samples.ToArray())
    startup_measured = $false
    interactive_frames_measured = $false
    gpu_memory_measured = $false
}
$stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    $encoding = [Text.UTF8Encoding]::new($false)
    $content = $encoding.GetBytes(($record | ConvertTo-Json -Depth 8) + [Environment]::NewLine)
    $stream.Write($content, 0, $content.Length)
}
finally {
    $stream.Dispose()
}
$record | Select-Object elapsed_seconds, percent_of_one_logical_cpu, peak_sampled_gui_private_commit_bytes, peak_sampled_combined_private_commit_bytes
