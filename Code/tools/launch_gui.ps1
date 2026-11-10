<#
@brief Code 폴더의 개발용 Python과 소스를 명시하여 GUI 창을 실행한다.
@param Workspace 비어 있으면 Code/.local/gui-workspace를 사용한다.
@param Python 비어 있으면 Code/.venv/Scripts/python.exe를 사용한다.
@param CadPython 비어 있으면 존재하는 Code/.venv-cad/Scripts/python.exe를 사용하며 없으면 CAD 없이 실행한다.
@param OpenEmsWsl 설치/감사된 고정 WSL openEMS 런타임을 명시적으로 연결한다.
#>
[CmdletBinding()]
param(
    [string]$Workspace = '',
    [string]$Python = '',
    [string]$CadPython = '',
    [switch]$OpenEmsWsl
)

$ErrorActionPreference = 'Stop'
$codeRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$guiExecutable = Join-Path $codeRoot 'build/windows-release/bin/tracewave_gui.exe'
if ([string]::IsNullOrWhiteSpace($Workspace))
{
    $Workspace = Join-Path $codeRoot '.local/gui-workspace'
}
if ([string]::IsNullOrWhiteSpace($Python))
{
    $Python = Join-Path $codeRoot '.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $guiExecutable -PathType Leaf))
{
    throw 'Build the GUI first with tools/setup_native.ps1.'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf))
{
    throw 'Prepare the Python environment first or pass -Python with its executable path.'
}
if ([string]::IsNullOrWhiteSpace($CadPython))
{
    $defaultCadPython = Join-Path $codeRoot '.venv-cad/Scripts/python.exe'
    if (Test-Path -LiteralPath $defaultCadPython -PathType Leaf)
    {
        $CadPython = $defaultCadPython
    }
}
elseif (-not (Test-Path -LiteralPath $CadPython -PathType Leaf))
{
    throw 'Prepare the CAD environment first or pass -CadPython with its executable path.'
}
$guiArguments = @(
    '--python', [System.IO.Path]::GetFullPath($Python),
    '--source', (Join-Path $codeRoot 'src'),
    '--workspace', [System.IO.Path]::GetFullPath($Workspace)
)
if (-not [string]::IsNullOrWhiteSpace($CadPython))
{
    $guiArguments += @('--cad-python', [System.IO.Path]::GetFullPath($CadPython))
}
if ($OpenEmsWsl)
{
    $guiArguments += '--openems-wsl'
}
# @brief pipeline으로 GUI 프로세스 종료까지 기다려 실제 종료 코드를 읽는다.
& $guiExecutable @guiArguments | Out-Null
if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0)
{
    throw "GUI exited with code $LASTEXITCODE."
}
