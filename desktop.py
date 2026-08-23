import threading

import webview
from waitress import serve

from app import app

PORT = 5000


def _run_server():
    serve(app, host="127.0.0.1", port=PORT)


def main():
    threading.Thread(target=_run_server, daemon=True).start()
    webview.create_window("SOG Monitoring", f"http://127.0.0.1:{PORT}", width=1200, height=800)
    webview.start()


if __name__ == "__main__":
    main()
