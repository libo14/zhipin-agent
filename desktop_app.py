from __future__ import annotations

import contextlib
import ctypes
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from web_app import RecruitmentWebHandler


def find_available_port(preferred: int = 8765) -> int:
    for port in [preferred, *range(8766, 8799)]:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No available local port found.")


def start_local_server() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    port = find_available_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), RecruitmentWebHandler)
    url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    return server, thread, url


def shutdown_server(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def run_smoke_check() -> int:
    server, _, url = start_local_server()
    try:
        with urllib.request.urlopen(f"{url}/api/sample", timeout=5) as response:
            print(f"SMOKE_STATUS={response.status}")
            return 0 if response.status == 200 else 1
    finally:
        shutdown_server(server)


def open_native_window(url: str) -> None:
    import webview

    webview.create_window(
        "智聘Agent",
        url,
        width=1180,
        height=760,
        min_size=(920, 620),
        text_select=True,
    )
    webview.start(gui="edgechromium", debug=False)


def show_startup_error(error: Exception) -> None:
    message = (
        "智聘Agent 无法打开内嵌桌面窗口。\n\n"
        "请确认 Windows 10/11 已安装 Microsoft Edge WebView2 Runtime，"
        f"然后重新启动软件。\n\n错误信息：{error}"
    )
    ctypes.windll.user32.MessageBoxW(None, message, "智聘Agent", 0x10)


def main() -> None:
    if "--smoke" in sys.argv:
        raise SystemExit(run_smoke_check())

    server, thread, url = start_local_server()
    try:
        if "--browser" in sys.argv:
            webbrowser.open(url)
            print(f"ZhipinAgent is running at {url}")
            while thread.is_alive():
                time.sleep(1)
        else:
            open_native_window(url)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        show_startup_error(exc)
    finally:
        shutdown_server(server)


if __name__ == "__main__":
    main()
