"""Does the assistant really learn from past chats/feedback, and can it improve its own code?"""
import importlib.util
import shutil

import pytest

import web_server as ws
import prompts
import config
import routes_improve
import services as sv
from autonomous_improver import AutonomousImprover
from conftest import FakeResponse
from learning_system import LearningSystem
from self_analyzer import SelfAnalyzer
from upgrade_manager import UpgradeManager


@pytest.fixture
def client(fake_ollama):
    sv.conversation_history.start_new_conversation()
    return ws.app.test_client()


def chat(client, message):
    response = client.post("/api/chat", json={"message": message})
    assert response.status_code == 200, response.get_json()
    return response.get_json()["response"]


# ---------------- learning from earlier conversations and feedback

def test_recalls_facts_from_an_earlier_conversation(client, fake_ollama):
    chat(client, "My dog is called Biscuit and he loves the beach")
    client.post("/api/conversations/new")
    chat(client, "What is my dog called?")
    prompt = fake_ollama.last_prompt
    assert "Recent conversation" not in prompt          # the old chat is not in the short-term context...
    assert "Related memory" in prompt and "Biscuit" in prompt  # ...but long-term memory finds it


def test_feedback_changes_later_prompts(client, fake_ollama):
    fake_ollama.reply = "Recursion is when a function calls itself. " * 30
    chat(client, "Explain recursion")
    client.post("/api/feedback", json={"rating": 2, "feedback": "Too long, use short bullet points"})

    fake_ollama.reply = "ok"
    chat(client, "Explain loops")
    prompt = fake_ollama.last_prompt
    assert "Feedback the user gave on your earlier answers" in prompt
    assert "2/5 on \"Recursion is when a function calls itself." in prompt
    assert "Too long, use short bullet points" in prompt

    saved = sv.learner.learning_data["user_feedback"][-1]
    assert saved["response_excerpt"].startswith("Recursion is when") and "\n" not in saved["response_excerpt"]


def test_usage_is_tracked(client, fake_ollama, monkeypatch):
    monkeypatch.setattr(sv.weather_provider, "get_weather", lambda place: "sunny")
    monkeypatch.setattr(sv.web_searcher, "search", lambda q, num_results=5: "results")
    before = client.get("/api/self/learning").get_json()["insights"]
    chat(client, "weather in Rome")
    chat(client, "latest news")
    client.post("/api/execute-code", json={"code": "print(1)"})
    after = client.get("/api/self/learning").get_json()["insights"]
    assert after["total_conversations"] == before["total_conversations"] + 2
    usage = sv.learner.learning_data["feature_usage"]
    assert usage["weather"] >= 1 and usage["web_search"] >= 1 and usage["code_execution"] >= 1


def test_feedback_guidance_unit(tmp_path):
    ls = LearningSystem(tmp_path)
    assert ls.get_feedback_guidance() == ""
    ls.log_feedback(1, 5, "")                       # stars only: nothing to tell the model
    assert ls.get_feedback_guidance() == ""
    for i in range(7):
        ls.log_feedback(i, 3, f"note {i}", f"answer {i}")
    guidance = ls.get_feedback_guidance(limit=3).splitlines()
    assert guidance[1:] == ['- 3/5 on "answer 4": note 4', '- 3/5 on "answer 5": note 5',
                            '- 3/5 on "answer 6": note 6']


# ---------------- improving its own code

BAD_SEARCH = '''import requests


class WebSearcher:
    def search(self, query, num_results=5):
        try:
            data = requests.get("https://api.duckduckgo.com/", params={"q": query, "format": "json"}, timeout=10).json()
        except:
            return "Search error"
        return data.get("AbstractText") or "No results found"
'''

