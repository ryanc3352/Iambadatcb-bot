import io
import zipfile

import pytest

import routes_system
import updater
import web_server as ws


def repo_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(f"Iambadatcb-bot-main/{name}", content)
    return buffer.getvalue()


NEW_VERSION = {
    "README.md": "top-level file, not part of the app",
    "files/web_server.py": "new server",
    "files/static/js/new.js": "new script",
    "files/same.py": "unchanged",
    "files/.env": "SECRET=from-zip",
    "files/ai_files/x.txt": "never copied",
    "files/conversation_history.db": "never copied",
}


@pytest.fixture
def app_dir(tmp_path):
    base = tmp_path / "app"
    base.mkdir()
    (base / "web_server.py").write_text("old server")
    (base / "same.py").write_text("unchanged")
    (base / ".env").write_text("SECRET=mine")
    return base


def test_app_files_only_takes_the_app_folder():
    files = updater.app_files(repo_zip(NEW_VERSION))
    assert sorted(files) == ["same.py", "static/js/new.js", "web_server.py"]


def test_app_files_rejects_bad_downloads():
    with pytest.raises(updater.UpdateError):
        updater.app_files(b"not a zip")
    with pytest.raises(updater.UpdateError):
        updater.app_files(repo_zip({"files/other.py": "x"}))
    assert "../evil.py" not in updater.app_files(repo_zip({**NEW_VERSION, "files/../evil.py": "x"}))


def test_update_replaces_changed_files_and_keeps_backups(app_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "download", lambda url: repo_zip(NEW_VERSION))
    result = updater.update("http://example.test/main.zip", app_dir, tmp_path / "backups")
    assert result["changed"] == ["static/js/new.js", "web_server.py"]
    assert (app_dir / "web_server.py").read_text() == "new server"
    assert (app_dir / "static/js/new.js").read_text() == "new script"
    assert (app_dir / ".env").read_text() == "SECRET=mine"
    assert not (app_dir / "ai_files").exists() and not (app_dir / "conversation_history.db").exists()
    assert (tmp_path / "backups").joinpath(result["backup"], "web_server.py").read_text() == "old server"
    # A second press finds nothing new
    assert updater.update("http://example.test/main.zip", app_dir, tmp_path / "backups")["changed"] == []


def test_failed_write_puts_everything_back(app_dir, tmp_path, monkeypatch):
    real_replace = updater.os.replace

    def replace(src, dst):
        if str(dst).endswith("web_server.py"):
            raise PermissionError("file is locked")
        real_replace(src, dst)

    monkeypatch.setattr(updater.os, "replace", replace)
    files = updater.app_files(repo_zip(NEW_VERSION))
    with pytest.raises(updater.UpdateError, match="Nothing was changed"):
        updater.install(files, ["static/js/new.js", "web_server.py"], app_dir, tmp_path / "backups")
    assert (app_dir / "web_server.py").read_text() == "old server"
    assert not (app_dir / "static/js/new.js").exists()


def test_update_route(app_dir, tmp_path, monkeypatch):
    client = ws.app.test_client()
    monkeypatch.setattr(routes_system, "BASE_DIR", app_dir)
    monkeypatch.setattr(routes_system, "BACKUPS_PATH", tmp_path / "backups")
    monkeypatch.setattr(updater, "download", lambda url: repo_zip(NEW_VERSION))
    restarts = []
    monkeypatch.setattr(routes_system, "restart_soon", lambda: restarts.append(1))

    assert client.post("/api/update", data="confirm=1").status_code == 400  # plain forms from other sites

    monkeypatch.setenv("AI_ASSISTANT_LAUNCHER", "start.py")
    data = client.post("/api/update", json={"confirm": True}).get_json()
    assert data == {"success": True, "changed": ["static/js/new.js", "web_server.py"], "restarting": True}
    assert restarts == [1]

    data = client.post("/api/update", json={"confirm": True}).get_json()
    assert data == {"success": True, "changed": [], "restarting": False}
    assert restarts == [1]  # nothing new: no restart


def test_update_route_reports_download_errors(monkeypatch):
    def offline(url):
        raise updater.UpdateError("Couldn't download the update")

    monkeypatch.setattr(updater, "download", offline)
    data = ws.app.test_client().post("/api/update", json={"confirm": True}).get_json()
    assert data == {"success": False, "error": "Couldn't download the update"}
