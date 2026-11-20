<#
.SYNOPSIS
보이는 빈 Windows Studio의 F0 시작 시간을 수집하고 cold 표본을 합산한다.
.DESCRIPTION
Warm은 같은 빈 workspace를 사용해 준비 실행 1회와 계측 실행을 수행한다.
Cold는 Windows를 재부팅한 뒤 Studio를 처음 실행할 때 한 번 수집한다.
수집 전 GUI 자동화나 실행 파일의 내용 읽기를 피한다. PowerShell 7에서 실행한다.
#>
[CmdletBinding(DefaultParameterSetName = 'Collect')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Collect')]
    [string]$Gui,
    [Parameter(Mandatory, ParameterSetName = 'Collect')]
    [string]$Python,
    [Parameter(Mandatory, ParameterSetName = 'Collect')]
    [string]$Source,
    [Parameter(ParameterSetName = 'Collect')]
    [ValidateSet('Warm', 'Cold')]
    [string]$Mode = 'Warm',
    [Parameter(ParameterSetName = 'Collect')]
    [ValidateRange(1, 100)]
    [int]$SampleCount,
    [Parameter(Mandatory, ParameterSetName = 'SummarizeCold')]
    [ValidateNotNullOrEmpty()]
    [string[]]$ColdReports,
    [Parameter(Mandatory)]
    [string]$Output
)

$ErrorActionPreference = 'Stop'
$schema = 'rfad.windows-startup-measurement/0.1'

# @brief 작은 표본에서도 p95는 nearest-rank로 계산하고 성공한 표본만으로 실패를 가리지 않는다.
function Get-StartupStatistics {
    param([object[]]$Samples, [int]$Minimum, [int]$WindowLimit, [int]$ReadyLimit)

    $count = $Samples.Count
    $measurements = [ordered]@{}
    $metrics = [ordered]@{ first_window_ms = $WindowLimit; new_project_ready_ms = $ReadyLimit }
    $complete = $count -gt 0 -and @($Samples | Where-Object { -not $_.ok }).Count -eq 0
    foreach ($name in $metrics.Keys) {
        $values = @()
        if ($complete) {
            $values = @($Samples | ForEach-Object { $_.$name } | Sort-Object)
        }
        $median = $null
        $p95 = $null
        $maximum = $null
        if ($values.Count -gt 0) {
            $middle = [int][Math]::Floor($count / 2)
            $median = $values[$middle]
            if ($count % 2 -eq 0) {
                $median = ($values[$middle - 1] + $values[$middle]) / 2.0
            }
            $p95 = $values[[int][Math]::Ceiling(0.95 * $count) - 1]
            $maximum = $values[-1]
        }
        $measurements[$name] = [ordered]@{
            median = $median
            p95 = $p95
            maximum = $maximum
            target_p95 = $metrics[$name]
            within_target = if ($complete -and $count -ge $Minimum) { $p95 -le $metrics[$name] } else { $null }
        }
    }
    [ordered]@{ sample_count = $count; minimum = $Minimum; complete = $complete; timing_ms = $measurements }
}

# @brief 최초 표시와 준비 카운터의 진위와 순서를 확인하고 원시 표본을 보존한다.
function Invoke-StartupSample {
    param([Diagnostics.ProcessStartInfo]$StartInfo, [int]$Number)
    $sample = [ordered]@{ number = $Number; ok = $false }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $StartInfo
    $started = $false
    try {
        $sample.launch_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
        $started = $process.Start()
        $sample.launch_return_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
        if (-not $started) {
            throw 'Studio 프로세스를 시작하지 못했습니다.'
        }
        $sample.pid = $process.Id
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) {
            throw 'Studio가 30초 안에 계측을 끝내고 종료하지 못했습니다.'
        }
        $sample.exit_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
        $sample.exit_code = $process.ExitCode
        if (-not [Threading.Tasks.Task]::WaitAll(@($stdout, $stderr), 5000)) {
            throw '계측 응답 파이프가 종료되지 않았습니다.'
        }
        $markers = $stdout.GetAwaiter().GetResult() | ConvertFrom-Json -AsHashtable
        $sample.probe = $markers
        if ($stderr.GetAwaiter().GetResult()) {
            $sample.stderr = $stderr.Result.Substring(0, [Math]::Min(512, $stderr.Result.Length))
        }
        if ($markers.schema -ne 'rfad.windows-startup-probe/0.1' -or ($markers.pid -ne $process.Id) -or
            ($markers.qpc_frequency -ne [Diagnostics.Stopwatch]::Frequency)) {
            throw 'GUI 이정표의 형식, 프로세스 또는 카운터가 일치하지 않습니다.'
        }
        if (-not $markers.ok -or $process.ExitCode -ne 0) {
            throw "GUI 시작 실패: $($markers.error)"
        }
        $paint = [long]$markers.canvas_painted_qpc
        $service = [long]$markers.service_ready_qpc
        $ready = [Math]::Max($paint, $service)
        if ([Math]::Min($paint, $service) -lt $sample.launch_qpc -or $ready -gt $sample.exit_qpc -or
            $markers.dpi -le 0 -or $markers.client_width -le 0 -or $markers.client_height -le 0) {
            throw '이정표 시간이나 Windows 화면 크기가 유효하지 않습니다.'
        }
        $scale = 1000.0 / [Diagnostics.Stopwatch]::Frequency
        $sample.first_window_ms = ($paint - $sample.launch_qpc) * $scale
        $sample.new_project_ready_ms = ($ready - $sample.launch_qpc) * $scale
        $sample.ok = $true
    }
    catch {
        $sample.error = $_.Exception.Message
    }
    finally {
        if ($started -and -not $process.HasExited) {
            # @brief 계측기가 만든 프로세스만 정리한다. 그 서비스의 job handle도 함께 닫힌다.
            try {
                $process.Kill()
                if (-not $process.WaitForExit(5000)) {
                    $sample.cleanup_error = '계측 Studio의 종료 시간을 초과했습니다.'
                }
            }
            catch {
                if (-not $process.HasExited) {
                    $sample.cleanup_error = $_.Exception.Message
                }
            }
        }
        $process.Dispose()
    }
    return $sample
}

