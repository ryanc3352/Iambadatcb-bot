"""GitHub links in a message: the model gets the repository (README and file list), a file's code,
a folder listing, an issue / pull request, or a person's list of repositories (github.com/<name>).
Links work with or without https://. Also downloads whole repositories for 🐙 Add from GitHub.

Without a link it knows the user's own repositories: "my repos" lists them and naming one ("my snake repo")
reads it. Their GitHub name comes from GITHUB_USER in .env, else what they said once ("my github is ann",
"here's my github: github.com/ann", saved in user_settings.json), else the GITHUB_TOKEN's account.

Uses GitHub's public API: 60 requests an hour without a token. GITHUB_TOKEN in .env raises the
limit to 5000 and lets the app read your private repositories.
"""
import base64
import json
import re
import time

import requests

GITHUB_LINK = re.compile(
    r"(?<![\w.@/-])(?:https?://)?(?:www\.)?github\.com/([\w.-]+?)"
    r"(?:/([\w.-]+?)(?:\.git)?(?:/(blob|tree|issues|pull)/([^\s?#)>\]]+))?)?"
    r"(?=[\s/?#)>\].,!:;'\"]|$)", re.IGNORECASE)
# "my github is ann", "github username: ann", "GitHub account @ann", "github: ann"
_NOUN = r"\s+(?:user\s*name|username|user|account|profile|name|handle)"
GITHUB_NAME = re.compile(rf"(?:\bmy\s+github(?:{_NOUN})?(?:\s+is|\s*:)|\bgithub{_NOUN}(?:\s+is|\s*:)?|\bgithub\s*:)"
                         r"\s*(?:called\s+|named\s+)?@?\b([a-z0-9][a-z0-9-]{0,38})\b(?!\.\w|/)", re.IGNORECASE)  # not a link
NOT_NAMES = {"a", "an", "the", "is", "not", "down", "broken", "private", "public", "empty", "slow", "gone", "new", "old",
             "fine", "ok", "okay", "working", "offline", "online", "locked", "suspended", "deleted", "link", "repo",
             "repos", "guide", "settings", "github", "https", "http", "www", "and", "or", "but", "so", "to", "too", "also", "still", "for", "with", "account", "page", "profile"}
NOT_OWNERS = {"orgs", "users", "settings", "topics", "search", "marketplace", "about", "features", "pricing", "login",
              "join", "explore", "sponsors", "apps", "enterprise", "collections", "trending", "notifications", "new",
              "codespaces", "pulls", "issues", "site", "security", "customer-stories", "readme", "team"}
MENTIONS_GITHUB = re.compile(r"\bgit\s?hub\b|\bmy\s+(?:repos?|repositor(?:y|ies))\b", re.IGNORECASE)
# words that make it worth looking through the user's repositories for one named in the message
ABOUT_REPOS = re.compile(r"\bgit\s?hub\b|\brepos?\b|\brepositor(?:y|ies)\b|\bprojects?\b", re.IGNORECASE)
# "my repos", "my github", "my repositories", "my projects on github": list them all
MY_REPOS = re.compile(r"\bmy\s+(?:own\s+)?(?:git\s?hub|repos?|repositor(?:y|ies)|(?:git\s?hub\s+)?projects?)\b",
                      re.IGNORECASE)
NO_LINK_NOTE = ("The user mentions GitHub but the app doesn't know which account or repository. The app reads GitHub "
                "for you: github.com/<username> lists that person's public repositories and "
                "github.com/<owner>/<repository> reads one. If you need it, ask for their GitHub username or a link "
                "(the app remembers their username after that); don't say you can't access GitHub.")
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
CACHE_SECONDS = 600  # follow-up questions about the same link don't use up the hourly limit


class GitHubError(Exception):
    """GitHub couldn't be reached or refused the request."""


