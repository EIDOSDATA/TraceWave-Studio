<#
@file
@brief 사용자별 Windows 앱 등록과 설치 파일 제거를 담당한다.
@param DisplayVersion 설치 시 표시할 배포 버전.
@param StudioExe 현재 설치의 아이콘을 가진 Studio 실행 파일.
@param KeepExisting 갱신을 마칠 때까지 기존 등록을 유지한다.
@param ApplicationName Windows 제거 목록에서 공개 설치와 시제품을 구분한다.
@param Quiet 확인 창 없이 동일한 제거 범위를 적용한다.
#>
[CmdletBinding(DefaultParameterSetName = 'Remove')]
param
(
    [Parameter(Mandatory, ParameterSetName = 'Register')][string]$DisplayVersion,
    [Parameter(Mandatory, ParameterSetName = 'Register')][string]$StudioExe,
    [Parameter(ParameterSetName = 'Register')][switch]$KeepExisting,
    [Parameter(ParameterSetName = 'Register')][ValidateSet('TraceWave Studio', 'TraceWave Studio Preview')][string]$ApplicationName = 'TraceWave Studio',
    [Parameter(ParameterSetName = 'Remove')][switch]$Quiet
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$prefix = $root.TrimEnd('\') + '\'
$pathComparison = [StringComparison]::OrdinalIgnoreCase
$versionsPrefix = (Join-Path $root 'Versions') + '\'
$registrationBase = 'Software\Microsoft\Windows\CurrentVersion\Uninstall'
$sha = [Security.Cryptography.SHA256]::Create()
try
{
    $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($prefix.ToUpperInvariant()))).Replace('-', '')
}
finally
{
    $sha.Dispose()
}
$entryName = "TraceWaveStudio.$hash"
$entry = "HKCU:\$registrationBase\$entryName"
$uninstaller = Join-Path $root 'TraceWaveUninstall.ps1'

function Assert-PlainPath
{
    <# @brief 제거 대상을 다른 폴더로 연결하는 재분석점을 거부한다. #>
    param([string]$Path)
    if (([IO.File]::GetAttributes($Path) -band [IO.FileAttributes]::ReparsePoint) -ne 0)
    {
        throw "연결된 경로에서 설치 또는 제거를 진행할 수 없습니다. $Path"
    }
}

function Show-RemovalMessage
{
    <# @brief Windows에서 실행한 사용자와 자동 실행에 같은 결과를 알린다. #>
    param([string]$Message, [switch]$Failed)
    if ($Quiet)
    {
        if ($Failed)
        {
            [Console]::Error.WriteLine($Message)
        }
        else
        {
            Write-Host $Message
        }
        return
    }

    Add-Type -AssemblyName System.Windows.Forms
    $icon = if ($Failed) { 'Warning' } else { 'Information' }
    [void][Windows.Forms.MessageBox]::Show($Message, 'TraceWave Studio 제거', 'OK', $icon)
}

function Assert-InstallationPath
{
    <# @brief 실제 설치 경로에서 실행됐는지 확인한다. #>
    if ($root -eq [IO.Path]::GetPathRoot($root) -or $script:PSCommandPath -ne $uninstaller)
    {
        throw 'TraceWave Studio 설치 폴더 안에서 실행해야 합니다.'
    }
    for ($directory = [IO.DirectoryInfo]::new($root); $null -ne $directory; $directory = $directory.Parent)
    {
        Assert-PlainPath $directory.FullName
    }
    Assert-PlainPath $uninstaller
}

function Remove-InstalledDirectory
{
    <# @brief 검증한 설치 폴더 아래에서 연결을 따라가지 않고 파일을 지운다. #>
    param([string]$Path)
    if (([IO.File]::GetAttributes($Path) -band [IO.FileAttributes]::ReparsePoint) -eq 0)
    {
        foreach ($child in [IO.Directory]::EnumerateFileSystemEntries($Path))
        {
            if (([IO.File]::GetAttributes($child) -band [IO.FileAttributes]::Directory) -ne 0)
            {
                Remove-InstalledDirectory $child
            }
            else
            {
                [IO.File]::Delete($child)
            }
        }
    }
    [IO.Directory]::Delete($Path, $false)
}

