"""End-to-end tests of every HTTP endpoint (Flask test client + fake Ollama)."""
import io
import re
import json
import zipfile

import pytest

import web_server as ws
import config
import prompts
import routes_chat
import routes_files
import routes_improve
import services as sv
from upgrade_manager import UpgradeManager


@pytest.fixture
def client(fake_ollama):
    sv.conversation_history.start_new_conversation()
    return ws.app.test_client()


def post(client, url, data=None):
    return client.post(url, json=data if data is not None else {})


def sse_events(response):
    return [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
            if line.startswith("data: ")]


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    buffer.seek(0)
    return buffer


# ---------------- page

def test_index_and_static(client):
    page = client.get("/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Add Folder" in html and "My Files" in html and "model-btn" in html and "logs-btn" in html
    scripts = re.findall(r"/static/js/([\w-]+\.js)", html)
    assert scripts[0] == "core.js" and scripts[-1] == "main.js" and len(scripts) >= 5
    for script in scripts:
        assert client.get(f"/static/js/{script}").status_code == 200
    assert client.get("/static/css/style.css").status_code == 200


def test_unknown_route_is_json_404(client):
    response = client.get("/api/nope")
    assert response.status_code == 404 and "error" in response.get_json()


# ---------------- chat

def test_chat_roundtrip_and_prompt(client, fake_ollama):
    before = sv.conversation_history.count_messages()
    response = post(client, "/api/chat", {"message": "hello there"})
    assert response.status_code == 200
    assert response.get_json() == {"response": "Hello from the fake model!", "has_code": False, "code": None,
                                   "packages": [], "files": []}
    assert sv.conversation_history.count_messages() == before + 2

    prompt = fake_ollama.last_prompt
    assert prompt.startswith(config.SYSTEM_PROMPT.strip()[:40])
    assert "Current date and time:" in prompt
    assert prompt.endswith("User: hello there\nAssistant:")
    assert prompt.count("hello there") == 1  # not repeated in 'Recent conversation'


def test_context_and_new_conversation(client, fake_ollama):
    post(client, "/api/chat", {"message": "my cat is called Mochi"})
    post(client, "/api/chat", {"message": "what is my cat called?"})
    assert "User: my cat is called Mochi" in fake_ollama.last_prompt

    assert post(client, "/api/conversations/new").get_json() == {"success": True}
    post(client, "/api/chat", {"message": "fresh start"})
    assert "Recent conversation" not in fake_ollama.last_prompt


def test_past_chats(client, fake_ollama, monkeypatch):
    forgotten = []
    monkeypatch.setattr(routes_chat.memory, "forget", forgotten.extend)
    post(client, "/api/conversations/new")
    post(client, "/api/chat", {"message": "my dog is called Rex"})
    first = client.get("/api/conversations").get_json()["current"]
    post(client, "/api/conversations/new")
    post(client, "/api/chat", {"message": "<b>second</b> chat"})

    data = client.get("/api/conversations").get_json()
    second = data["current"]
    assert [c["title"] for c in data["conversations"][:2]] == ["<b>second</b> chat", "my dog is called Rex"]
    chat = client.get(f"/api/conversations/{first}").get_json()
    assert [(m["role"], m["content"]) for m in chat["messages"]] == [
        ("user", "my dog is called Rex"), ("assistant", "Hello from the fake model!")]

    # Reopen the first chat and carry on: its messages are the context again
    opened = post(client, f"/api/conversations/{first}/open").get_json()
    assert opened["success"] and len(opened["messages"]) == 2
    post(client, "/api/chat", {"message": "what is my dog called?"})
    assert "User: my dog is called Rex" in fake_ollama.last_prompt
    assert "second" not in fake_ollama.last_prompt

    assert post(client, f"/api/conversations/{first}/rename", {"title": "Dogs"}).get_json() == {"success": True}
    assert client.get("/api/conversations").get_json()["conversations"][0]["title"] == "Dogs"
    assert post(client, f"/api/conversations/{first}/rename", {}).status_code == 400

    # Deleting forgets the chat's messages in long-term memory too
    deleted = client.delete(f"/api/conversations/{second}").get_json()
    assert deleted == {"success": True, "current": first}
    assert len(forgotten) == 2
    deleted = client.delete(f"/api/conversations/{first}").get_json()
    assert deleted["current"] not in (first, second)
    ids = [c["id"] for c in client.get("/api/conversations").get_json()["conversations"]]
    assert first not in ids and second not in ids

    for response in (client.get(f"/api/conversations/{first}"), post(client, f"/api/conversations/{first}/open"),
                     post(client, f"/api/conversations/{first}/rename", {"title": "x"}),
                     client.delete(f"/api/conversations/{first}")):
        assert response.status_code == 404 and response.get_json()["success"] is False


def test_chat_validation(client):
    assert post(client, "/api/chat", {"message": "   "}).status_code == 400
    assert client.post("/api/chat", data="hello", content_type="text/plain").status_code == 400
    assert client.post("/api/chat", json=["not", "an", "object"]).status_code == 400


def test_chat_when_ollama_fails(client, fake_ollama):
    fake_ollama.status, fake_ollama.error = 404, "model 'mistral' not found"
    before = sv.conversation_history.count_messages()
    response = post(client, "/api/chat", {"message": "hi"})
    assert response.status_code == 503 and "not found" in response.get_json()["error"]
    assert sv.conversation_history.count_messages() == before  # errors are not saved as replies


def test_chat_runnable_code_but_not_upgrades(client, fake_ollama):
    fake_ollama.reply = "Run this:\n```python\nprint(1)\n```"
    data = post(client, "/api/chat", {"message": "code please"}).get_json()
    assert data["has_code"] is True and data["code"] == "print(1)"

    fake_ollama.reply = "UPGRADE_REQUEST:\nFILE: memory.py\nDESCRIPTION: x\nCODE:\n```python\nx = 1\n```"
    assert post(client, "/api/chat", {"message": "upgrade"}).get_json()["has_code"] is False


def test_stream(client, fake_ollama):
    fake_ollama.reply = "one two three"
    before = sv.conversation_history.count_messages()
    events = sse_events(post(client, "/api/chat-stream", {"message": "count"}))
    assert "".join(e.get("token", "") for e in events) == "one two three"
    assert events[-1] == {"done": True, "has_code": False, "code": None, "has_upgrade": False,
                          "packages": [], "files": [], "error": None}
    assert sv.conversation_history.count_messages() == before + 2


def test_stream_code_and_upgrade_flags(client, fake_ollama):
    fake_ollama.reply = "```python\nprint(2)\n```"
    done = sse_events(post(client, "/api/chat-stream", {"message": "x"}))[-1]
    assert done["has_code"] and done["code"] == "print(2)"
    fake_ollama.reply = "UPGRADE_REQUEST: FILE: a.py DESCRIPTION: b CODE: ```python\nx=1\n```"
    done = sse_events(post(client, "/api/chat-stream", {"message": "x"}))[-1]
    assert done["has_upgrade"] and not done["has_code"]


@pytest.mark.parametrize("setup", [{"stream_error": "GPU fell over"}, {"status": 500, "error": "GPU fell over"}])
def test_stream_errors_are_reported_not_saved(client, fake_ollama, setup):
    for key, value in setup.items():
        setattr(fake_ollama, key, value)
    before = sv.conversation_history.count_messages()
    done = sse_events(post(client, "/api/chat-stream", {"message": "x"}))[-1]
    assert done["done"] and "GPU fell over" in done["error"] and done["has_code"] is False
    assert sv.conversation_history.count_messages() == before


def test_stream_validation(client):
    assert post(client, "/api/chat-stream", {"message": ""}).status_code == 400


# ---------------- live data routing

@pytest.fixture
def live(monkeypatch):
    calls = []
    monkeypatch.setattr(sv.weather_provider, "get_weather", lambda p: calls.append(("now", p)) or f"WEATHER-NOW {p}")
    monkeypatch.setattr(sv.weather_provider, "get_weather_for_tomorrow",
                        lambda p: calls.append(("tomorrow", p)) or f"WEATHER-TOMORROW {p}")
    monkeypatch.setattr(sv.web_searcher, "search", lambda q, num_results=5: calls.append(("search", q)) or "SEARCH-RESULTS")
    return calls


def test_weather_goes_into_prompt(client, fake_ollama, live):
    post(client, "/api/chat", {"message": "What's the weather in Paris tomorrow?"})
    assert live == [("tomorrow", "Paris")] and "WEATHER-TOMORROW Paris" in fake_ollama.last_prompt
    post(client, "/api/chat", {"message": "Is it cloudy in Cape Town right now?"})
    assert live[-1] == ("now", "Cape Town")


def test_weather_without_place_and_non_weather(client, fake_ollama, live):
    post(client, "/api/chat", {"message": "I love the rain"})
    post(client, "/api/chat", {"message": "Write a script that gets the weather for a city"})
    post(client, "/api/chat", {"message": "I'm training a model on the brain"})
    assert live == []


def test_unknown_lowercase_place_adds_nothing(client, fake_ollama, monkeypatch):
    monkeypatch.setattr(sv.weather_provider, "get_weather", lambda p: f"❌ Could not find location: {p}")
    post(client, "/api/chat", {"message": "What weather is best for running?"})
    assert "Could not find" not in fake_ollama.last_prompt
    post(client, "/api/chat", {"message": "What's the weather in Pariss?"})  # capitalized: tell the model
    assert "❌ Could not find location: Pariss" in fake_ollama.last_prompt


def test_search_goes_into_prompt(client, fake_ollama, live):
    post(client, "/api/chat", {"message": "latest news about space"})
    assert live == [("search", "latest news about space")] and "SEARCH-RESULTS" in fake_ollama.last_prompt
    post(client, "/api/chat", {"message": "Plan a trip to Stockholm"})
    post(client, "/api/chat", {"message": "Show the current code and a recent change"})
    assert len(live) == 1


def test_live_data_errors_do_not_break_chat(client, fake_ollama, monkeypatch):
    def boom(place):
        raise RuntimeError("weather API down")
    monkeypatch.setattr(sv.weather_provider, "get_weather", boom)
    assert post(client, "/api/chat", {"message": "weather in Oslo"}).status_code == 200
    assert "(Search error: weather API down)" in fake_ollama.last_prompt


@pytest.mark.parametrize("question,place", [
    ("What is the weather in New York tomorrow?", "New York"),
    ("Is it sunny at the beach in Cape Town today", "Cape Town"),
    ("temperature in London right now?", "London"),
    ("weather for Paris, France this weekend", "Paris, France"),
    ("What's the weather like in the Netherlands", "Netherlands"),
    ("weather in london", "london"),
    ("Vilnius weather tomorrow", "Vilnius"),
    ("New York weather", "New York"),
    ("How is the weather Berlin", "Berlin"),
    ("What weather is best for running", "running"),  # not a place; see test below
    ("What weather is best", None),
    ("What temperature should I cook chicken at", None),
    ("weather for a city", None),
    ("I love rain", None),
])
def test_extract_location(question, place):
    assert prompts.extract_location(question) == place


def test_named_files_add_their_code(client, fake_ollama, monkeypatch):
    post(client, "/api/chat", {"message": "Please improve memory.py"})
    assert "Current code of memory.py:" in fake_ollama.last_prompt
    assert "def get_chroma_client" in fake_ollama.last_prompt
    post(client, "/api/chat", {"message": "Look at web_server.py"})
    assert "Current code of web_server.py:" in fake_ollama.last_prompt
    monkeypatch.setattr(prompts, "MAX_CODE_CONTEXT_CHARS", 100)
    post(client, "/api/chat", {"message": "Look at web_server.py"})
    assert "web_server.py is too large to show here" in fake_ollama.last_prompt
    post(client, "/api/chat", {"message": "memory is nice"})
    assert "Current code of" not in fake_ollama.last_prompt


# ---------------- tools

def run_code(client, body):
    """The events of a code run; the last one has the result."""
    return sse_events(post(client, "/api/execute-code", body))


def test_execute_code(client, monkeypatch):
    runs = client.get("/api/stats").get_json()["code_runs"]
    events = run_code(client, {"code": "print(6*7)", "run_id": "abc"})
    assert events[0] == {"run_id": "abc"}
    assert {"output": "42\n"} in events
    assert events[-1] == {"done": True, "success": True, "output": "42"}
    failed = run_code(client, {"code": "raise ValueError('bad')"})[-1]
    assert failed["success"] is False and "ValueError: bad" in failed["output"]
    assert client.get("/api/stats").get_json()["code_runs"] == runs + 2
    assert post(client, "/api/execute-code", {"code": ""}).status_code == 400
    monkeypatch.setattr(routes_chat, "ENABLE_CODE_EXECUTION", False)
    assert post(client, "/api/execute-code", {"code": "print(1)"}).status_code == 403


def test_execute_code_installs_packages_and_reads_answers(client, monkeypatch):
    installed = []
    monkeypatch.setattr(sv.code_executor, "install",
                        lambda packages, run_id, report: (installed.extend(packages), (True, ""))[1])
    done = run_code(client, {"code": "print(input())", "packages": ["requests", 5], "input": "hi"})[-1]
    assert done == {"done": True, "success": True, "output": "📦 Installed requests\nhi"}
    assert installed == ["requests"]


def test_run_saved_file(client):
    client.post("/api/files/save", json={"path": "game/utils.py", "content": "NAME = 'snake'"})
    client.post("/api/files/save", json={"path": "game/main.py", "content": "import utils\nprint(utils.NAME, input())"})
    done = run_code_at(client, "/api/run-file", {"path": "game/main.py", "input": "ok"})[-1]
    assert done == {"done": True, "success": True, "output": "snake ok"}
    client.post("/api/files/save", json={"path": "notes.txt", "content": "x"})
    assert post(client, "/api/run-file", {"path": "notes.txt"}).status_code == 400
    assert post(client, "/api/run-file", {"path": "../web_server.py"}).status_code == 403


def test_code_from_a_folder_chat_runs_in_that_folder(client, tmp_path):
    source = tmp_path / "proj"
    source.mkdir()
    (source / "data.txt").write_text("folder data")
    sv.folder_manager.add_folder(source, "proj")
    done = run_code(client, {"code": "print(open('data.txt').read())", "folder": "proj"})[-1]
    assert done["output"] == "folder data"
    assert post(client, "/api/execute-code", {"code": "print(1)", "folder": "nope"}).status_code == 404


def run_code_at(client, url, body):
    return sse_events(post(client, url, body))


def test_stop_code_when_nothing_runs(client):
    assert post(client, "/api/stop-code", {"run_id": "nope"}).get_json() == {"success": False}


def test_answers_offer_packages_with_code(client, fake_ollama):
    fake_ollama.reply = "Install:\n```bash\npip install requests\n```\nThen:\n```python\nimport requests\n```"
    data = post(client, "/api/chat", {"message": "get a web page"}).get_json()
    assert data["has_code"] and data["code"] == "import requests" and data["packages"] == ["requests"]


def test_history_and_stats(client):
    post(client, "/api/chat", {"message": "remember me"})
    history = client.get("/api/history?limit=2").get_json()
    assert history["success"] and len(history["messages"]) == 2
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    stats = client.get("/api/stats").get_json()
    assert stats["success"] and stats["message_count"] >= 2
    assert set(stats) == {"success", "message_count", "conversations", "files", "code_runs"}


# ---------------- knowledge base

def test_knowledge_base_endpoints(client, fake_ollama):
    upload = client.post("/api/knowledge-base/upload",
                         data={"file": (io.BytesIO(b"The spare key is under the red flowerpot."), "../../house.txt")},
                         content_type="multipart/form-data")
    assert upload.get_json()["success"], upload.get_json()
    assert "house.txt" in client.get("/api/knowledge-base/list").get_json()["documents"]

    post(client, "/api/chat", {"message": "where is the spare key?"})
    assert "Document Context" in fake_ollama.last_prompt and "flowerpot" in fake_ollama.last_prompt

    assert client.delete("/api/knowledge-base/delete/house.txt").get_json()["success"]
    assert client.delete("/api/knowledge-base/delete/house.txt").get_json()["success"] is False


def test_knowledge_base_upload_errors(client):
    bad_type = client.post("/api/knowledge-base/upload", data={"file": (io.BytesIO(b"MZ"), "tool.exe")},
                           content_type="multipart/form-data")
    assert bad_type.get_json()["success"] is False
    assert client.post("/api/knowledge-base/upload", data={}, content_type="multipart/form-data").status_code == 400
    weird = client.post("/api/knowledge-base/upload", data={"file": (io.BytesIO(b"x"), "../..")},
                        content_type="multipart/form-data")
    assert weird.status_code == 400


def test_upload_too_large_is_json_413(client, monkeypatch):
    monkeypatch.setitem(ws.app.config, "MAX_CONTENT_LENGTH", 100)
    response = client.post("/api/knowledge-base/upload", data={"file": (io.BytesIO(b"x" * 500), "big.txt")},
                           content_type="multipart/form-data")
    assert response.status_code == 413 and "error" in response.get_json()


# ---------------- upgrades (against a temporary copy, never the real files)

@pytest.fixture
def temp_upgrades(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "memory.py").write_text("def keep():\n    return 1\n")
    manager = UpgradeManager(project, tmp_path / "backups", allowed_files=["memory.py"])
    monkeypatch.setattr(routes_improve, "upgrade_manager", manager)
    return project


def test_upgrade_flow(client, temp_upgrades):
    new_code = "def keep():\n    return 2\n\n\ndef added():\n    return 3\n"
    applied = post(client, "/api/upgrade/apply", {"file": "memory.py", "code": new_code, "description": "v2"}).get_json()
    assert applied == {"success": True, "message": "✅ Upgraded memory.py", "requires_restart": True}
    assert (temp_upgrades / "memory.py").read_text() == new_code

    dropped = post(client, "/api/upgrade/apply", {"file": "memory.py", "code": "x = 1\n"}).get_json()
    assert dropped["success"] is False and "nothing in the new code fits" in dropped["message"]
    assert post(client, "/api/upgrade/apply", {"file": "memory.py", "code": " "}).status_code == 400

    history = client.get("/api/upgrade/history").get_json()["history"]
    backups = client.get("/api/upgrade/backups").get_json()["backups"]
    assert history[-1]["description"] == "v2" and len(backups) == 1
    rolled = post(client, "/api/upgrade/rollback", {"backup_path": backups[0]}).get_json()
    assert rolled["success"] and (temp_upgrades / "memory.py").read_text() == "def keep():\n    return 1\n"
    assert post(client, "/api/upgrade/rollback", {}).status_code == 400


def test_upgrade_disabled(client, temp_upgrades, monkeypatch):
    monkeypatch.setattr(routes_improve, "ENABLE_SELF_IMPROVEMENT", False)
    response = post(client, "/api/upgrade/apply", {"file": "memory.py", "code": "def keep(): pass"})
    assert response.status_code == 403


# ---------------- folders

def upload_zip(client, files, name="proj", filename="proj.zip"):
    return client.post("/api/folders/upload",
                       data={"folder": (make_zip(files), filename), "folder_name": name},
                       content_type="multipart/form-data")


def test_folder_flow(client, fake_ollama):
    response = upload_zip(client, {"proj/app.py": "print('app')\n", "proj/README.md": "# Read me\n",
                                   "../evil.txt": "zip slip"})
    assert response.get_json()["success"], response.get_json()
    folders = client.get("/api/folders/list").get_json()["folders"]
    assert any(f["name"] == "proj" and f["file_count"] == 3 for f in folders)

    files = client.get("/api/folders/proj/contents").get_json()["files"]
    assert {f["path"] for f in files} == {"proj/app.py", "proj/README.md", "evil.txt"}  # '..' was dropped
    assert post(client, "/api/folders/proj/file", {"file_path": "proj/app.py"}).get_json()["content"] == "print('app')\n"
    assert post(client, "/api/folders/proj/file", {"file_path": "../../x"}).status_code == 404
    assert post(client, "/api/folders/proj/file", {}).status_code == 400
    assert "Files: 3" in client.get("/api/folders/proj/summary").get_json()["summary"]

    chat = post(client, "/api/chat/with-folder", {"message": "what does app.py print?", "folder_name": "proj"})
    assert chat.get_json()["response"] == "Hello from the fake model!"
    assert "--- proj/app.py ---\nprint('app')" in fake_ollama.last_prompt

    assert client.delete("/api/folders/proj/delete").get_json()["success"]
    assert client.delete("/api/folders/proj/delete").status_code == 400
    assert client.get("/api/folders/proj/contents").status_code == 404


def test_folder_upload_errors(client, monkeypatch):
    assert upload_zip(client, {"a.txt": "x"}, filename="notes.txt").status_code == 400
    bad = client.post("/api/folders/upload", data={"folder": (io.BytesIO(b"not a zip"), "x.zip")},
                      content_type="multipart/form-data")
    assert bad.status_code == 400 and "valid ZIP" in bad.get_json()["error"]
    assert client.post("/api/folders/upload", data={}, content_type="multipart/form-data").status_code == 400
    monkeypatch.setattr(routes_files, "MAX_ZIP_FILES", 1)
    assert upload_zip(client, {"a.txt": "1", "b.txt": "2"}).status_code == 400
    monkeypatch.setattr(routes_files, "MAX_ZIP_FILES", 5000)
    monkeypatch.setattr(routes_files, "MAX_ZIP_UNCOMPRESSED", 10)
    assert upload_zip(client, {"a.txt": "x" * 100}).status_code == 400


def test_folder_chat_errors(client):
    assert post(client, "/api/chat/with-folder", {"message": "hi", "folder_name": "missing"}).status_code == 404
    assert post(client, "/api/chat/with-folder", {"message": "", "folder_name": "x"}).status_code == 400
    assert post(client, "/api/chat/with-folder", {"message": "hi"}).status_code == 400


# ---------------- self-improvement and feedback

def test_self_endpoints(client):
    analysis = client.get("/api/self/analyze").get_json()
    assert analysis["success"] and 0 <= analysis["quality_score"] <= 100 and "CODE QUALITY" in analysis["report"]
    learning = client.get("/api/self/learning").get_json()
    assert learning["success"] and "LEARNING REPORT" in learning["report"]
    improvements = client.get("/api/self/improvements").get_json()
    assert improvements["success"] and improvements["count"] == len(improvements["proposals"])
    prompt = client.get("/api/self/improvement-prompt").get_json()
    assert prompt["success"] and "UPGRADE_REQUEST" in prompt["prompt"] and "Upgrades already applied" in prompt["prompt"]
    if prompt["target_file"]:
        assert prompt["prompt"].startswith(f"Improve {prompt['target_file']}.")
        assert prompt["target_file"] in config.UPGRADEABLE_FILES


def test_feedback(client):
    assert post(client, "/api/feedback", {"rating": 4, "feedback": "nice"}).get_json()["success"]
    post(client, "/api/feedback", {"rating": 99})
    assert sv.learner.learning_data["user_feedback"][-1]["rating"] == 5
    assert post(client, "/api/feedback", {"rating": "lots"}).status_code == 400


def test_calculator_results_go_into_prompt(client, fake_ollama):
    post(client, "/api/chat", {"message": "What is 1234*5678 and 15% of 240?"})
    assert "🧮 Calculator results" in fake_ollama.last_prompt
    assert "1234*5678 = 7006652" in fake_ollama.last_prompt and "15% of 240 = 36" in fake_ollama.last_prompt
    post(client, "/api/chat", {"message": "we need 5-10 people"})
    assert "Calculator results" not in fake_ollama.last_prompt


# ---------------- the model asks for a web search

@pytest.fixture
def searched(monkeypatch):
    queries = []
    monkeypatch.setattr(sv.web_searcher, "search", lambda q, num_results=5: queries.append(q) or f"RESULTS FOR {q}")
    return queries


def test_model_search_request_non_streaming(client, fake_ollama, searched):
    fake_ollama.replies = ["SEARCH: capital of Freedonia\n", "The capital is Fredville."]
    before = sv.conversation_history.count_messages()
    data = post(client, "/api/chat", {"message": "What is the capital of Freedonia?"}).get_json()
    assert data["response"] == "The capital is Fredville."
    assert searched == ["capital of Freedonia"]
    second_prompt = fake_ollama.requests[-1]["prompt"]
    assert "You asked to search the web for 'capital of Freedonia'" in second_prompt
    assert "RESULTS FOR capital of Freedonia" in second_prompt
    assert sv.conversation_history.get_all_messages(limit=1)[0]["content"] == "The capital is Fredville."
    assert sv.conversation_history.count_messages() == before + 2


def test_model_search_request_streaming(client, fake_ollama, searched):
    fake_ollama.replies = ["SEARCH: price of gold today", "Gold costs a lot."]
    events = sse_events(post(client, "/api/chat-stream", {"message": "How much is gold?"}))
    assert {"searching": "price of gold today"} in events
    assert "".join(e.get("token", "") for e in events) == "Gold costs a lot."
    assert searched == ["price of gold today"]


def test_model_searching_twice_gets_a_clear_message(client, fake_ollama, searched):
    fake_ollama.replies = ["SEARCH: a", "SEARCH: b"]
    data = post(client, "/api/chat", {"message": "hard question"}).get_json()
    assert data["response"] == "I searched the web for 'a' but couldn't find a clear answer."


@pytest.mark.parametrize("reply", ["Seattle is a city in Washington.", "SEA", "Search engines are useful."])
def test_normal_replies_that_look_like_search_stream_unchanged(client, fake_ollama, searched, reply):
    fake_ollama.reply = reply
    events = sse_events(post(client, "/api/chat-stream", {"message": "tell me"}))
    assert "".join(e.get("token", "") for e in events) == reply
    assert searched == []


def test_folder_chat_can_search(client, fake_ollama, searched):
    upload_zip(client, {"a.py": "print(1)"}, name="searchproj")
    fake_ollama.replies = ["SEARCH: python print docs", "print() writes text."]
    data = post(client, "/api/chat/with-folder", {"message": "what does a.py use?", "folder_name": "searchproj"}).get_json()
    assert data["response"] == "print() writes text." and searched == ["python print docs"]
    assert "--- a.py ---" in fake_ollama.requests[-1]["prompt"]  # folder context kept on the second pass
    client.delete("/api/folders/searchproj/delete")


# ---------------- local first, internet second

def test_local_documents_come_before_web_search(client, fake_ollama, live):
    client.post("/api/knowledge-base/upload",
                data={"file": (io.BytesIO(b"Latest team news: the team moved to the new office in Riga on Monday."),
                               "team_news.txt")},
                content_type="multipart/form-data")
    post(client, "/api/chat", {"message": "What is the latest news about our team?"})
    assert live == []                                   # answered from the local document
    assert "new office in Riga" in fake_ollama.last_prompt
    post(client, "/api/chat", {"message": "latest news about Mars rovers"})
    assert live == [("search", "latest news about Mars rovers")]  # nothing local: search online
    client.delete("/api/knowledge-base/delete/team_news.txt")


def test_prompt_tells_model_to_check_local_info_first(client, fake_ollama):
    post(client, "/api/chat", {"message": "hello"})
    assert "Only if the" in fake_ollama.last_prompt and "Never search for things the local information" in fake_ollama.last_prompt


def test_every_upgradeable_file_can_be_shown_to_the_model():
    """Auto-Improve shows the model a whole file, so none may grow past the limit."""
    for name in config.UPGRADEABLE_FILES:
        assert prompts.code_length(config.BASE_DIR / name) <= prompts.MAX_CODE_CONTEXT_CHARS, name


def test_windows_line_endings_dont_make_a_file_too_big(tmp_path, monkeypatch):
    """A Windows checkout has \\r\\n endings: more bytes, but the model gets the same text."""
    text = "x = 1\n" * (prompts.MAX_CODE_CONTEXT_CHARS // 6)
    (tmp_path / "calculator.py").write_text(text, encoding="utf-8", newline="\r\n")
    assert (tmp_path / "calculator.py").stat().st_size > prompts.MAX_CODE_CONTEXT_CHARS
    monkeypatch.setattr(routes_improve, "upgrade_manager", UpgradeManager(tmp_path, tmp_path / "b", ["calculator.py"]))
    monkeypatch.setattr(routes_improve, "UPGRADEABLE_FILES", ["calculator.py"])
    assert routes_improve.pick_improvement_target({"calculator.py": {"issues": ["x"]}}) == "calculator.py"


# --- Only requests addressed to this PC (DNS rebinding) ---------------------------

@pytest.mark.parametrize("host", ["127.0.0.1:5000", "localhost:5000", "LOCALHOST", "[::1]:5000", "192.168.1.20:5000"])
def test_requests_to_this_pc_are_answered(client, host):
    assert client.get("/", base_url=f"http://{host}/").status_code == 200


@pytest.mark.parametrize("host", ["evil.example.com", "localhost.evil.com:5000", "127.0.0.1.nip.io:5000"])
def test_requests_for_other_names_are_refused(client, host):
    """A web page can point its own domain at 127.0.0.1 to reach this app, which can run code."""
    assert client.get("/", base_url=f"http://{host}/").status_code == 403
    response = client.post("/api/execute-code", json={"code": "print(1)"}, base_url=f"http://{host}/")
    assert response.status_code == 403 and "print" not in response.get_data(as_text=True)


def test_extra_host_names_can_be_allowed(client, monkeypatch):
    monkeypatch.setattr(ws, "ALLOWED_HOSTS", ["my-pc.local"])
    assert client.get("/", base_url="http://my-pc.local:5000/").status_code == 200
