param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$PythonExe = "$ProjectRoot\..\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot

if (-not (Test-Path $PythonExe)) {
  throw "Python executable not found: $PythonExe"
}

& $PythonExe -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
  & $PythonExe -m pip install pyinstaller
}

$dist = Join-Path $ProjectRoot "dist"
$build = Join-Path $ProjectRoot "build"
$safeRoot = Join-Path $env:LOCALAPPDATA "ZhipinAgentBuild"
$safeDist = Join-Path $safeRoot "dist"
$safeBuild = Join-Path $safeRoot "build"
New-Item -ItemType Directory -Force $dist, $build, $safeDist, $safeBuild | Out-Null

$appName = "ZhipinAgent"
$staticPath = Join-Path $ProjectRoot "static"
$srcPath = Join-Path $ProjectRoot "src"
$sampleJobPath = Join-Path $ProjectRoot "data\sample_job.txt"
$sampleResumesPath = Join-Path $ProjectRoot "data\resumes"
$entryPath = Join-Path $ProjectRoot "desktop_app.py"
$iconPath = Join-Path $ProjectRoot "assets\zhipin-agent.ico"

& $PythonExe -m PyInstaller `
  --noconfirm `
  --clean `
  --name $appName `
  --onedir `
  --windowed `
  --icon $iconPath `
  --noupx `
  --distpath $safeDist `
  --workpath $safeBuild `
  --specpath $build `
  --add-data "$staticPath;static" `
  --add-data "$srcPath;src" `
  --add-data "$sampleJobPath;data" `
  --add-data "$sampleResumesPath;data\resumes" `
  --hidden-import "pypdf" `
  --hidden-import "pydantic" `
  --hidden-import "fastapi" `
  --hidden-import "starlette" `
  --hidden-import "uvicorn" `
  --hidden-import "uvicorn.logging" `
  --hidden-import "uvicorn.loops.auto" `
  --hidden-import "uvicorn.protocols.http.auto" `
  --hidden-import "uvicorn.protocols.websockets.auto" `
  --hidden-import "multipart" `
  --hidden-import "sqlite3" `
  --hidden-import "_sqlite3" `
  --hidden-import "smtplib" `
  --hidden-import "imaplib" `
  --hidden-import "email" `
  --hidden-import "email.header" `
  --hidden-import "email.message" `
  --hidden-import "ssl" `
  --hidden-import "urllib.request" `
  --hidden-import "urllib.error" `
  --hidden-import "webview" `
  --hidden-import "webview.platforms.edgechromium" `
  --hidden-import "webview.platforms.winforms" `
  --hidden-import "webview.platforms.win32" `
  --hidden-import "pythonnet" `
  --hidden-import "clr_loader" `
  $entryPath

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Remove-Item -LiteralPath (Join-Path $dist $appName) -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $safeDist $appName) -Destination $dist -Recurse -Force
Copy-Item -LiteralPath $iconPath -Destination (Join-Path $dist "$appName\ZhipinAgent.ico") -Force

Write-Host "Built app folder: $dist\$appName"
Write-Host "Run: $dist\$appName\$appName.exe"