if ($PSCmdlet.ParameterSetName -eq 'Register')
{
    Assert-InstallationPath
    if ($KeepExisting -and (Test-Path -LiteralPath $entry))
    {
        return
    }
    $windowsPowerShell = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0\powershell.exe'
    $command = '"{0}" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass' -f $windowsPowerShell
    $values = @{
        DisplayName = $ApplicationName
        DisplayVersion = $DisplayVersion
        Publisher = 'EIDOSDATA'
        DisplayIcon = "$StudioExe,0"
        InstallLocation = $root
        UninstallString = "$command -WindowStyle Hidden -File `"$uninstaller`""
        QuietUninstallString = "$command -File `"$uninstaller`" -Quiet"
    }
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("$registrationBase\$entryName")
    try
    {
        foreach ($value in $values.GetEnumerator())
        {
            $key.SetValue($value.Key, $value.Value, 'String')
        }
        $key.SetValue('NoModify', 1, 'DWord')
        $key.SetValue('NoRepair', 1, 'DWord')
    }
    finally
    {
        $key.Dispose()
    }
    return
}

$lock = $null
try
{
    Assert-InstallationPath
    if ((Get-ItemProperty -LiteralPath $entry -Name InstallLocation).InstallLocation -ne $root)
    {
        throw 'Windows에 등록된 TraceWave Studio 설치 위치가 다릅니다.'
    }
    if (-not $Quiet)
    {
        Add-Type -AssemblyName System.Windows.Forms
        $prompt = "TraceWave Studio와 전용 런타임 및 설치 캐시를 제거할까요?`r`n`r`nWorkspace의 프로젝트와 해석 결과는 보존합니다."
        $answer = [Windows.Forms.MessageBox]::Show($prompt, 'TraceWave Studio 제거', 'OKCancel', 'Question', 'Button2')
        if ($answer -ne 'OK')
        {
            exit 0
        }
    }

    $lockPath = Join-Path $root 'Setup.lock'
    if (Test-Path -LiteralPath $lockPath)
    {
        Assert-PlainPath $lockPath
    }
    try
    {
        $lock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'Delete')
    }
    catch
    {
        $cause = $_.Exception.GetBaseException()
        if ($cause -is [IO.IOException] -and ($cause.HResult -band 65535) -in @(32, 33))
        {
            throw '설치 또는 제거가 진행 중입니다. 창을 닫은 뒤 다시 시도하세요.'
        }
        throw
    }

    $targets = @('Versions', 'Python31210', 'Cache' | ForEach-Object { Join-Path $root $_ })
    foreach ($target in $targets)
    {
        if (Test-Path -LiteralPath $target)
        {
            $resolved = (Resolve-Path -LiteralPath $target).ProviderPath
            if ([IO.Path]::GetDirectoryName($resolved) -ne $root)
            {
                throw "설치 폴더 바로 아래에 있는 경로만 제거할 수 있습니다. $target"
            }
            Assert-PlainPath $resolved
        }
    }
    $active = @(Get-Process -Name tracewave_gui, tracewave_shell_prototype, python, pythonw, openEMS -ErrorAction SilentlyContinue | Where-Object {
        $path = $_.Path
        $path -and @($targets | Where-Object {
            $path.StartsWith($_ + '\', $pathComparison)
        }).Count
    })
    if ($active.Count -gt 0)
    {
        throw 'TraceWave Studio와 실행 중인 해석을 닫은 뒤 제거를 다시 시도하세요.'
    }

    foreach ($target in $targets)
    {
        if ([IO.Directory]::Exists($target))
        {
            Remove-InstalledDirectory $target
        }
    }
    foreach ($name in @('TraceWave Studio.lnk', 'TraceWave Studio Preview.lnk'))
    {
        $shortcutPath = Join-Path ([Environment]::GetFolderPath('Programs')) $name
        if (Test-Path -LiteralPath $shortcutPath -PathType Leaf)
        {
            $shell = New-Object -ComObject WScript.Shell
            $shortcut = $shell.CreateShortcut($shortcutPath)
            if ($shortcut.TargetPath.StartsWith($versionsPrefix, $pathComparison))
            {
                [IO.File]::Delete($shortcutPath)
            }
        }
    }
    foreach ($name in @('Setup-status.json', 'Setup.log'))
    {
        [IO.File]::Delete((Join-Path $root $name))
    }
    [IO.File]::Delete($lockPath)
    [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKey("$registrationBase\$entryName")
    [IO.File]::Delete($uninstaller)
}
catch
{
    Show-RemovalMessage ("제거를 완료하지 못했습니다. " + $_.Exception.Message) -Failed
    exit 1
}
finally
{
    if ($null -ne $lock)
    {
        $lock.Dispose()
    }
}
Show-RemovalMessage "TraceWave Studio를 제거했습니다.`r`n작업 데이터 보관 위치: $(Join-Path $root 'Workspace')"