GOOD_SEARCH = '''"""Web search helper."""
import requests


class WebSearcher:
    """DuckDuckGo Instant Answer search."""

    def search(self, query, num_results=5):
        """Return the instant answer for a query."""
        try:
            data = requests.get("https://api.duckduckgo.com/", params={"q": query, "format": "json"}, timeout=10).json()
        except (requests.exceptions.RequestException, ValueError):
            return "Search error"
        return data.get("AbstractText") or "No results found"
'''


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A temporary copy of the project, so upgrades never touch the real files."""
    project = tmp_path / "project"
    project.mkdir()
    for py_file in config.BASE_DIR.glob("*.py"):
        shutil.copy2(py_file, project / py_file.name)
    (project / "web_search.py").write_text(BAD_SEARCH, encoding="utf-8")

    analyzer = SelfAnalyzer(project, tmp_path / "logs")
    manager = UpgradeManager(project, tmp_path / "backups", allowed_files=["web_search.py"])
    for module in (prompts, routes_improve):  # the chat shows the file's code, the routes upgrade it
        monkeypatch.setattr(module, "UPGRADEABLE_FILES", ["web_search.py"])
        monkeypatch.setattr(module, "upgrade_manager", manager)
    monkeypatch.setattr(routes_improve, "analyzer", analyzer)
    monkeypatch.setattr(routes_improve, "improver", AutonomousImprover(analyzer, sv.learner))
    return project


def test_auto_improve_uses_current_code_and_really_improves_it(client, fake_ollama, sandbox, monkeypatch):
    before = routes_improve.analyzer.analyze_all_files()
    score_before = routes_improve.analyzer.get_code_quality_score(before)
    issues_before = len(before["web_search.py"]["issues"])

    # 1. Auto-Improve picks the file and asks for a fix
    improve = client.get("/api/self/improvement-prompt").get_json()
    assert improve["target_file"] == "web_search.py"
    assert improve["prompt"].startswith("Improve web_search.py.")
    assert "Bare 'except:'" in improve["prompt"] and "- none yet" in improve["prompt"]

    # 2. Sending it to the model includes the file's CURRENT code
    fake_ollama.reply = ("UPGRADE_REQUEST:\nFILE: web_search.py\nDESCRIPTION: Add docstrings, catch specific errors\n"
                         f"CODE:\n```python\n{GOOD_SEARCH}```")
    chat(client, improve["prompt"])
    assert "Current code of web_search.py:" in fake_ollama.last_prompt
    assert "        except:\n" in fake_ollama.last_prompt  # the model sees the old code it must fix

    # 3. The user approves; the file is backed up and replaced
    applied = client.post("/api/upgrade/apply", json={
        "file": "web_search.py", "code": GOOD_SEARCH, "description": "Add docstrings, catch specific errors"
    }).get_json()
    assert applied["success"], applied
    assert (sandbox / "web_search.py").read_text(encoding="utf-8") == GOOD_SEARCH
    assert len(routes_improve.upgrade_manager.list_backups()) == 1

    # 4. The measured quality really went up
    after = routes_improve.analyzer.analyze_all_files()
    assert len(after["web_search.py"]["issues"]) < issues_before
    assert routes_improve.analyzer.get_code_quality_score(after) > score_before

    # 5. The upgraded module still works
    spec = importlib.util.spec_from_file_location("upgraded_search", sandbox / "web_search.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: FakeResponse({"AbstractText": "It works"}))
    assert module.WebSearcher().search("x") == "It works"

    # 6. The next Auto-Improve remembers what was already done
    next_prompt = client.get("/api/self/improvement-prompt").get_json()["prompt"]
    assert "- web_search.py: Add docstrings, catch specific errors" in next_prompt


def test_bad_upgrade_is_refused_and_can_be_rolled_back(client, sandbox):
    # An upgrade written from memory that drops the class is refused
    refused = client.post("/api/upgrade/apply", json={"file": "web_search.py", "code": "def search(q):\n    return q\n"})
    assert refused.get_json()["success"] is False and "WebSearcher" in refused.get_json()["message"]
    # A good one is applied, then undone
    client.post("/api/upgrade/apply", json={"file": "web_search.py", "code": GOOD_SEARCH})
    backup = client.get("/api/upgrade/backups").get_json()["backups"][0]
    assert client.post("/api/upgrade/rollback", json={"backup_path": backup}).get_json()["success"]
    assert (sandbox / "web_search.py").read_text(encoding="utf-8") == BAD_SEARCH
