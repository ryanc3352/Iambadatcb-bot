"""The ⬆️ Update button: download the newest version from GitHub and copy it over the app's files.

Chats, saved files, settings (.env) and the .venv are never touched: they aren't in the download,
and they're skipped even if they were. The files that get replaced are copied to backups/ first.
"""
import io
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

import requests

APP_FOLDER = "files"  # the app's folder inside the repository
KEEP = {".env", ".venv", "venv", "data", "ai_files", "backups", "logs", "user_settings.json", "__pycache__"}


class UpdateError(Exception):
    """The update couldn't be downloaded or installed."""


def download(url):
    """The repository ZIP as bytes."""
    try:
        response = requests.get(url, timeout=(10, 120))
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        raise UpdateError(f"Couldn't download the update ({e}). Check your internet connection.") from e


def app_files(zip_bytes):
    """{path inside the app folder: content} for each app file in the repository ZIP."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise UpdateError("The download isn't a ZIP file") from e
    files = {}
    for info in archive.infolist():
        parts = PurePosixPath(info.filename).parts
        # "<repo>-main/files/web_server.py" -> "web_server.py"
        if info.is_dir() or len(parts) < 3 or parts[1] != APP_FOLDER:
            continue
        relative = parts[2:]
        if ".." in relative or relative[0] in KEEP or relative[-1].endswith(".db"):
            continue
        files["/".join(relative)] = archive.read(info)
    if "web_server.py" not in files:
        raise UpdateError("The download doesn't contain the app (no files/web_server.py)")
    return files


def changed_files(files, base_dir):
    """Paths whose content differs from the installed file (or that are new)."""
    changed = []
    for relative, content in files.items():
        target = Path(base_dir, relative)
        try:
            if target.read_bytes() == content:
                continue
        except OSError:
            pass
        changed.append(relative)
    return sorted(changed)


def install(files, changed, base_dir, backups_dir):
    """Write the changed files, keeping a copy of the old ones. On a failure, put everything back."""
    backup = Path(backups_dir) / f"update-{datetime.now():%Y%m%d-%H%M%S}"
    written = []
    try:
        for relative in changed:
            target = Path(base_dir, relative)
            if target.exists():
                (backup / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".update")
            temporary.write_bytes(files[relative])
            os.replace(temporary, target)
            written.append(relative)
    except OSError as e:
        for relative in written:
            old = backup / relative
            try:
                if old.exists():
                    shutil.copy2(old, Path(base_dir, relative))
                else:
                    Path(base_dir, relative).unlink()
            except OSError:
                pass
        raise UpdateError(f"Couldn't write {relative}: {e}. Nothing was changed.") from e
    return backup if written and backup.exists() else None


def update(url, base_dir, backups_dir):
    """Download and install the newest version.

    Returns:
        dict: changed (list of paths), backup (folder with the old files, or None)
    """
    files = app_files(download(url))
    changed = changed_files(files, base_dir)
    backup = install(files, changed, base_dir, backups_dir) if changed else None
    return {'changed': changed, 'backup': str(backup) if backup else None}
