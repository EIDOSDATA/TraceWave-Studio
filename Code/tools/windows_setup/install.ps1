<#
@file
@brief 봉인한 Windows 앱과 고정 의존성을 사용자 단위로 설치한다.
@param Bundle Setup.exe에서 꺼낸 후보 ZIP.
@param Identity 후보 ZIP의 고정 SHA-256.
@param DisplayVersion Windows에 등록할 배포 버전.
@param InstallRoot 앱, 전용 런타임과 작업 영역의 설치 경로.
@param WithoutSimulation Windows 기능만 준비한다.
@param WithWsl 기존 WSL2 해석 환경을 재현할 때 선택한다.
@param NoShortcut 검증 시 시작 메뉴 등록을 생략한다.
@param NoLaunch 검증 시 설치 후 앱 실행을 생략한다.
#>
[CmdletBinding()]
param
(
    [Parameter(Mandatory)][string]$Bundle,
    [Parameter(Mandatory)][string]$Identity,
    [Parameter(Mandatory)][string]$DisplayVersion,
    [string]$InstallRoot = (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'TraceWaveStudio'),
    [switch]$WithoutSimulation,
    [switch]$WithWsl,
    [switch]$NoShortcut,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$PSNativeCommandUseErrorActionPreference = $false
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Test-FileHash
{
    <# @brief 파일 내용을 고정 SHA-256과 대조한다. #>
    param([string]$Path, [string]$Expected)
    return (Test-Path -LiteralPath $Path -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Expected)
}

function Get-VerifiedDownload
{
    <# @brief 공식 자산을 받은 뒤 해시가 맞을 때만 재사용 가능한 위치에 게시한다. #>
    param([string]$Url, [string]$Name, [string]$Expected)
    $destination = Join-Path $cache $Name
    if (Test-Path -LiteralPath $destination)
    {
        if (-not (Test-FileHash $destination $Expected))
        {
            throw "설치 캐시의 SHA-256이 다릅니다. $destination"
        }
        return $destination
    }
    $temporary = $destination + '.' + [Guid]::NewGuid().ToString('N') + '.part'
    try
    {
        Write-Host "다운로드 중  $Name"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $temporary -TimeoutSec 600
        if (-not (Test-FileHash $temporary $Expected))
        {
            throw "다운로드한 파일의 SHA-256이 다릅니다. $Name"
        }
        [IO.File]::Move($temporary, $destination)
        return $destination
    }
    finally
    {
        [IO.File]::Delete($temporary)
    }
}

function Expand-Once
{
    <# @brief 압축 해제를 끝낸 새 폴더만 설치 대상에 연결한다. #>
    param([string]$Archive, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Destination))
    {
        $stage = $Destination + '.new-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
        [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $stage)
        [IO.Directory]::Move($stage, $Destination)
    }
}

function Invoke-Checked
{
    <# @brief 실패한 하위 프로그램의 종료값을 사용자와 로그에 남긴다. #>
    param([string]$Program, [string[]]$Arguments, [string]$Step)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0)
    {
        throw "$Step 단계가 실패했습니다. 종료 코드 $LASTEXITCODE"
    }
}

