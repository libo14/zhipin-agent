from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path


APP_NAME = "ZhipinAgent"
PAYLOAD_NAME = "ZhipinAgentPayload.zip"


def bundled_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def desktop_path() -> Path:
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        desktop = result.stdout.strip()
        if result.returncode == 0 and desktop:
            return Path(desktop)
    except Exception:
        pass
    return Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))


def ps_quote(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def stop_running_app() -> None:
    subprocess.run(
        ["taskkill", "/IM", "ZhipinAgent.exe", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def create_shortcut(install_dir: Path) -> None:
    shortcut = desktop_path() / "ZhipinAgent.lnk"
    target = install_dir / "ZhipinAgent.exe"
    icon = install_dir / "ZhipinAgent.ico"
    icon_location = icon if icon.exists() else target
    ps = f"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut({ps_quote(shortcut)})
$shortcut.TargetPath = {ps_quote(target)}
$shortcut.WorkingDirectory = {ps_quote(install_dir)}
$shortcut.IconLocation = {ps_quote(icon_location)}
$shortcut.Description = 'ZhipinAgent recruiting workbench'
$shortcut.Save()
"""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=False,
    )


def install() -> Path:
    payload = bundled_path(PAYLOAD_NAME)
    if not payload.exists():
        raise FileNotFoundError(f"Installer payload not found: {payload}")

    install_dir = desktop_path() / APP_NAME
    temp_dir = Path(os.environ.get("TEMP", str(desktop_path()))) / f"ZhipinAgentInstall_{int(time.time())}"

    stop_running_app()
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(payload, "r") as archive:
        archive.extractall(temp_dir)

    install_dir.mkdir(parents=True, exist_ok=True)
    for item in temp_dir.iterdir():
        target = install_dir / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    shutil.rmtree(temp_dir, ignore_errors=True)
    create_shortcut(install_dir)
    return install_dir


def main() -> None:
    quiet = "--quiet" in sys.argv
    no_start = "--no-start" in sys.argv
    try:
        install_dir = install()
        app = install_dir / "ZhipinAgent.exe"
        print(f"Installed ZhipinAgent to: {install_dir}")
        print("A desktop shortcut named ZhipinAgent.lnk has been created.")
        if app.exists() and not no_start:
            subprocess.Popen([str(app)], cwd=str(install_dir))
        if not quiet:
            input("Installation finished. Press Enter to close this window...")
    except Exception as exc:
        print(f"Installation failed: {exc}")
        if not quiet:
            input("Press Enter to close this window...")
        raise


if __name__ == "__main__":
    main()
