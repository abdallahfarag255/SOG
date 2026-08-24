import threading

import webview
from waitress import serve

from app import app


class DesktopApp:
    def __init__(self, port: int = 5000):
        self._port = port

    def run(self) -> None:
        threading.Thread(target=self._serve, daemon=True).start()
        webview.create_window("SOG Monitoring", f"http://127.0.0.1:{self._port}", width=1200, height=800)
        webview.start()

    def _serve(self) -> None:
        serve(app, host="127.0.0.1", port=self._port)


if __name__ == "__main__":
    DesktopApp().run()
