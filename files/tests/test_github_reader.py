import io
import json
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
    monkeypatch.setattr(sv.github_reader, "context_for", lambda text, earlier="": "From GitHub: README says hello")
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
    assert client.post("/api/folders/github", json={"url": "github.com/ann"}).status_code == 400  # a person, no repo
    assert client.post("/api/folders/github", json={"url": "github.com/ann/snake"}).get_json()["success"]


def test_add_folder_from_github_download_error(monkeypatch):
    def fails(owner, repo):
        raise GitHubError("not found")

    monkeypatch.setattr(sv.github_reader, "download_zip", fails)
    data = ws.app.test_client().post("/api/folders/github", json={"url": "https://github.com/ann/nope"}).get_json()
    assert data == {"success": False, "error": "Couldn't download ann/nope: not found"}


# ---------- links without https, people's repository lists, follow-ups ----------

PAGES.update({
    "https://api.github.com/users/ann/repos": [
        {"name": "snake", "description": "A snake game", "language": "Python", "stargazers_count": 7,
         "pushed_at": "2026-09-30T10:00:00Z", "fork": False},
        {"name": "dotfiles", "description": None, "language": None, "stargazers_count": 0,
         "pushed_at": "2026-08-01T10:00:00Z", "fork": True}],
    "https://api.github.com/users/empty/repos": [],
})


def test_links_without_https_and_to_people():
    reader = GitHubReader()
    assert reader.links("look at github.com/ann/snake.") == [("ann", "snake", "repo", "")]
    assert reader.links("see www.github.com/ann/snake/issues/3") == [("ann", "snake", "issues", "3")]
    assert reader.links("my page: https://github.com/ann/ and (github.com/bob)") == [("ann", "", "user", ""),
                                                                                    ("bob", "", "user", "")]
    assert reader.links("github.com/explore or https://github.com/orgs/x") == []
    assert reader.links("mail me@github.com/x or notgithub.com/ann/snake") == []


def test_github_names_in_words():
    reader = GitHubReader()
    for text in ("my github is ann", "My GitHub username is ann.", "github account @ann", "github: ann",
                 "my github account is called ann"):
        assert reader.links(text) == [("ann", "", "user", "")], text
    for text in ("my github is down", "I pushed it to github yesterday", "github is great", "github actions failed",
                 "github usernames are hard"):
        assert reader.links(text) == [], text
    assert reader.links("my github is ann, see github.com/ann") == [("ann", "", "user", "")]
    assert reader.named_own("github username: ann/") is None  # not "name" out of "username"


def test_a_persons_repositories(reader):
    context = reader.context_for("what repos are on github.com/ann?")
    assert "From GitHub (github.com/ann)" in context and "ann's repositories (2" in context
    assert "- snake: A snake game (Python, ⭐ 7, changed 2026-09-30)" in context
    assert "- dotfiles: no description (⭐ 0, changed 2026-08-01, fork)" in context
    assert "github.com/ann/<repository>" in context
    assert "empty has no public repositories." in reader.context_for("github.com/empty")


def test_own_private_repositories_with_a_token(monkeypatch):
    reader = GitHubReader("abc")
    pages = {"https://api.github.com/user": {"login": "Ann"},
             "https://api.github.com/user/repos": [{"name": "secret", "private": True, "stargazers_count": 0}]}
    asked = []

    def fake_get(url, **params):
        asked.append(url)
        return FakeResponse(pages[url])
    monkeypatch.setattr(reader, "_get", fake_get)
    assert "- secret: no description (⭐ 0, changed , private)" in reader.context_for("github.com/ann")
    assert asked == ["https://api.github.com/user", "https://api.github.com/user/repos"]


def test_a_follow_up_uses_the_previous_messages_link(reader):
    context = reader.context_for("what does it do?", earlier="look at github.com/ann/snake")
    assert context.startswith("From GitHub (github.com/ann/snake, linked earlier)") and "A snake game" in context
    assert reader.context_for("and this one? github.com/ann", earlier="github.com/ann/snake").startswith(
        "From GitHub (github.com/ann)")
    assert reader.context_for("thanks!", earlier="no links") == ""


def test_github_without_a_link_asks_for_one(reader):
    for text in ("can you see my repos?", "look at my GitHub", "what's on my git hub"):
        assert "ask for their GitHub username or a link" in reader.context_for(text), text
        assert "don't say you can't access GitHub" in reader.context_for(text), text
    assert reader.context_for("explain git rebase") == ""


def test_repeated_requests_come_from_the_cache(monkeypatch):
    reader, fetched = GitHubReader(), []

    def fetch(url, **params):
        fetched.append(url)
        return FakeResponse(PAGES[url])
    monkeypatch.setattr(reader, "_fetch", fetch)
    for _ in range(3):
        reader.context_for("github.com/ann")
    assert fetched == ["https://api.github.com/users/ann/repos"]
    monkeypatch.setattr("github_reader.CACHE_SECONDS", 0)
    reader.context_for("github.com/ann")
    assert len(fetched) == 2


