<#
@file
@brief 재부팅 후 전용 WSL2 배포의 설치를 한 번 재개하고 실제 실행을 확인한다.
@param Install 배포가 없을 때 TraceWave-Dev만 새로 설치한다. 생략하면 조회만 한다.
@details 기존 배포의 설정, 패키지와 기본 배포를 변경하지 않는다.
자동 재부팅, 자동 권한 상승, 반복 설치 및 openEMS 설치는 수행하지 않는다.
#>
[CmdletBinding()]
param
(
    [switch]$Install
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$codeRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$profilePath = Join-Path $codeRoot 'runtime_profiles/wsl-development.json'
$profile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
$distribution = 'TraceWave-Dev'
$distributionSource = 'Ubuntu-24.04'
$stateRoot = Join-Path $codeRoot '.local/wsl'
$installPath = [System.IO.Path]::GetFullPath((Join-Path $stateRoot $distribution))
$statusPath = Join-Path $stateRoot 'status.json'
$wslExecutable = (Get-Command 'wsl.exe' -ErrorAction Stop).Source

if ($profile.distribution.name -ne $distribution -or $profile.distribution.source -ne $distributionSource)
{
    throw 'The WSL profile must name the dedicated TraceWave-Dev Ubuntu-24.04 distribution.'
}
if (-not $installPath.StartsWith($codeRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase))
{
    throw 'The WSL installation directory must remain below Code.'
}

function Get-DistributionNames
{
    <# @brief 표시 언어와 NUL 문자에 의존하지 않고 등록 배포 이름을 읽는다. #>
    $lines = @(& $wslExecutable --list --quiet 2>&1)
    if ($LASTEXITCODE -ne 0)
    {
        throw ('Cannot enumerate WSL distributions: ' + ($lines -join ' '))
    }
    foreach ($line in $lines)
    {
        $name = ([string]$line -replace "`0", '').Trim()
        if ($name.Length -gt 0)
        {
            Write-Output $name
        }
    }
}

function Save-Status
{
    <# @brief 설치 명령 종료값과 실제 실행 준비 상태를 분리해 기록한다. #>
    param
    (
        [string]$State,
        [bool]$Registered,
        [bool]$Runnable,
        [object]$InstallExitCode,
        [string]$Kernel = ''
    )
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    [ordered]@{
        schema = 'rfad.runtime.wsl-check/0.1'
        checked_at = [DateTimeOffset]::UtcNow.ToString('o')
        distribution = $distribution
        install_path = $installPath
        state = $State
        registered = $Registered
        runnable = $Runnable
        install_exit_code = $InstallExitCode
        kernel = $Kernel
        openems_installed = $null
        openems_check_performed = $false
        headless_dependencies_verified = $false
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statusPath -Encoding utf8
}

$names = @(Get-DistributionNames)
$installExitCode = $null
if ($distribution -notin $names -and $Install)
{
    if (Test-Path -LiteralPath $installPath)
    {
        throw 'The dedicated installation directory already exists without a registered distribution. Inspect it before retrying; this script never deletes or overwrites it.'
    }
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    & $wslExecutable --install $distributionSource --name $distribution --location $installPath --no-launch --version 2 --web-download
    $installExitCode = $LASTEXITCODE
    $names = @(Get-DistributionNames)
}

if ($distribution -notin $names)
{
    Save-Status -State 'distribution_missing_restart_or_install_required' -Registered $false -Runnable $false -InstallExitCode $installExitCode
    Write-Warning 'TraceWave-Dev is not registered. A successful installer exit code is not readiness. If Windows requested a restart, restart it manually before rerunning with -Install.'
    exit 2
}

$releaseOutput = @(& $wslExecutable --distribution $distribution --user root --exec /bin/cat /etc/os-release 2>&1)
$releaseExitCode = $LASTEXITCODE
$kernelOutput = @(& $wslExecutable --distribution $distribution --user root --exec /bin/uname -r 2>&1)
$kernelExitCode = $LASTEXITCODE
$releaseText = ($releaseOutput -join "`n") -replace "`0", ''
$kernelText = (($kernelOutput -join "`n") -replace "`0", '').Trim()
$ubuntu = $releaseText -match '(?m)^ID="?ubuntu"?\r?$'
$version = $releaseText -match '(?m)^VERSION_ID="?24\.04"?\r?$'
$wsl2 = $kernelText -match '(?i)WSL2'

if ($releaseExitCode -ne 0 -or $kernelExitCode -ne 0 -or -not $ubuntu -or -not $version -or -not $wsl2)
{
    Save-Status -State 'distribution_execution_not_verified' -Registered $true -Runnable $false -InstallExitCode $installExitCode -Kernel $kernelText
    Write-Warning 'TraceWave-Dev is registered, but Ubuntu 24.04 on a WSL2 kernel did not pass the execution check. Existing distributions are not modified.'
    exit 3
}

Save-Status -State 'wsl_ready_openems_not_configured' -Registered $true -Runnable $true -InstallExitCode $installExitCode -Kernel $kernelText
Write-Output 'TraceWave-Dev runs Ubuntu 24.04 on WSL2. openEMS and Qt-free dependency checks remain pending.'
exit 0
