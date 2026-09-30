import io
import zipfile

import pytest

import services as sv
import web_server as ws
from github_reader import GitHubError, GitHubReader


class FakeResponse:
    def __init__(self, data=None, text=""):
        self.data, self.text = data, text

    def json(self):
        return self.data


PAGES = {
    "https://api.github.com/repos/ann/snake": {"full_name": "ann/snake", "description": "A snake game",
                                               "stargazers_count": 7, "language": "Python", "default_branch": "main"},
    "https://api.github.com/repos/ann/snake/git/trees/main": {"tree": [{"path": "main.py", "type": "blob"},
                                                                       {"path": "assets", "type": "tree"}]},
    "https://api.github.com/repos/ann/snake/readme": {"content": "IyBTbmFrZQpQbGF5IHdpdGggYXJyb3dzLg=="},
    "https://raw.githubusercontent.com/ann/snake/main/src/game.py": "print('game')",
    "https://api.github.com/repos/ann/snake/contents/src": [{"name": "game.py", "type": "file"},
                                                            {"name": "levels", "type": "dir"}],
    "https://api.github.com/repos/ann/snake/issues/3": {"title": "Crash on start", "state": "open",
                                                        "user": {"login": "bob"}, "body": "It crashes."},
    "https://api.github.com/repos/ann/snake/issues/3/comments": [{"user": {"login": "ann"}, "body": "Fixed soon"}],
}


@pytest.fixture
def reader(monkeypatch):
    reader = GitHubReader()

    def fake_get(url, **params):
        if url not in PAGES:
            raise GitHubError("not found (or it's private: add GITHUB_TOKEN to .env)")
        page = PAGES[url]
        return FakeResponse(text=page) if isinstance(page, str) else FakeResponse(page)

    monkeypatch.setattr(reader, "_get", fake_get)
    return reader


def test_links():
    reader = GitHubReader()
    text = ("See https://github.com/ann/snake. And https://github.com/ann/snake/blob/main/src/game.py, "
            "https://github.com/ann/snake/issues/3 and https://github.com/ann/snake.git and "
            "https://github.com/ann/snake/actions plus https://github.com/orgs/x")
    assert reader.links(text) == [("ann", "snake", "repo", ""), ("ann", "snake", "blob", "main/src/game.py"),
                                  ("ann", "snake", "issues", "3")]
    assert reader.links("no links here") == []


def test_context_for_repo_file_folder_and_issue(reader):
    repo = reader.context_for("what does https://github.com/ann/snake do?")
    assert "A snake game" in repo and "main.py" in repo and "Play with arrows." in repo
    assert "print('game')" in reader.context_for("explain https://github.com/ann/snake/blob/main/src/game.py")
    assert "levels/" in reader.context_for("https://github.com/ann/snake/tree/main/src")
    issue = reader.context_for("help with https://github.com/ann/snake/issues/3")
    assert "Crash on start" in issue and "It crashes." in issue and "Fixed soon" in issue
    assert reader.context_for("hello") == ""


def test_unreadable_link_is_reported_not_guessed(reader):
    context = reader.context_for("https://github.com/ann/private-thing")
    assert "Couldn't read github.com/ann/private-thing" in context and "don't guess" in context


def test_token_is_sent():
    assert GitHubReader("abc").headers["Authorization"] == "Bearer abc"
    assert "Authorization" not in GitHubReader().headers


def test_github_link_reaches_the_prompt(fake_ollama, monkeypatch):
    monkeypatch.setattr(sv.github_reader, "context_for", lambda text: "From GitHub: README says hello")
    ws.app.test_client().post("/api/chat", json={"message": "read https://github.com/ann/snake"})
    assert "From GitHub: README says hello" in fake_ollama.last_prompt


def test_add_folder_from_github(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ann-snake-1a2b3c/main.py", "print('snake')")
        archive.writestr("ann-snake-1a2b3c/assets/logo.txt", "logo")
    monkeypatch.setattr(sv.github_reader, "download_zip", lambda owner, repo: buffer.getvalue())
    client = ws.app.test_client()
    data = client.post("/api/folders/github", json={"url": "https://github.com/ann/snake"}).get_json()
    assert data["success"] and data["folder"] == "snake"
    files = {f["path"] for f in sv.folder_manager.get_folder_contents("snake")[0]}
    assert files == {"main.py", "assets/logo.txt"}  # GitHub's wrapper folder is gone
    assert client.post("/api/folders/github", json={"url": "not a link"}).status_code == 400


def test_add_folder_from_github_download_error(monkeypatch):
    def fails(owner, repo):
        raise GitHubError("not found")

    monkeypatch.setattr(sv.github_reader, "download_zip", fails)
    data = ws.app.test_client().post("/api/folders/github", json={"url": "https://github.com/ann/nope"}).get_json()
    assert data == {"success": False, "error": "Couldn't download ann/nope: not found"}
