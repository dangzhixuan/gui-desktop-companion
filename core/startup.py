import os
import sys
from pathlib import Path


STARTUP_FILENAME = "GnomonDesktopCompanion.cmd"


def get_startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("无法定位 Windows 启动目录。")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def startup_file(startup_dir=None) -> Path:
    return Path(startup_dir or get_startup_dir()) / STARTUP_FILENAME


def is_startup_enabled(startup_dir=None) -> bool:
    return startup_file(startup_dir).exists()


def set_startup_enabled(enabled: bool, *, startup_dir=None, app_path=None) -> None:
    target = startup_file(startup_dir)
    if not enabled:
        target.unlink(missing_ok=True)
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    if app_path is not None:
        command = f'start "" "{Path(app_path).resolve()}"'
    elif getattr(sys, "frozen", False):
        command = f'start "" "{Path(sys.executable).resolve()}"'
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        executable = pythonw if pythonw.exists() else Path(sys.executable)
        app = Path(__file__).resolve().parent.parent / "app.py"
        command = f'start "" "{executable}" "{app}"'

    target.write_text(
        "@echo off\r\n" + command + "\r\n",
        encoding="utf-8",
    )
