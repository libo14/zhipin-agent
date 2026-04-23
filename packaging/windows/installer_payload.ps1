param(
  [string]$ZipPath = "$PSScriptRoot\ZhipinAgentPayload.zip",
  [string]$InstallDir = (Join-Path ([Environment]::GetFolderPath("Desktop")) "ZhipinAgent")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ZipPath)) {
  throw "Payload zip not found: $ZipPath"
}

$temp = Join-Path $env:TEMP ("ZhipinAgentInstall_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $temp | Out-Null
Expand-Archive -Path $ZipPath -DestinationPath $temp -Force

New-Item -ItemType Directory -Force $InstallDir | Out-Null
Copy-Item -Path (Join-Path $temp "*") -Destination $InstallDir -Recurse -Force

$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcut = $shell.CreateShortcut((Join-Path $desktop "ZhipinAgent.lnk"))
$shortcut.TargetPath = Join-Path $InstallDir "ZhipinAgent.exe"
$shortcut.WorkingDirectory = $InstallDir
$shortcut.Description = "ZhipinAgent recruiting workbench"
$shortcut.Save()

$programs = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
$startShortcut = $shell.CreateShortcut((Join-Path $programs "ZhipinAgent.lnk"))
$startShortcut.TargetPath = Join-Path $InstallDir "ZhipinAgent.exe"
$startShortcut.WorkingDirectory = $InstallDir
$startShortcut.Description = "ZhipinAgent recruiting workbench"
$startShortcut.Save()

Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
Start-Process -FilePath (Join-Path $InstallDir "ZhipinAgent.exe")
