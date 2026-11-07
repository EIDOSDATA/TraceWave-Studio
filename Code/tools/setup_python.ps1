<#
@file
@brief Code 내부의 서비스 및 CAD 개발 환경을 고정 의존성으로 구성한다.
@param Python CPython 3.12 실행 파일의 경로 또는 명령 이름.
@param SkipCad 서비스 환경만 구성할 때 지정한다.
#>
[CmdletBinding()]
param
(
    [string]$Python = 'python',
    [switch]$SkipCad
)

$ErrorActionPreference = 'Stop'
$codeRoot = Split-Path -Parent $PSScriptRoot
$profileRoot = Join-Path $codeRoot 'runtime_profiles'
$reportRoot = Join-Path $codeRoot '.local/python'
New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null

function Invoke-CheckedPython
{
    <# @brief Python 명령이 실패하면 후속 설치를 중단한다. #>
    param
    (
        [string]$Executable,
        [string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0)
    {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

function Initialize-LocalEnvironment
{
    <# @brief 고정된 하위 경로에만 venv를 만들고 실제 격리 상태를 확인한다. #>
    param([string]$Name)
    $environmentPath = Join-Path $codeRoot $Name
    $executable = Join-Path $environmentPath 'Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $executable))
    {
        Invoke-CheckedPython -Executable $Python -Arguments @('-I', '-m', 'venv', $environmentPath)
    }
    $check = @'
import pathlib, platform, struct, sys
expected = pathlib.Path(sys.argv[1]).resolve()
valid = sys.prefix != sys.base_prefix and pathlib.Path(sys.prefix).resolve() == expected
valid = valid and sys.version_info[:2] == (3, 12) and sys.platform == 'win32'
valid = valid and struct.calcsize('P') == 8 and platform.machine().upper() == 'AMD64'
if not valid:
    raise SystemExit('Expected a local Windows x64 CPython 3.12 virtual environment.')
'@
    Invoke-CheckedPython -Executable $executable -Arguments @('-I', '-c', $check, $environmentPath)
    return $executable
}

$servicePython = Initialize-LocalEnvironment -Name '.venv'
$serviceLock = Join-Path $profileRoot 'python-service-build.txt'
Invoke-CheckedPython -Executable $servicePython -Arguments @('-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:', '--require-hashes', '-r', $serviceLock)
Invoke-CheckedPython -Executable $servicePython -Arguments @('-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '--no-build-isolation', '--editable', $codeRoot)
Invoke-CheckedPython -Executable $servicePython -Arguments @('-I', '-m', 'pip', 'check')

if (-not $SkipCad)
{
    $cadPython = Initialize-LocalEnvironment -Name '.venv-cad'
    $cadLock = Join-Path $profileRoot 'python-cad-windows-x64.txt'
    $planPath = Join-Path $reportRoot 'cad-install-plan.json'
    $checkScript = Join-Path $PSScriptRoot 'check_cad_environment.py'
    Invoke-CheckedPython -Executable $cadPython -Arguments @('-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--dry-run', '--ignore-installed', '--only-binary=:all:', '--require-hashes', '--report', $planPath, '-r', $cadLock)
    Invoke-CheckedPython -Executable $cadPython -Arguments @('-I', '-X', 'utf8', $checkScript, '--check-plan', $planPath)
    Invoke-CheckedPython -Executable $cadPython -Arguments @('-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:', '--require-hashes', '--report', (Join-Path $reportRoot 'cad-install-result.json'), '-r', $cadLock)
    Invoke-CheckedPython -Executable $cadPython -Arguments @('-I', '-m', 'pip', 'check')
    Invoke-CheckedPython -Executable $cadPython -Arguments @('-I', '-X', 'utf8', $checkScript, '--output', (Join-Path $reportRoot 'cad-smoke.json'))
}

Write-Output 'Local Python development environments are ready.'