function Install-CompilerRuntime
{
    <# @brief 고정 WinLibs 자산에서 필요한 DLL만 추출하고 개별 해시를 검사한다. #>
    param($Files, [string]$Bin)
    $pending = @($Files.PSObject.Properties | Where-Object {
        -not (Test-FileHash (Join-Path $Bin $_.Name) $_.Value)
    })
    if (-not $pending.Count)
    {
        return
    }

    $url = 'https://github.com/brechtsanders/winlibs_mingw/releases/download/16.1.0mcf-14.0.0-ucrt-r1/winlibs-x86_64-mcf-seh-gcc-16.1.0-mingw-w64ucrt-14.0.0-r1.7z'
    $archive = Get-VerifiedDownload $url 'winlibs-16.1.0-x64.7z' '4d517fbf84e921497ca1bd4e605c4c14cb96ae2a402cfd6d197853c701c83b5f'
    $temporary = Join-Path $cache ('winlibs-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    $entries = @($pending | ForEach-Object { 'mingw64/bin/' + $_.Name })
    $tar = Join-Path ([Environment]::SystemDirectory) 'tar.exe'
    Invoke-Checked $tar (@('-xf', $archive, '-C', $temporary) + $entries) 'WinLibs 압축 해제'
    foreach ($file in $pending)
    {
        if (-not (Test-FileHash (Join-Path $temporary ('mingw64/bin/' + $file.Name)) $file.Value))
        {
            throw "WinLibs DLL의 SHA-256이 다릅니다. $($file.Name)"
        }
    }
    foreach ($file in $pending)
    {
        $source = Join-Path $temporary ('mingw64/bin/' + $file.Name)
        Copy-Item -LiteralPath $source -Destination (Join-Path $Bin $file.Name) -Force
    }
}

function Get-StudioArguments
{
    <# @brief 같은 작업 영역과 검증된 worker를 바로 가기와 실행에 연결한다. #>
    param([bool]$UseWsl)
    $arguments = @(
        '--python', $service, '--source', (Join-Path $codeRoot 'src'),
        '--workspace', $workspace, '--cad-python', (Join-Path $codeRoot '.venv-cad/Scripts/python.exe'),
        '--exchange-python', (Join-Path $codeRoot '.venv-exchange/Scripts/python.exe')
    )
    if ($UseWsl)
    {
        $arguments += '--openems-wsl'
    }
    return ($arguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
}

function Register-StudioShortcut
{
    <# @brief 설치를 다시 실행해도 사용자 시작 메뉴의 같은 바로 가기에서 앱을 연다. #>
    param([bool]$UseWsl, [switch]$NewOnly)
    if (-not $NoShortcut)
    {
        $folder = [Environment]::GetFolderPath('Programs')
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        $link = Join-Path $folder 'TraceWave Studio.lnk'
        if ($NewOnly -and (Test-Path -LiteralPath $link))
        {
            return
        }
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($link)
        $shortcut.TargetPath = $gui
        $shortcut.IconLocation = "$gui,0"
        $shortcut.Arguments = Get-StudioArguments $UseWsl
        $shortcut.WorkingDirectory = $codeRoot
        $shortcut.Save()
    }
}

function Register-StudioRemoval
{
    <# @brief 현재 사용자에게 Windows 표준 제거 경로를 연결한다. #>
    param([switch]$KeepExisting)
    $script = Join-Path $root 'TraceWaveUninstall.ps1'
    if ((Test-Path -LiteralPath $script) -and
        ([IO.File]::GetAttributes($script) -band [IO.FileAttributes]::ReparsePoint))
    {
        throw "제거 스크립트 위치가 연결된 경로입니다. $script"
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $script -Force
    & $script -DisplayVersion $DisplayVersion -StudioExe $gui -KeepExisting:$KeepExisting
}

$windowsVersion = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
if ($WithoutSimulation -and $WithWsl)
{
    throw '해석 생략과 WSL2 선택을 함께 지정할 수 없습니다.'
}
if (-not [Environment]::Is64BitProcess -or [int]$windowsVersion.CurrentBuildNumber -lt 22000)
{
    throw 'Windows 11 x64에서 Setup.exe를 실행하세요.'
}
$root = [IO.Path]::GetFullPath($InstallRoot)
$cache = Join-Path $root 'Cache'
$versions = Join-Path $root 'Versions'
$workspace = Join-Path $root 'Workspace'
New-Item -ItemType Directory -Force -Path $root, $cache, $versions | Out-Null
try
{
    $lock = [IO.File]::Open((Join-Path $root 'Setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
}
catch
{
    $cause = $_.Exception.GetBaseException()
    if ($cause -is [IO.IOException] -and ($cause.HResult -band 65535) -in @(32, 33))
    {
        Write-Host 'TraceWave Studio 설치가 이미 진행 중입니다. 먼저 시작한 설치가 끝날 때까지 기다려 주세요.'
        exit 2
    }
    throw
}
$log = Join-Path $root 'Setup.log'
$status = [ordered]@{ revision = $null; windows_ready = $false; simulation = 'pending' }
$result = 0
Start-Transcript -LiteralPath $log -Append | Out-Null
try
{
    $bundleHash = [IO.File]::ReadAllText($Identity).Trim()
    if ($bundleHash -notmatch '^[0-9a-f]{64}$' -or -not (Test-FileHash $Bundle $bundleHash))
    {
        throw 'Setup.exe 내부 후보 ZIP의 SHA-256이 다릅니다.'
    }
    $clear = [IO.Compression.ZipFile]::OpenRead($Bundle)
    try
    {
        $reader = New-Object IO.StreamReader($clear.GetEntry('bundle-manifest.json').Open())
        try
        {
            $manifest = $reader.ReadToEnd() | ConvertFrom-Json
        }
        finally
        {
            $reader.Dispose()
        }
    }
    finally
    {
        $clear.Dispose()
    }
    if ($manifest.source_revision -notmatch '^[0-9a-f]{40}$' -or -not $manifest.external_compiler_runtime)
    {
        throw '공개 Windows 검증 후보 묶음이 필요합니다.'
    }
    $status.revision = $manifest.source_revision
    $app = Join-Path $versions $manifest.source_revision.Substring(0, 12)
    Expand-Once $Bundle $app
    $codeRoot = Join-Path $app 'Code'
    $bin = Join-Path $codeRoot 'build/windows-release/bin'
    $gui = Join-Path $bin 'tracewave_gui.exe'
    Register-StudioRemoval -KeepExisting

    Write-Host '[1/3] Windows 런타임을 준비합니다.'
    $pythonRoot = Join-Path $root 'Python31210'
    $python = Join-Path $pythonRoot 'tools/python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf))
    {
        $url = 'https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg'
        $package = Get-VerifiedDownload $url 'python.3.12.10.nupkg' '0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8'
        Expand-Once $package $pythonRoot
    }
    Invoke-Checked $python @('-I', '-c', 'import sys, ssl, struct; assert sys.version_info[:3] == (3, 12, 10) and struct.calcsize(chr(80)) == 8') 'CPython 확인'
    Invoke-Checked $python @('-E', '-s', '-X', 'utf8', (Join-Path $codeRoot 'tools/build_internal_bundle.py'), '--verify', $Bundle) '후보 내용 확인'
    Install-CompilerRuntime $manifest.external_compiler_runtime $bin

    Write-Host '[2/3] 편집, CAD, 복소 네트워크 및 출력 환경을 준비합니다.'
    $windowsPowerShell = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell/v1.0/powershell.exe'
    $shellArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File')
    Invoke-Checked $windowsPowerShell ($shellArgs + @((Join-Path $codeRoot 'tools/setup_python.ps1'), '-Python', $python)) '서비스 및 CAD 설치'
    $service = Join-Path $codeRoot '.venv/Scripts/python.exe'
    $pip = @('-I', '-m', 'pip', '--isolated', '--disable-pip-version-check')
    Invoke-Checked $service ($pip + @('install', '--only-binary=:all:', '--require-hashes', '-r',
        (Join-Path $codeRoot 'runtime_profiles/python-network-windows-x64.txt'))) '복소 네트워크 설치'
    Invoke-Checked $service ($pip + @('check')) '복소 네트워크 의존성 확인'
    Invoke-Checked $windowsPowerShell ($shellArgs + @((Join-Path $codeRoot 'tools/setup_exchange.ps1'), '-Python', $python)) '출력 worker 설치'
    Register-StudioShortcut $false -NewOnly
    $status.windows_ready = $true

    $useWsl = $false
    if ($WithoutSimulation)
    {
        $status.simulation = 'deferred'
    }
    elseif (-not $WithWsl)
    {
        Write-Host '[3/3] Windows openEMS 해석 환경을 준비합니다.'
        $builder = Join-Path $codeRoot 'tools/setup_openems_windows.py'
        Invoke-Checked $python @('-I', '-B', '-X', 'utf8', $builder, '--cache', $cache) 'Windows openEMS 설치 및 native 감사'
        $status.simulation = 'ready'
        $status.solver_platform = 'windows'
    }
    else
    {
        Write-Host '[3/3] 전용 WSL2 및 openEMS를 준비합니다. 첫 설치는 시간이 걸립니다.'
        $wsl = Join-Path ([Environment]::SystemDirectory) 'wsl.exe'
        & $wsl --version | Out-Null
        if ($LASTEXITCODE -ne 0)
        {
            Write-Host 'Windows가 WSL 기능 활성화에 필요한 관리자 승인을 요청할 수 있습니다.'
            $enableArgs = @('--install', '--no-distribution', '--web-download')
            $enable = Start-Process -FilePath $wsl -ArgumentList $enableArgs -Verb RunAs -WindowStyle Hidden -Wait -PassThru
            if ($enable.ExitCode -notin @(0, 3010))
            {
                throw "Windows WSL 설치가 실패했습니다. 종료 코드 $($enable.ExitCode)"
            }
            $status.simulation = 'restart_required'
            $result = 3010
            Write-Host 'Windows를 재부팅한 뒤 같은 Setup.exe를 다시 실행하세요.'
        }
        else
        {
            Invoke-Checked $windowsPowerShell ($shellArgs + @((Join-Path $codeRoot 'tools/setup_wsl.ps1'),
                '-Install', '-StateRoot', (Join-Path $root 'WSL'))) '전용 Ubuntu WSL2 설치'
            $builder = Join-Path $codeRoot 'tools/setup_openems_wsl.py'
            $solver = @('-I', '-X', 'utf8', $builder)
            $audit = Join-Path $codeRoot '.local/wsl/native-audit.json'
            if (-not (Test-Path -LiteralPath $audit -PathType Leaf))
            {
                Invoke-Checked $python ($solver + @('--install-dependencies')) 'openEMS 설치 및 native 감사'
            }
            else
            {
                Invoke-Checked $python ($solver + @('--audit-only')) 'openEMS native 재감사'
            }
            $useWsl = $true
            $status.simulation = 'ready'
            $status.solver_platform = 'wsl2'
        }
    }
    if ($result -eq 0)
    {
        Register-StudioRemoval
        Register-StudioShortcut $useWsl
        Write-Host 'TraceWave Studio 설치가 끝났습니다.'
        if (-not $NoLaunch)
        {
            Start-Process -FilePath $gui -ArgumentList (Get-StudioArguments $useWsl) -WorkingDirectory $codeRoot
        }
    }
}
catch
{
    $result = 1
    $status.error = $_.Exception.Message
    Write-Host $status.error -ForegroundColor Red
    Write-Host "설치 기록  $log"
}
finally
{
    $status | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'Setup-status.json') -Encoding UTF8
    Stop-Transcript | Out-Null
    $lock.Dispose()
}
exit $result
