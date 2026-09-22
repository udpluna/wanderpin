"""
WanderPin — iPhone location simulator for iOS 17.4+.

Uses Apple's built-in Developer Mode location simulation (the same feature Xcode uses)
through the open-source pymobiledevice3 library.

Run:  python wanderpin.py            (opens the app window)
      python wanderpin.py --browser  (use your web browser instead)
"""
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

# PyInstaller windowed builds have no console: give logging somewhere to go.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from core.config import APP_NAME, DATA_DIR, PORT, STATIC_DIR, VERSION  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(DATA_DIR / "app.log", encoding="utf-8")],
)
log = logging.getLogger("wanderpin")

# Record crashes (including native ones) so problems in the packaged app can be diagnosed.
import faulthandler  # noqa: E402
import traceback  # noqa: E402
_crash_file = open(DATA_DIR / "crash.log", "a", encoding="utf-8")
faulthandler.enable(file=_crash_file)


def _excepthook(tp, val, tb):
    log.error("Unhandled error:\n%s", "".join(traceback.format_exception(tp, val, tb)))
sys.excepthook = _excepthook
threading.excepthook = lambda a: _excepthook(a.exc_type, a.exc_value, a.exc_traceback)


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def run_server(host: str, stop_evt: threading.Event):
    log.info("Starting server…")
    import uvicorn
    from core.server import app

    config = uvicorn.Config(app, host=host, port=PORT, log_level="warning", ws="none")
    server = uvicorn.Server(config)

    def watcher():
        stop_evt.wait()
        server.should_exit = True
    threading.Thread(target=watcher, daemon=True).start()
    server.run()


def _show_error(msg: str):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME, 0x10)
    except Exception:
        print(msg)


def main():
    log.info("Launching %s %s (frozen=%s)", APP_NAME, VERSION, getattr(sys, "frozen", False))
    url = f"http://127.0.0.1:{PORT}"
    if port_in_use(PORT):
        # already running: just show it
        log.info("%s is already running — opening it.", APP_NAME)
        webbrowser.open(url)
        return

    from core.store import Store
    settings = Store().settings
    host = "0.0.0.0" if settings.get("lan_enabled") else "127.0.0.1"
    use_browser = "--browser" in sys.argv or settings.get("open_in_browser")

    stop_evt = threading.Event()
    t = threading.Thread(target=run_server, args=(host, stop_evt), daemon=False)
    t.start()
    started = False
    for _ in range(600):              # first launch can be slow while antivirus scans the app
        if port_in_use(PORT):
            started = True
            break
        if not t.is_alive():
            break
        time.sleep(0.1)
    if not started:
        log.error("Background service failed to start - see the error above.")
        _show_error(f"{APP_NAME} couldn't start its background service.\n\n"
                    f"Please report this with the file:\n{DATA_DIR / 'app.log'}")
        return
    log.info("%s %s running at %s (data: %s)", APP_NAME, VERSION, url, DATA_DIR)

    if not use_browser:
        try:
            import webview  # pywebview: native window (Edge WebView2 on Windows)
            webview.create_window(APP_NAME, url, width=1360, height=860, min_size=(980, 640),
                                  background_color="#0b0d12", text_select=True)
            icon = STATIC_DIR / "img" / "icon.ico"
            webview.start(icon=str(icon) if icon.exists() else None)
            stop_evt.set()      # window closed -> shut everything down (resets phone GPS)
            t.join(timeout=10)
            return
        except Exception as e:
            log.warning("App window unavailable (%s) — using the browser instead.", e)

    webbrowser.open(url)
    print(f"\n  {APP_NAME} is running at {url}\n  Close this window to quit.\n")
    try:
        while t.is_alive():
            t.join(0.5)
    except KeyboardInterrupt:
        stop_evt.set()
        t.join(timeout=10)


if __name__ == "__main__":
    main()
