"""FRAME AI Windows launcher.

Starts the FastAPI backend and the traced Next.js server from a packaged
directory, keeps all mutable state in a per-user data directory, and opens the
browser once both servers are ready.

Nothing in this module ever prints the API token or provider keys.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "FRAME AI"
DEFAULT_API_PORT = 8000
DEFAULT_WEB_PORT = 3000
STARTUP_TIMEOUT_SECONDS = 90.0
SKY_MODEL_NAME = "skyseg.onnx"
SKY_MODEL_BYTES = 175_997_079
SKY_MODEL_SHA256 = "ab9c34c64c3d821220a2886a4a06da4642ffa14d5b30e8d5339056a089aa1d39"
_LOG_PATH: Path | None = None


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    # Running the launcher from source (packaging smoke tests).
    return Path(__file__).resolve().parents[1] / "packaging" / "out"


def _default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME / "data"
        return Path.home() / "AppData" / "Roaming" / APP_NAME / "data"
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "frame-ai" / "data"
    return Path.home() / ".local" / "share" / "frame-ai" / "data"


def _log_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME / "logs"
        return Path.home() / "AppData" / "Roaming" / APP_NAME / "logs"
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "frame-ai" / "logs"
    return Path.home() / ".local" / "state" / "frame-ai" / "logs"


def _redirect_streams() -> None:
    """A windowed build has no stdio; keep all logs in a file instead."""

    global _LOG_PATH
    if not getattr(sys, "frozen", False):
        return
    log_dir = _log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "frame-ai.log"
        if log_path.is_file() and log_path.stat().st_size > 5 * 1024 * 1024:
            rotated = log_dir / "frame-ai.log.1"
            rotated.unlink(missing_ok=True)
            log_path.replace(rotated)
        stream = log_path.open("a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
        _LOG_PATH = log_path
    except OSError:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        sys.stderr = sys.stdout


def _log(message: str) -> None:
    stream = sys.stdout or sys.__stdout__
    if stream is not None:
        print(f"[frame-ai] {message}", file=stream, flush=True)


def _port_free(port: int) -> bool:
    # Windows can have an IPv6-only listener on the same port number, and a
    # bind probe may still succeed through socket reuse. An active loopback
    # connection is the reliable signal that something already serves the port.
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            probe = socket.socket(family, socket.SOCK_STREAM)
        except OSError:
            continue
        probe.settimeout(0.25)
        try:
            if probe.connect_ex((host, port)) == 0:
                return False
        except OSError:
            pass
        finally:
            probe.close()
    return True


def _pick_port(preferred: int) -> int:
    if _port_free(preferred):
        return preferred
    for candidate in range(preferred + 1, preferred + 40):
        if _port_free(candidate):
            return candidate
    raise SystemExit(f"no free port near {preferred}")


def _find_server_js(web_root: Path) -> Path:
    direct = web_root / "server.js"
    if direct.is_file():
        return direct
    candidates = sorted(web_root.glob("*/server.js")) + sorted(web_root.glob("*/*/server.js"))
    if not candidates:
        raise SystemExit(f"Next.js server bundle not found under {web_root}")
    return candidates[0]


def _ensure_layout(data_dir: Path) -> None:
    for relative in (
        "",
        "originals",
        "masks",
        "generated",
        "generative/results",
        "generative/tmp",
        "tmp/previews",
        "tmp/exports",
        "mattes",
        "models/semantic",
    ):
        (data_dir / relative).mkdir(parents=True, exist_ok=True)


def _ensure_bundled_sky_model(data_dir: Path) -> None:
    """Install the bundled sky model once; the registry verifies its hash.

    The registry re-validates every startup, so an existing file with the
    expected size is left alone and no 168 MB re-hash runs on every launch.
    """

    source = _resource_root() / "semantic" / SKY_MODEL_NAME
    if not source.is_file():
        return
    target = data_dir / "models" / "semantic" / SKY_MODEL_NAME
    if target.is_file() and target.stat().st_size == SKY_MODEL_BYTES:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    digest = hashlib.sha256()
    written = 0
    try:
        with source.open("rb") as src, temporary.open("wb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
                digest.update(chunk)
                written += len(chunk)
        if written != SKY_MODEL_BYTES or digest.hexdigest() != SKY_MODEL_SHA256:
            temporary.unlink(missing_ok=True)
            _log("bundled sky model failed verification; sky masks stay disabled")
            return
        os.replace(temporary, target)
        _log("bundled sky model installed into the data directory")
    except OSError as error:
        temporary.unlink(missing_ok=True)
        _log(f"bundled sky model could not be installed: {error.__class__.__name__}")


def _wait_for(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.4)
    return False


def _hide_console() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetConsoleWindow()
        if handle:
            ctypes.windll.user32.ShowWindow(handle, 0)
    except Exception:
        pass


def _tray_image():
    try:
        from PIL import Image

        for candidate in (
            _resource_root() / "assets" / "frame-ai.png",
            Path(__file__).resolve().parents[1] / "packaging" / "assets" / "frame-ai.png",
        ):
            if candidate.is_file():
                with Image.open(candidate) as image:
                    return image.convert("RGBA").copy()
    except Exception:
        pass

    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (2, 2, 61, 61), radius=14, fill=(8, 9, 10, 255), outline=(230, 180, 80, 255), width=3
    )
    draw.ellipse((17, 17, 46, 46), outline=(240, 240, 240, 255), width=4)
    return image


def _run_tray(
    url: str,
    server,
    ready: threading.Event,
    window_ref: dict[str, object] | None = None,
    log_dir: Path | None = None,
) -> None:
    try:
        import pystray
    except Exception:
        _log("tray unavailable; keeping the console window")
        return

    def current_window():
        return (window_ref or {}).get("window")

    def open_app(icon=None, item=None) -> None:
        window = current_window()
        if window is not None:
            window.restore()
            window.show()
        else:
            webbrowser.open(url)

    def open_logs(icon=None, item=None) -> None:
        target = log_dir or _log_dir()
        try:
            target.mkdir(parents=True, exist_ok=True)
            os.startfile(str(target))
        except (OSError, AttributeError):
            webbrowser.open(target.as_uri())

    def quit_app(icon=None, item=None) -> None:
        server.should_exit = True
        if window_ref is not None:
            window_ref["quitting"] = True
        window = current_window()
        if window is not None:
            window.destroy()
        if icon is not None:
            icon.stop()

    try:
        icon = pystray.Icon(
            "frame-ai",
            _tray_image(),
            "FRAME AI",
            menu=pystray.Menu(
                pystray.MenuItem("打开界面", open_app, default=True),
                pystray.MenuItem("打开日志目录", open_logs),
                pystray.MenuItem("退出", quit_app),
            ),
        )

        def setup(tray_icon) -> None:
            tray_icon.visible = True
            ready.set()
            _log("tray icon ready")

        icon.run(setup=setup)
    except Exception as error:
        _log(f"tray failed: {error.__class__.__name__}")


def _hide_console_when_ready(ready: threading.Event, url: str) -> None:
    if not ready.wait(15):
        return
    if _wait_for(url, STARTUP_TIMEOUT_SECONDS):
        _hide_console()


def _initial_window_size() -> tuple[int, int]:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            work = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0):
                width = work.right - work.left
                height = work.bottom - work.top
                return (
                    max(960, min(1440, int(width * 0.92))),
                    max(640, min(900, int(height * 0.92))),
                )
        except Exception:
            pass
    return (1280, 820)


def _run_desktop_window(
    url: str,
    tray_ready: threading.Event,
    window_ref: dict[str, object],
    hide_console: bool,
) -> None:
    import webview

    width, height = _initial_window_size()
    window = webview.create_window(
        APP_NAME,
        url,
        width=width,
        height=height,
        min_size=(min(1024, width), min(700, height)),
        background_color="#f2f4f1",
        confirm_close=False,
    )
    if window is None:
        raise RuntimeError("webview_window_unavailable")
    window_ref["window"] = window

    def on_closing():
        if window_ref.get("quitting"):
            return True
        # With a tray icon, closing hides the window; quit from the tray menu.
        if tray_ready.is_set():
            window.hide()
            return False
        return True

    def on_shown() -> None:
        if hide_console and tray_ready.wait(10):
            _hide_console()

    window.events.closing += on_closing
    window.events.shown += on_shown
    webview.start(gui="edgechromium")


def _start_node(web_root: Path, web_port: int, env: dict[str, str]) -> subprocess.Popen[bytes]:
    node = Path(getattr(sys, "_MEIPASS", _resource_root())) / "node" / "node.exe"
    if not node.is_file():
        node = Path("node.exe")
    command = [str(node), str(_find_server_js(web_root))]
    _log(f"starting web server on http://127.0.0.1:{web_port}")
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    return subprocess.Popen(
        command,
        cwd=str(_find_server_js(web_root).parent),
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )


def _open_browser_later(url: str) -> None:
    def worker() -> None:
        if _wait_for(url, STARTUP_TIMEOUT_SECONDS):
            webbrowser.open(url)

    threading.Thread(target=worker, daemon=True).start()


def _data_summary(data_dir: Path) -> tuple[bool, int]:
    settings_file = data_dir / "provider-settings.json"
    database = data_dir / "frame.db"
    images = 0
    if database.is_file():
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
                row = connection.execute("SELECT COUNT(*) FROM image_asset").fetchone()
                images = int(row[0]) if row else 0
        except sqlite3.Error:
            images = -1
    return settings_file.is_file(), images


def main(argv: list[str] | None = None) -> int:
    _redirect_streams()
    parser = argparse.ArgumentParser(description=f"{APP_NAME} desktop launcher")
    parser.add_argument("--data-dir", type=Path, help="override the per-user data directory")
    parser.add_argument("--api-port", type=int, default=int(os.environ.get("FRAME_API_PORT", DEFAULT_API_PORT)))
    parser.add_argument("--web-port", type=int, default=int(os.environ.get("FRAME_WEB_PORT", DEFAULT_WEB_PORT)))
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="use the system browser instead of the native desktop window",
    )
    parser.add_argument("--no-tray", action="store_true", help="skip the system tray icon")
    parser.add_argument(
        "--show-console",
        action="store_true",
        help="keep the console window visible after startup",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="start both servers, probe them, print state and exit",
    )
    args = parser.parse_args(argv)

    data_dir = args.data_dir
    if data_dir is None:
        configured = os.environ.get("FRAME_DATA_DIR", "").strip()
        data_dir = Path(configured) if configured else _default_data_dir()
    data_dir = data_dir.expanduser().resolve()
    _ensure_layout(data_dir)
    _ensure_bundled_sky_model(data_dir)

    web_port = _pick_port(args.web_port)
    api_port = _pick_port(args.api_port)
    if api_port != args.api_port:
        _log(f"API port {args.api_port} is busy; using {api_port}")
    if web_port != args.web_port:
        _log(f"web port {args.web_port} is busy; using {web_port}")

    env = {
        **os.environ,
        "FRAME_DATA_DIR": str(data_dir),
        "FRAME_PACKAGED": "1",
        "FRAME_ENVIRONMENT": "production",
        "FRAME_ALLOWED_ORIGINS": (
            f"http://127.0.0.1:{web_port},http://localhost:{web_port}"
        ),
        "FRAME_ALLOWED_HOSTS": "127.0.0.1,localhost,::1",
        "NEXT_TELEMETRY_DISABLED": "1",
        "NODE_ENV": "production",
        "HOSTNAME": "127.0.0.1",
        "PORT": str(web_port),
        "API_INTERNAL_URL": f"http://127.0.0.1:{api_port}",
    }
    # Both semantic models ship with the desktop package; expose the controls
    # unless the user explicitly disabled them.
    env.setdefault("FRAME_FEATURE_SEMANTIC_MASKS", "1")
    os.environ.update(env)
    if not getattr(sys, "frozen", False):
        source_api = Path(__file__).resolve().parents[1] / "services" / "api"
        if str(source_api) not in sys.path:
            sys.path.insert(0, str(source_api))
    app_root = _resource_root() / "api"
    if (app_root / "app").is_dir() and str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    _log(f"data directory: {data_dir}")
    _log("provider keys are not bundled; enter them in Settings or the onboarding flow")

    web_root = _resource_root() / "web"
    node_process = _start_node(web_root, web_port, env)
    uvicorn_server = None

    try:
        import uvicorn

        from app.main import app as api_app

        config = uvicorn.Config(
            api_app,
            host="127.0.0.1",
            port=api_port,
            log_level="info",
            access_log=False,
            log_config=None,
        )
        uvicorn_server = uvicorn.Server(config)

        if args.smoke_test:
            thread = threading.Thread(target=uvicorn_server.run, daemon=True)
            thread.start()
            api_ok = _wait_for(f"http://127.0.0.1:{api_port}/api/v1/health", STARTUP_TIMEOUT_SECONDS)
            web_ok = _wait_for(f"http://127.0.0.1:{web_port}/", STARTUP_TIMEOUT_SECONDS)
            has_settings, images = _data_summary(data_dir)
            _log(f"smoke: api={api_ok} web={web_ok} provider_settings={has_settings} images={images}")
            uvicorn_server.should_exit = True
            thread.join(timeout=15)
            return 0 if api_ok and web_ok and images == 0 and not has_settings else 1

        url = f"http://127.0.0.1:{web_port}/"
        health_url = f"http://127.0.0.1:{api_port}/api/v1/health"
        tray_ready = threading.Event()
        window_ref: dict[str, object] = {}
        if not args.no_tray:
            threading.Thread(
                target=_run_tray,
                args=(url, uvicorn_server, tray_ready, window_ref, _log_dir()),
                daemon=True,
            ).start()

        if args.browser:
            if not args.no_tray and not args.show_console:
                threading.Thread(
                    target=_hide_console_when_ready,
                    args=(tray_ready, url),
                    daemon=True,
                ).start()
            if not args.no_browser:
                _open_browser_later(url)
            _log(f"open {url} (use the tray icon to exit)")
            uvicorn_server.run()
            return 0

        server_thread = threading.Thread(target=uvicorn_server.run, daemon=True)
        server_thread.start()
        if not _wait_for(health_url, STARTUP_TIMEOUT_SECONDS) or not _wait_for(
            url, STARTUP_TIMEOUT_SECONDS
        ):
            _log("startup failed; see the log above")
            uvicorn_server.should_exit = True
            server_thread.join(timeout=15)
            return 1

        _log("opening desktop window")
        try:
            _run_desktop_window(
                url,
                tray_ready,
                window_ref,
                hide_console=not args.show_console and not args.no_tray,
            )
        except Exception as error:
            _log(f"desktop window failed ({error.__class__.__name__}); falling back to browser")
            window_ref.clear()
            if not args.no_browser:
                webbrowser.open(url)
            while not uvicorn_server.should_exit:
                time.sleep(0.5)
        finally:
            uvicorn_server.should_exit = True
            server_thread.join(timeout=15)
        return 0
    finally:
        if uvicorn_server is not None:
            uvicorn_server.should_exit = True
        node_process.terminate()
        try:
            node_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            node_process.kill()


def _fatal(error: BaseException) -> None:
    import traceback

    traceback.print_exc()
    if getattr(sys, "frozen", False) and os.name == "nt":
        try:
            import ctypes

            location = str(_LOG_PATH) if _LOG_PATH is not None else str(_log_dir())
            ctypes.windll.user32.MessageBoxW(
                0,
                f"{APP_NAME} failed to start.\n\nDetails: {location}",
                APP_NAME,
                0x10,
            )
        except Exception:
            pass


if __name__ == "__main__":
    try:
        exit_code = main()
    except SystemExit:
        raise
    except Exception as error:
        _fatal(error)
        exit_code = 1
    raise SystemExit(exit_code)
