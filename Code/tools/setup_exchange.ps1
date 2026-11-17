<#
@file
@brief 별도 출력 교환 worker의 Windows x64 Python 환경을 고정 wheel로 구성한다.
@param Python CPython 3.12 실행 파일의 경로 또는 명령 이름.
#>
[CmdletBinding()]
param
(
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$codeRoot = Split-Path -Parent $PSScriptRoot
$exchangeEnvironment = Join-Path $codeRoot '.venv-exchange'
$exchangePython = Join-Path $exchangeEnvironment 'Scripts/python.exe'
$exchangeLock = Join-Path $codeRoot 'runtime_profiles/python-exchange-windows-x64.txt'
$exchangeReports = Join-Path $codeRoot '.local/exchange-environment'

function Invoke-ExchangePython
{
    <# @brief 환경 구성 실패를 후속 설치 성공으로 가리지 않는다. #>
    param
    (
        [string]$Executable,
        [string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0)
    {
        throw "Exchange Python command failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $exchangePython))
{
    Invoke-ExchangePython -Executable $Python -Arguments @('-I', '-m', 'venv', $exchangeEnvironment)
}
$environmentCheck = @'
import pathlib, platform, struct, sys
expected = pathlib.Path(sys.argv[1]).resolve()
valid = sys.prefix != sys.base_prefix and pathlib.Path(sys.prefix).resolve() == expected
valid = valid and sys.version_info[:2] == (3, 12) and sys.platform == 'win32'
valid = valid and struct.calcsize('P') == 8 and platform.machine().upper() == 'AMD64'
if not valid:
    raise SystemExit('Expected a local Windows x64 CPython 3.12 virtual environment.')
'@
Invoke-ExchangePython -Executable $exchangePython -Arguments @('-I', '-c', $environmentCheck, $exchangeEnvironment)
New-Item -ItemType Directory -Force -Path $exchangeReports | Out-Null
Invoke-ExchangePython -Executable $exchangePython -Arguments @('-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:', '--require-hashes', '--report', (Join-Path $exchangeReports 'install.json'), '-r', $exchangeLock)
Invoke-ExchangePython -Executable $exchangePython -Arguments @('-I', '-m', 'pip', 'check')
Write-Output 'Local exchange worker environment is ready. Configure --exchange-python explicitly.'
