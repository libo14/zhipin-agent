param(
  [string]$InstallDir = (Join-Path ([Environment]::GetFolderPath("Desktop")) "ZhipinAgent")
)

$ErrorActionPreference = "Stop"

$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "ZhipinAgent.lnk"
$startShortcut = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\ZhipinAgent.lnk"

Remove-Item -LiteralPath $desktopShortcut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $startShortcut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Uninstalled ZhipinAgent."
