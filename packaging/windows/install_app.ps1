param(
  [string]$SourceDir = "$PSScriptRoot\..\..\dist\ZhipinAgent",
  [string]$InstallDir = (Join-Path ([Environment]::GetFolderPath("Desktop")) "ZhipinAgent")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $SourceDir)) {
  throw "Build output not found: $SourceDir. Run packaging\windows\build_exe.ps1 first."
}

New-Item -ItemType Directory -Force $InstallDir | Out-Null
Copy-Item -Path (Join-Path $SourceDir "*") -Destination $InstallDir -Recurse -Force

$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcut = $shell.CreateShortcut((Join-Path $desktop "ZhipinAgent.lnk"))
$shortcut.TargetPath = Join-Path $InstallDir "ZhipinAgent.exe"
$shortcut.WorkingDirectory = $InstallDir
$shortcut.IconLocation = Join-Path $InstallDir "ZhipinAgent.ico"
$shortcut.Description = "ZhipinAgent recruiting workbench"
$shortcut.Save()

$programs = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
$startShortcut = $shell.CreateShortcut((Join-Path $programs "ZhipinAgent.lnk"))
$startShortcut.TargetPath = Join-Path $InstallDir "ZhipinAgent.exe"
$startShortcut.WorkingDirectory = $InstallDir
$startShortcut.IconLocation = Join-Path $InstallDir "ZhipinAgent.ico"
$startShortcut.Description = "ZhipinAgent recruiting workbench"
$startShortcut.Save()

Write-Host "Installed ZhipinAgent to $InstallDir"
Write-Host "Desktop shortcut created: $($shortcut.FullName)"