class GitHubReader:
    def __init__(self, token="", user="", settings_path=None):
        """user: GITHUB_USER from .env; settings_path: user_settings.json, where a name the user gave is saved."""
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "Personal-AI-Assistant"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.cache, self.login, self.user, self.settings_path = {}, None, user, settings_path

    # ---- whose repositories "my" means

    def _settings(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (AttributeError, OSError, ValueError):
            return {}

    def _token_login(self):
        """The GITHUB_TOKEN's account name, asked once ("" without a token or if GitHub can't say)."""
        if self.login is None:
            self.login = ""
            if "Authorization" in self.headers:
                try:
                    self.login = self._get(f"{API}/user").json().get("login", "")
                except (GitHubError, ValueError):
                    pass
        return self.login

    def own_user(self):
        """The user's GitHub name: GITHUB_USER, else the one they gave, else the token's account; "" if unknown."""
        return self.user or self._settings().get("github_user") or self._token_login()

    def remember_user(self, name):
        if self.settings_path is None or self.user or self._settings().get("github_user") == name:
            return
        data = self._settings()
        data["github_user"] = name
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def named_own(self, text):
        """The user's GitHub name if this message gives it: "my github is ann", or a link to a person
        with "my" in the message ("my github: github.com/ann"). None otherwise."""
        if match := next((m for m in GITHUB_NAME.finditer(text or "") if m.group(1).lower() not in NOT_NAMES), None):
            return match.group(1)
        people = [link[0] for link in self.links(text) if link[2] == "user"]
        return people[0] if people and re.search(r"\bmy\b", text, re.IGNORECASE) else None

    def own_repo_links(self, text):
        """Without a link: the user's own repository named in the message ("what does my snake repo do?"),
        or all of them for "my repos". [] if neither, or the user's GitHub name isn't known."""
        if not text or not ABOUT_REPOS.search(text) or not (owner := self.own_user()):
            return []
        try:
            names = [r.get("name", "") for r in self._repos(owner)]
        except GitHubError:
            names = []
        words = f" {_words(text)} "
        for name in sorted(names, key=len, reverse=True):  # "budget-bot" before "bot"
            if len(name) >= 3 and f" {_words(name)} " in words:
                return [(owner, name, "repo", "")]
        return [(owner, "", "user", "")] if MY_REPOS.search(text) else []

    def _resolve(self, text):
        return self.links(text) or self.own_repo_links(text)

    # ---- reading GitHub

    def _get(self, url, **params):
        key = (url, tuple(sorted(params.items())))
        if key in self.cache and time.monotonic() - self.cache[key][0] < CACHE_SECONDS:
            return self.cache[key][1]
        response = self._fetch(url, **params)
        self.cache[key] = (time.monotonic(), response)
        return response

    def _fetch(self, url, **params):
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=(10, 60))
        except requests.RequestException as e:
            raise GitHubError(f"GitHub can't be reached ({e})") from e
        if response.status_code == 404:
            raise GitHubError("not found (or it's private: add GITHUB_TOKEN to .env)")
        if response.status_code in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0":
            raise GitHubError("GitHub's hourly limit is used up; add GITHUB_TOKEN to .env for a higher limit")
        if not response.ok:
            raise GitHubError(f"GitHub answered {response.status_code}")
        return response

    def links(self, text):
        """(owner, repo, kind, rest) for each GitHub link in the text, without repeats.
        A link to a person (github.com/ann) or "my github is ann" gives (owner, "", "user", "")."""
        found = []
        for match in GITHUB_LINK.finditer(text or ""):
            owner, repo, kind, rest = match.groups()
            if owner.lower() in NOT_OWNERS:
                continue
            kind = (kind or ("repo" if repo else "user")).lower()
            link = (owner, repo or "", kind, (rest or "").rstrip("/.,!:;"))
            if link not in found:
                found.append(link)
        for match in GITHUB_NAME.finditer(text or ""):
            name = match.group(1)
            if name.lower() not in NOT_NAMES and not any(link[0].lower() == name.lower() for link in found):
                found.append((name, "", "user", ""))
        return found

    def context_for(self, text, earlier="", max_chars=8000):
        """What the GitHub links in a message (or the user's own repositories it names) point to, for the prompt.
        Without any, a follow-up uses those of `earlier` (the user's previous message); a message about GitHub
        that still has none gets a note telling the model to ask for a link. "" otherwise."""
        if name := self.named_own(text):
            self.remember_user(name)
        links, before = self._resolve(text), False
        if not links:
            links, before = self._resolve(earlier), True
        if not links:
            return NO_LINK_NOTE if MENTIONS_GITHUB.search(text or "") else ""
        parts = []
        for owner, repo, kind, rest in links[:2]:
            name = f"github.com/{owner}" + (f"/{repo}" if repo else "") + (f"/{kind}/{rest}" if rest else "")
            where = f"{name}, linked earlier" if before else name
            try:
                parts.append(f"From GitHub ({where}):\n" + self.describe(owner, repo, kind, rest, max_chars // 2))
            except GitHubError as e:
                parts.append(f"Couldn't read {name} from GitHub: {e}. Tell the user; don't guess its content.")
        return "\n\n".join(parts)

    def describe(self, owner, repo, kind, rest, max_chars=4000):
        if kind == "user":
            return self.describe_user(owner, max_chars)
        if kind == "blob":  # rest = "<branch>/<path>"
            text = self._get(f"{RAW}/{owner}/{repo}/{rest}").text
            return f"File {rest.split('/', 1)[-1]}:\n```\n{cut(text, max_chars)}\n```"
        if kind == "tree":  # rest = "<branch>/<folder>"
            branch, _, folder = rest.partition("/")
            items = self._get(f"{API}/repos/{owner}/{repo}/contents/{folder}", ref=branch).json()
            names = [item["name"] + ("/" if item.get("type") == "dir" else "") for item in items]
            return f"Folder {folder or '/'} contains: " + ", ".join(names[:200])
        if kind in ("issues", "pull"):
            number = rest.split("/")[0]
            issue = self._get(f"{API}/repos/{owner}/{repo}/issues/{number}").json()
            comments = self._get(f"{API}/repos/{owner}/{repo}/issues/{number}/comments", per_page=5).json()
            lines = [f"{'Pull request' if 'pull_request' in issue else 'Issue'} #{number}: {issue.get('title')} "
                     f"({issue.get('state')}, by {issue.get('user', {}).get('login')})",
                     cut(issue.get("body") or "(no description)", max_chars // 2)]
            lines += [f"Comment by {c.get('user', {}).get('login')}: {cut(c.get('body') or '', 500)}" for c in comments]
            return "\n".join(lines)
        return self.describe_repo(owner, repo, max_chars)

    def describe_repo(self, owner, repo, max_chars=4000):
        info = self._get(f"{API}/repos/{owner}/{repo}").json()
        branch = info.get("default_branch", "main")
        lines = [f"Repository {info.get('full_name')}: {info.get('description') or 'no description'} "
                 f"(⭐ {info.get('stargazers_count', 0)}, language {info.get('language')}, branch {branch})"]
        try:
            tree = self._get(f"{API}/repos/{owner}/{repo}/git/trees/{branch}", recursive=1).json()
            paths = [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]
            lines.append(f"Files ({len(paths)}): " + ", ".join(paths[:150]) + (" ..." if len(paths) > 150 else ""))
        except GitHubError:
            pass
        try:
            readme = self._get(f"{API}/repos/{owner}/{repo}/readme").json()
            text = base64.b64decode(readme.get("content", "")).decode("utf-8", errors="replace")
            lines.append(f"README:\n{cut(text, max_chars)}")
        except (GitHubError, ValueError):
            lines.append("(no README)")
        return "\n".join(lines)

    def describe_user(self, owner, max_chars=4000):
        """A person's (or organisation's) repositories, most recently changed first. With GITHUB_TOKEN set
        and the token's own account, private ones are listed too."""
        repos = self._repos(owner)
        if not repos:
            return f"{owner} has no public repositories."
        lines = [f"{owner}'s repositories ({len(repos)}{'+' if len(repos) == 100 else ''}, most recently changed first):"]
        for r in repos:
            notes = [r.get("language") or "", f"⭐ {r.get('stargazers_count', 0)}",
                     f"changed {(r.get('pushed_at') or '')[:10]}", "private" if r.get("private") else "",
                     "fork" if r.get("fork") else ""]
            lines.append(f"- {r.get('name')}: {r.get('description') or 'no description'} "
                         f"({', '.join(n for n in notes if n)})")
        return (cut("\n".join(lines), max_chars) +
                f"\nTo read one, the user can send its link: github.com/{owner}/<repository>")

    def _repos(self, owner):
        """owner's repositories, most recently changed first; private ones too for the token's own account."""
        if (login := self._token_login()) and login.lower() == owner.lower():
            return self._get(f"{API}/user/repos", affiliation="owner", sort="updated", per_page=100).json()
        return self._get(f"{API}/users/{owner}/repos", sort="updated", per_page=100).json()

    def download_zip(self, owner, repo):
        """The repository's default branch as ZIP bytes."""
        return self._get(f"{API}/repos/{owner}/{repo}/zipball").content


def _words(text):
    """'Iambadatcb-bot' and 'the iambadatcb bot?' both as plain lowercase words: 'iambadatcb bot'."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def cut(text, limit):
    return text if len(text) <= limit else text[:limit] + "\n[... rest not shown]"
