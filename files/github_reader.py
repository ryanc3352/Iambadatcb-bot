"""GitHub links in a message: the model gets the repository (README and file list), a file's code,
a folder listing or an issue / pull request. Also downloads whole repositories for 🐙 Add from GitHub.

Uses GitHub's public API: 60 requests an hour without a token. GITHUB_TOKEN in .env raises the
limit to 5000 and lets the app read your private repositories.
"""
import base64
import re

import requests

GITHUB_LINK = re.compile(
    r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/(blob|tree|issues|pull)/([^\s?#)>\]]+))?"
    r"(?=[\s/?#)>\].,!]|$)", re.IGNORECASE)
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"


class GitHubError(Exception):
    """GitHub couldn't be reached or refused the request."""


class GitHubReader:
    def __init__(self, token=""):
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "Personal-AI-Assistant"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _get(self, url, **params):
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
        """(owner, repo, kind, rest) for each GitHub link in the text, without repeats."""
        found = []
        for match in GITHUB_LINK.finditer(text or ""):
            owner, repo, kind, rest = match.groups()
            if owner.lower() in ("orgs", "users", "settings", "topics", "search", "marketplace"):
                continue
            link = (owner, repo, (kind or "repo").lower(), (rest or "").rstrip("/.,!:;"))
            if link not in found:
                found.append(link)
        return found

    def context_for(self, text, max_chars=8000):
        """What the GitHub links in a message point to, for the prompt ("" without links)."""
        parts = []
        for owner, repo, kind, rest in self.links(text)[:2]:
            name = f"github.com/{owner}/{repo}" + (f"/{kind}/{rest}" if rest else "")
            try:
                parts.append(f"From GitHub ({name}):\n" + self.describe(owner, repo, kind, rest, max_chars // 2))
            except GitHubError as e:
                parts.append(f"Couldn't read {name} from GitHub: {e}. Tell the user; don't guess its content.")
        return "\n\n".join(parts)

    def describe(self, owner, repo, kind, rest, max_chars=4000):
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

    def download_zip(self, owner, repo):
        """The repository's default branch as ZIP bytes."""
        return self._get(f"{API}/repos/{owner}/{repo}/zipball").content


def cut(text, limit):
    return text if len(text) <= limit else text[:limit] + "\n[... rest not shown]"
