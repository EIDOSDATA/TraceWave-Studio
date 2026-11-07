<#
@brief 고정된 네이티브 의존성의 SHA256을 검사한 뒤 Windows GUI를 빌드한다.
@param SkipBuild 의존성 준비와 CMake 설정까지만 실행한다.
@param Jobs 동시에 실행할 빌드 작업 수다.
#>
[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [ValidateRange(1, 64)]
    [int]$Jobs = 4
)

$ErrorActionPreference = 'Stop'
$codeRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$profilePath = Join-Path $codeRoot 'runtime_profiles/native-windows-x64.json'
$profile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
if ($env:OS -ne 'Windows_NT')
{
    throw 'This development profile requires Windows.'
}
foreach ($name in @('cmake', 'ninja', 'g++', 'gcc', 'tar'))
{
    if (-not (Get-Command $name -ErrorAction SilentlyContinue))
    {
        throw "Missing development tool: $name. See ui/wxwidgets/README.md."
    }
}
foreach ($dependency in $profile.dependencies)
{
    $destination = Join-Path $codeRoot $dependency.download_path
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    if (-not (Test-Path -LiteralPath $destination -PathType Leaf))
    {
        Invoke-WebRequest -Uri $dependency.url -OutFile $destination
    }
    $actualHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $dependency.sha256)
    {
        throw "Dependency SHA256 mismatch: $($dependency.name). Inspect the local file before retrying."
    }
    if ($dependency.name -eq 'wxWidgets')
    {
        $sourceDirectory = Join-Path $codeRoot $dependency.source_path
        if (-not (Test-Path -LiteralPath (Join-Path $sourceDirectory 'CMakeLists.txt')))
        {
            & tar -xjf $destination -C (Split-Path -Parent $sourceDirectory)
            if ($LASTEXITCODE -ne 0)
            {
                throw 'wxWidgets source extraction failed.'
            }
        }
    }
}

Push-Location -LiteralPath $codeRoot
try
{
    & cmake --preset windows-release
    if ($LASTEXITCODE -ne 0)
    {
        throw 'CMake configuration failed.'
    }
    if (-not $SkipBuild)
    {
        & cmake --build --preset windows-release --parallel $Jobs
        if ($LASTEXITCODE -ne 0)
        {
            throw 'Native GUI build failed.'
        }
        $compilerDirectory = Split-Path -Parent (Get-Command g++).Source
        $outputDirectory = Join-Path $codeRoot 'build/windows-release/bin'
        foreach ($runtime in @('libgcc_s_seh-1.dll', 'libstdc++-6.dll', 'libmcfgthread-2.dll', 'libwinpthread-1.dll'))
        {
            $runtimePath = Join-Path $compilerDirectory $runtime
            if (Test-Path -LiteralPath $runtimePath -PathType Leaf)
            {
                Copy-Item -LiteralPath $runtimePath -Destination $outputDirectory -Force
            }
        }
        Write-Output "GUI built: $(Join-Path $outputDirectory 'tracewave_gui.exe')"
    }
}
finally
{
    Pop-Location
}
