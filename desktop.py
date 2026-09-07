import threading
import time
import urllib.request

import webview
from waitress import serve

from app import app
from update_progress_window import UpdateProgressWindow
from updater import Updater


class DesktopApp:
    def __init__(self, port: int = 5000):
        self._port = port
        self._updater = Updater()

    def run(self) -> None:
        if self._apply_pending_update():
            return

        # pywebview cancels file downloads by default (e.g. the Export File
        # button) - this lets the OS "Save As" dialog handle them instead.
        webview.settings['ALLOW_DOWNLOADS'] = True

        threading.Thread(target=self._serve, daemon=True).start()
        self._wait_until_ready()
        webview.create_window(
            "SOG Monitoring", f"http://127.0.0.1:{self._port}",
            width=1200, height=800, maximized=True, text_select=True,
        )
        webview.start()

    def _wait_until_ready(self, timeout: float = 15.0) -> None:
        # waitress needs a brief moment to start listening. Opening the
        # window before then makes it briefly show a blank/black
        # connection-failed page until it (sometimes) retries on its own -
        # waiting here means the window only ever opens once there's
        # something real to show.
        url = f"http://127.0.0.1:{self._port}/"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(url, timeout=0.5)
                return
            except Exception:
                time.sleep(0.1)

    def _apply_pending_update(self) -> bool:
        update = self._updater.find_update()
        if not update:
            return False

        download_url, _new_version = update
        progress_window = UpdateProgressWindow()
        try:
            return self._updater.apply_update(download_url, progress_callback=progress_window.update_progress)
        finally:
            progress_window.close()

    def _serve(self) -> None:
        serve(app, host="127.0.0.1", port=self._port)


if __name__ == "__main__":
    DesktopApp().run()
