import threading

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

        threading.Thread(target=self._serve, daemon=True).start()
        webview.create_window("SOG Monitoring", f"http://127.0.0.1:{self._port}", width=1200, height=800, maximized=True)
        webview.start()

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
