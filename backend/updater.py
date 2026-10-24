from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
from typing import Callable, Optional

import requests

CURRENT_VERSION = "1.1.4"

GITHUB_REPO = "ORACULO1/mc_launcher-personal"

ProgressCallback = Callable[[int, int], None]


def _parse_version(v: str) -> tuple:
    v = v.strip().lstrip("vV")
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def check_for_updates() -> dict:
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=6,
        )
        if r.status_code == 404:
            return {"ok": True, "updateAvailable": False, "currentVersion": CURRENT_VERSION}
        if r.status_code != 200:
            return {"ok": False, "error": f"GitHub respondió con el código {r.status_code}."}

        data = r.json()
        tag = data.get("tag_name", "")
        assets = data.get("assets", [])
        exe_asset = next((a for a in assets if a.get("name", "").lower().endswith(".exe")), None)
        download_url = exe_asset["browser_download_url"] if exe_asset else data.get("html_url")

        is_newer = _parse_version(tag) > _parse_version(CURRENT_VERSION)

        return {
            "ok": True,
            "updateAvailable": is_newer,
            "currentVersion": CURRENT_VERSION,
            "latestVersion": tag.lstrip("vV") or tag,
            "downloadUrl": download_url,
            "hasDirectExe": exe_asset is not None,
            "releaseNotes": (data.get("body") or "").strip(),
        }
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"No se pudo conectar a GitHub: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def download_and_launch_installer(
    download_url: str,
    on_progress: Optional[ProgressCallback] = None,
    on_ready: Optional[Callable[[], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    on_quit_app: Optional[Callable[[], None]] = None,
) -> None:
    try:
        installer_path = os.path.join(tempfile.gettempdir(), "ChechenitzaStudio-Setup-update.exe")

        with requests.get(download_url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(installer_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=262144):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)

        if on_ready:
            on_ready()

        time.sleep(1)

        env = os.environ.copy()
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        delayed_launch_cmd = f'ping 127.0.0.1 -n 3 -w 500 >nul & start "" "{installer_path}"'
        subprocess.Popen(delayed_launch_cmd, shell=True, env=env)

        if on_quit_app:
            on_quit_app()
        os._exit(0)

    except Exception as e:
        if on_error:
            on_error(str(e))


def start_download_and_install(
    download_url: str,
    on_progress: Optional[ProgressCallback] = None,
    on_ready: Optional[Callable[[], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    on_quit_app: Optional[Callable[[], None]] = None,
) -> None:
    threading.Thread(
        target=download_and_launch_installer,
        args=(download_url, on_progress, on_ready, on_error, on_quit_app),
        daemon=True,
    ).start()
