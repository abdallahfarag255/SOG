import threading

import webview
from waitress import serve

from app import app
from updater import Updater


class DesktopApp:
    def __init__(self, port: int = 5000):
        self._port = port
        self._updater = Updater()

    def run(self) -> None:
        if self._apply_pending_update():
            return

        threading.Thread(target=self._serve, daemon=True).start()
        webview.create_window("SOG Monitoring", f"http://127.0.0.1:{self._port}", width=1200, height=800)
        webview.start()

    def _apply_pending_update(self) -> bool:
        update = self._updater.find_update()
        if not update:
            return False

        download_url, _new_version = update
        return self._updater.apply_update(download_url)

    def _serve(self) -> None:
        serve(app, host="127.0.0.1", port=self._port)


if __name__ == "__main__":
    DesktopApp().run()
