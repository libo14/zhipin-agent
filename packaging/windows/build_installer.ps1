param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$PythonExe = "$ProjectRoot\..\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

if (-not (Test-Path $PythonExe)) {
  throw "Python executable not found: $PythonExe"
}

$appDir = Join-Path $ProjectRoot "dist\ZhipinAgent"
if (-not (Test-Path $appDir)) {
  & "$PSScriptRoot\build_exe.ps1" -ProjectRoot $ProjectRoot -PythonExe $PythonExe
}

& $PythonExe -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
  & $PythonExe -m pip install pyinstaller
}

$installerWork = Join-Path $ProjectRoot "build\installer"
$outputDir = Join-Path $ProjectRoot "dist\installer"
$safeRoot = Join-Path $env:LOCALAPPDATA "ZhipinAgentInstallerBuild"
$safeBuild = Join-Path $safeRoot "build"
New-Item -ItemType Directory -Force $installerWork, $outputDir, $safeBuild | Out-Null

$zipPath = Join-Path $installerWork "ZhipinAgentPayload.zip"
Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $appDir "*") -DestinationPath $zipPath -Force

$installerScript = Join-Path $PSScriptRoot "zhipin_installer.py"
$setupExe = Join-Path $outputDir "ZhipinAgentSetup.exe"
$iconPath = Join-Path $ProjectRoot "assets\zhipin-agent.ico"
Remove-Item -LiteralPath $setupExe -Force -ErrorAction SilentlyContinue

& $PythonExe -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --console `
  --noupx `
  --icon $iconPath `
  --name "ZhipinAgentSetup" `
  --distpath $outputDir `
  --workpath $safeBuild `
  --specpath $installerWork `
  --add-data "$zipPath;." `
  $installerScript

if ($LASTEXITCODE -ne 0) {
  throw "Installer build failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $setupExe)) {
  throw "Installer was not created: $setupExe"
}

Write-Host "Installer created: $setupExe"