$target = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
if ([IO.File]::Exists($target) -or [IO.Directory]::Exists($target)) {
    throw '기존 성능 기록을 덮어쓸 수 없습니다.'
}
if (-not [IO.Directory]::Exists([IO.Path]::GetDirectoryName($target))) {
    throw '기록의 상위 폴더를 먼저 준비하세요.'
}

if ($PSCmdlet.ParameterSetName -eq 'SummarizeCold') {
    $uniqueBoots = [Collections.Generic.HashSet[string]]::new()
    $coldSamples = @()
    $baseline = $null
    $conditions = @()
    foreach ($file in $ColdReports) {
        $inputReport = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json -AsHashtable
        if ($inputReport.schema -ne $schema -or $inputReport.mode -ne 'Cold' -or
            -not $inputReport.cold_first_launch_asserted_by_operator -or $null -eq $inputReport.fixture -or
            @($inputReport.samples).Count -ne 1 -or -not $inputReport.samples[0].ok -or
            [string]::IsNullOrWhiteSpace($inputReport.boot_started_utc) -or
            -not $uniqueBoots.Add(([DateTimeOffset]$inputReport.boot_started_utc).UtcDateTime.ToString('o'))) {
            throw '서로 다른 부팅에서 수집한 성공한 cold 단일 표본을 지정하세요.'
        }
        $sample = $inputReport.samples[0]
        $windowMs = $sample.first_window_ms -as [double]
        $readyMs = $sample.new_project_ready_ms -as [double]
        if ($null -eq $windowMs -or $null -eq $readyMs -or -not [double]::IsFinite($windowMs) -or
            -not [double]::IsFinite($readyMs) -or $windowMs -le 0 -or $readyMs -lt $windowMs) {
            throw 'Cold 시작 시간의 값 또는 순서가 유효하지 않습니다.'
        }
        $fixture = $inputReport.fixture | ConvertTo-Json -Depth 8 -Compress
        if ($null -eq $baseline) {
            $baseline = $fixture
        }
        elseif ($baseline -cne $fixture) {
            throw '빌드, 서비스 또는 Windows 표시 조건이 다른 cold 기록입니다.'
        }
        $coldSamples += $sample
        $conditions += [ordered]@{
            boot_started_utc = $inputReport.boot_started_utc
            sha256 = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $record = [ordered]@{
        schema = $schema
        mode = 'ColdSummary'
        recorded_utc = [DateTimeOffset]::UtcNow.ToString('o')
        fixture = ($baseline | ConvertFrom-Json -AsHashtable)
        inputs = $conditions
        samples = $coldSamples
        summary = Get-StartupStatistics $coldSamples 5 3000 5000
    }
}
else {
    if (-not [Diagnostics.Stopwatch]::IsHighResolution) {
        throw 'Windows 고해상도 경과 시간 카운터가 필요합니다.'
    }
    if (-not $PSBoundParameters.ContainsKey('SampleCount')) {
        $SampleCount = if ($Mode -eq 'Cold') { 1 } else { 20 }
    }
    if ($Mode -eq 'Cold' -and $SampleCount -ne 1) {
        throw 'Cold는 부팅당 첫 실행 한 번만 수집합니다.'
    }
    $guiPath = (Resolve-Path -LiteralPath $Gui).Path
    $pythonPath = (Resolve-Path -LiteralPath $Python).Path
    $sourcePath = (Resolve-Path -LiteralPath $Source).Path
    if (-not [IO.File]::Exists($guiPath) -or -not [IO.File]::Exists($pythonPath) -or
        -not [IO.Directory]::Exists($sourcePath)) {
        throw 'Studio와 서비스 실행 파일, 서비스 소스 폴더를 확인하세요.'
    }

    # @brief 사용자의 프로젝트와 분리한 빈 workspace를 이번 계측 전용으로 만든다.
    $fixturePath = $target + '.workspace'
    New-Item -Path $fixturePath -ItemType Directory | Out-Null
    $info = [Diagnostics.ProcessStartInfo]::new($guiPath)
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in @('--python', $pythonPath, '--source', $sourcePath, '--workspace', $fixturePath, '--measure-startup')) {
        $info.ArgumentList.Add($argument)
    }
    $recordedAt = [DateTimeOffset]::UtcNow.ToString('o')
    $warmup = $null
    $samples = @()
    if ($Mode -eq 'Warm') {
        $warmup = Invoke-StartupSample $info 0
    }
    if ($null -eq $warmup -or $warmup.ok) {
        for ($index = 1; $index -le $SampleCount; $index++) {
            $sample = Invoke-StartupSample $info $index
            $samples += $sample
            if (-not $sample.ok) {
                break
            }
        }
    }

    # @brief 메타데이터를 뒤에서 읽어 cold의 시작 전에 실행 파일 캐시를 건드리지 않는다.
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    $first = @($samples | Where-Object { $_.ok } | Select-Object -First 1)
    $display = $null
    if ($first.Count -eq 1) {
        $display = $first[0].probe | Select-Object dpi, client_width, client_height
        foreach ($sample in $samples) {
            if ($sample.ok -and ($sample.probe.dpi -ne $display.dpi -or
                $sample.probe.client_width -ne $display.client_width -or
                $sample.probe.client_height -ne $display.client_height)) {
                $sample.ok = $false
                $sample.error = '계측 중 DPI 또는 창 크기가 바뀌었습니다.'
            }
        }
    }
    $summary = if ($Mode -eq 'Cold') {
        Get-StartupStatistics $samples 5 3000 5000
    }
    else {
        Get-StartupStatistics $samples 20 1500 2000
    }
    $sourceManifest = @(Get-ChildItem -LiteralPath (Join-Path $sourcePath 'rfad') -Recurse -File -Filter '*.py' |
        Sort-Object FullName | ForEach-Object {
            $relative = [IO.Path]::GetRelativePath($sourcePath, $_.FullName).Replace('\', '/')
            $digest = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "$relative $digest"
        })
    $sourceBytes = [Text.Encoding]::UTF8.GetBytes($sourceManifest -join "`n")
    $sourceHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($sourceBytes)).ToLowerInvariant()
    $record = [ordered]@{
        schema = $schema
        mode = $Mode
        recorded_utc = $recordedAt
        boot_started_utc = $os.LastBootUpTime.ToUniversalTime().ToString('o')
        cold_first_launch_asserted_by_operator = $Mode -eq 'Cold'
        fixture = [ordered]@{
            executable_sha256 = (Get-FileHash -LiteralPath $guiPath -Algorithm SHA256).Hash.ToLowerInvariant()
            service_launcher_sha256 = (Get-FileHash -LiteralPath $pythonPath -Algorithm SHA256).Hash.ToLowerInvariant()
            service_source_sha256 = $sourceHash
            service_source_files = $sourceManifest.Count
            operating_system = $os | Select-Object Caption, Version, BuildNumber
            processor = @(Get-CimInstance -ClassName Win32_Processor | Select-Object Name, NumberOfLogicalProcessors)
            video = @(Get-CimInstance -ClassName Win32_VideoController | Select-Object Name, CurrentHorizontalResolution,
                CurrentVerticalResolution, CurrentRefreshRate)
            window = $display
            worker = 'lightweight-project-service'
        }
        qpc_frequency = [Diagnostics.Stopwatch]::Frequency
        warmup = $warmup
        requested_samples = $SampleCount
        samples = $samples
        summary = $summary
    }
}

$stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    $encoding = [Text.UTF8Encoding]::new($false)
    $bytes = $encoding.GetBytes(($record | ConvertTo-Json -Depth 12) + [Environment]::NewLine)
    $stream.Write($bytes, 0, $bytes.Length)
}
finally {
    $stream.Dispose()
}
$record.summary | ConvertTo-Json -Depth 5
if (-not $record.summary.complete) {
    throw '실패한 시작이 있습니다. 원시 기록을 확인하세요.'
}