def test_follow_up_reaches_the_prompt(fake_ollama, monkeypatch):
    monkeypatch.setattr(sv.github_reader, "_fetch", lambda url, **params: FakeResponse(PAGES[url]))
    monkeypatch.setattr(sv.github_reader, "cache", {})
    client = ws.app.test_client()
    client.post("/api/chat", json={"message": "what repos are on github.com/ann"})
    assert "- snake: A snake game" in fake_ollama.last_prompt
    client.post("/api/chat", json={"message": "which one is the newest?"})
    assert "From GitHub (github.com/ann, linked earlier)" in fake_ollama.last_prompt


# ---------- the user's own repositories without a link ----------

@pytest.fixture
def mine(reader, tmp_path):
    reader.settings_path = tmp_path / "user_settings.json"
    return reader


def test_my_repos_needs_a_name_first_then_remembers_it(mine):
    assert "ask for their GitHub username" in mine.context_for("can you see my repos?")
    assert "ann's repositories" in mine.context_for("my github is ann")
    assert json.loads(mine.settings_path.read_text())["github_user"] == "ann"
    again = GitHubReader(settings_path=mine.settings_path)  # after a restart
    again._get = mine._get
    assert "ann's repositories" in again.context_for("show me my repos")
    assert "A snake game" in again.context_for("what does my snake repo do?")


def test_a_link_with_my_is_remembered_but_someone_elses_is_not(mine):
    mine.context_for("look at github.com/bob")
    assert mine.own_user() == ""
    mine.context_for("here's my github: github.com/ann")
    assert mine.own_user() == "ann"
    mine.context_for("what about github.com/bob?")
    assert mine.own_user() == "ann"


def test_saving_the_name_keeps_the_other_settings(mine):
    mine.settings_path.write_text(json.dumps({"model": "qwen3:8b"}))
    mine.context_for("github username: ann")
    assert json.loads(mine.settings_path.read_text()) == {"model": "qwen3:8b", "github_user": "ann"}


def test_github_user_setting_wins_and_is_never_overwritten(mine):
    mine.user = "ann"
    assert "ann's repositories" in mine.context_for("list my github projects")
    mine.context_for("my github is bob")
    assert mine.own_user() == "ann" and not mine.settings_path.exists()


def test_the_tokens_account_is_used_when_no_name_was_given(monkeypatch, tmp_path):
    reader = GitHubReader("abc", settings_path=tmp_path / "s.json")
    pages = {"https://api.github.com/user": {"login": "ann"},
             "https://api.github.com/user/repos": [{"name": "secret", "private": True}]}
    monkeypatch.setattr(reader, "_get", lambda url, **params: FakeResponse(pages[url]))
    assert "- secret:" in reader.context_for("show my repos")


def test_repository_names_in_a_message(mine):
    mine.user = "ann"
    names = []
    mine._repos = lambda owner: [{"name": n} for n in names]
    names[:] = ["bot", "budget-bot", "ab"]
    assert mine.own_repo_links("how does my budget bot repo work") == [("ann", "budget-bot", "repo", "")]
    assert mine.own_repo_links("the Budget-Bot project?") == [("ann", "budget-bot", "repo", "")]
    assert mine.own_repo_links("my bot repo") == [("ann", "bot", "repo", "")]
    assert mine.own_repo_links("the ab repo") == []  # too short to tell from a word
    assert mine.own_repo_links("my robot project") == []
    assert mine.own_repo_links("my repos") == [("ann", "", "user", "")]


def test_messages_not_about_repositories_never_ask_github(mine):
    mine.user = "ann"
    mine._get = lambda url, **params: pytest.fail("GitHub was asked")
    assert mine.context_for("how is the snake doing today?") == ""


def test_a_follow_up_about_a_named_repo(mine):
    mine.user = "ann"
    context = mine.context_for("does it have tests?", earlier="what does my snake repo do?")
    assert context.startswith("From GitHub (github.com/ann/snake, linked earlier)")


def test_my_repos_reach_the_prompt(fake_ollama, monkeypatch):
    monkeypatch.setattr(sv.github_reader, "_fetch", lambda url, **params: FakeResponse(PAGES[url]))
    monkeypatch.setattr(sv.github_reader, "cache", {})
    monkeypatch.setattr(sv.github_reader, "user", "")
    client = ws.app.test_client()
    client.post("/api/chat", json={"message": "my github is ann"})
    client.post("/api/chat", json={"message": "thanks"})
    client.post("/api/chat", json={"message": "what does my snake repo do?"})
    assert "Repository ann/snake: A snake game" in fake_ollama.last_prompt
