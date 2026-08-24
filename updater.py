import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from version import APP_VERSION

GITHUB_REPO = "abdallahfarag255/SOG"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
APP_FOLDER_NAME = "SOG Monitoring"


class Updater:
    def __init__(self, current_version: str = APP_VERSION):
        self._current_version = current_version

    def find_update(self):
        """Returns (download_url, new_version) if a newer release is available, else None."""
        try:
            request = urllib.request.Request(RELEASES_API_URL, headers={"Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                release = json.loads(response.read())
        except Exception:
            return None

        latest_version = release.get("tag_name", "").lstrip("v")
        if not latest_version or not self._is_newer(latest_version, self._current_version):
            return None

        asset = next((a for a in release.get("assets", []) if a["name"].endswith(".zip")), None)
        if not asset:
            return None

        return asset["browser_download_url"], latest_version

    def apply_update(self, download_url: str) -> bool:
        """Downloads the update, then hands off to a helper script that replaces this
        app's folder once the current process exits. Only works for the packaged exe."""
        if not getattr(sys, "frozen", False):
            return False

        app_dir = os.path.dirname(sys.executable)
        parent_dir = os.path.dirname(app_dir)

        tmp_dir = tempfile.mkdtemp(prefix="sog_update_")
        zip_path = os.path.join(tmp_dir, "update.zip")
        urllib.request.urlretrieve(download_url, zip_path)

        extract_dir = os.path.join(tmp_dir, "extracted")
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_dir)

        new_app_dir = os.path.join(extract_dir, APP_FOLDER_NAME)
        if not os.path.isdir(new_app_dir):
            return False

        for config_file in (".env", "service_account.json"):
            src = os.path.join(app_dir, config_file)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(new_app_dir, config_file))

        script_path = os.path.join(tmp_dir, "apply_update.bat")
        with open(script_path, "w", encoding="utf-8") as script:
            script.write(
                "@echo off\r\n"
                "timeout /t 2 /nobreak > NUL\r\n"
                f'rmdir /s /q "{app_dir}"\r\n'
                f'move "{new_app_dir}" "{app_dir}"\r\n'
                f'start "" "{os.path.join(app_dir, APP_FOLDER_NAME + ".exe")}"\r\n'
                f'rmdir /s /q "{tmp_dir}"\r\n'
            )

        subprocess.Popen(["cmd", "/c", script_path], cwd=parent_dir, creationflags=subprocess.CREATE_NO_WINDOW)
        return True

    @staticmethod
    def _is_newer(candidate: str, current: str) -> bool:
        def parse(v):
            return tuple(int(part) if part.isdigit() else 0 for part in v.split("."))

        return parse(candidate) > parse(current)
