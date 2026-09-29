"""Model picker (download, switch, unload) and hiding the reasoning of 'thinking' models."""
import json
import time

import pytest

import web_server as ws
import services as sv
from llm_interface import LLMError, LLMInterface, ThinkFilter, strip_thinking
from model_manager import ModelManager, same_model


def wait_for(condition, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


# ---------------- thinking

@pytest.mark.parametrize("text,visible", [
    ("<think>hmm</think>\n\nThe answer is 4.", "The answer is 4."),
    ("<think>still thinking", ""),
    ("no tags here", "no tags here"),
    ("a < b and <thing>", "a < b and <thing>"),
])
def test_strip_thinking(text, visible):
    assert strip_thinking(text) == visible


@pytest.mark.parametrize("tokens,visible", [
    (["<think>", "a", "</think>", "Hi"], "Hi"),
    (["<th", "ink>x</th", "ink>", "\n\n", " Hello", " <b>"], "Hello <b>"),
    (["Hello ", "world"], "Hello world"),
    (["a < b", " and <thin", "g>"], "a < b and <thing>"),
    (["<think>never closed"], ""),
])
def test_think_filter(tokens, visible):
    f = ThinkFilter()
    assert "".join(f.feed(t) for t in tokens) + f.flush() == visible


def test_non_streamed_answers_hide_thinking(fake_ollama):
    fake_ollama.reply = "<think>Let me add 2 and 2.</think>\n\nIt is 4."
    llm = LLMInterface("m", 0.5, 100, fake_ollama.url)
    assert llm.generate_response("2+2?") == "It is 4."


# ---------------- model management in LLMInterface

def test_list_running_load_unload(fake_ollama):
    llm = LLMInterface("mistral", 0.5, 100, fake_ollama.url)
    assert llm.list_models() == [{"name": "mistral:latest", "size": 4_100_000_000}]
    assert llm.running_models() == []
    assert llm.load_model("mistral") is True and llm.running_models() == ["mistral"]
    assert llm.unload_model("mistral") is True
    assert fake_ollama.unloaded == ["mistral"] and llm.running_models() == []
    assert fake_ollama.requests == []  # load/unload aren't chat requests


def test_pull_model(fake_ollama):
    llm = LLMInterface("mistral", 0.5, 100, fake_ollama.url)
    statuses = [p["status"] for p in llm.pull_model("qwen3:8b")]
    assert statuses == ["pulling manifest", "downloading", "success"]
    assert "qwen3:8b" in [m["name"] for m in llm.list_models()]
    fake_ollama.pull_error = "pull model manifest: file does not exist"
    with pytest.raises(LLMError, match="does not exist"):
        list(llm.pull_model("not-a-model"))


def test_model_calls_when_ollama_is_down():
    llm = LLMInterface("mistral", 0.5, 100, "http://127.0.0.1:9")
    with pytest.raises(LLMError, match="Can't connect"):
        llm.list_models()
    with pytest.raises(LLMError):
        list(llm.pull_model("x"))
    assert llm.unload_model("mistral") is False


# ---------------- ModelManager

@pytest.fixture
def manager(fake_ollama, tmp_path):
    llm = LLMInterface("mistral", 0.5, 100, fake_ollama.url)
    return ModelManager(llm, tmp_path / "user_settings.json")


def test_same_model():
    assert same_model("mistral", "mistral:latest")
    assert same_model("qwen3:8b", "qwen3:8b") and not same_model("qwen3:8b", "qwen3:4b")
    assert same_model("hf.co/user/repo", "hf.co/user/repo:latest")


def test_switch_to_downloaded_model_unloads_previous(manager, fake_ollama):
    fake_ollama.models.append("llama3.2:latest")
    manager.llm.load_model("mistral")
    result = manager.select("llama3.2")
    assert result["action"] == "switched" and "mistral was unloaded" in result["message"]
    assert manager.llm.model_name == "llama3.2"
    assert fake_ollama.unloaded == ["mistral"]
    assert wait_for(lambda: "llama3.2" in fake_ollama.loaded)  # new model loaded in the background
    assert json.loads(manager.settings_path.read_text())["model"] == "llama3.2"
    assert manager.select("llama3.2:latest")["action"] == "unchanged"


def test_missing_model_is_downloaded_then_used(manager, fake_ollama):
    result = manager.select("qwen3:8b")
    assert result["action"] == "downloading"
    assert wait_for(lambda: manager.download["done"])
    assert manager.download["status"] == "success" and manager.download["error"] is None
    assert manager.llm.model_name == "qwen3:8b" and fake_ollama.pulled == ["qwen3:8b"]
    assert fake_ollama.unloaded == ["mistral"]
    status = manager.status()
    assert status["current"] == "qwen3:8b" and status["current_installed"]
    assert any(m["name"] == "qwen3:8b" for m in status["installed"])


def test_failed_download_keeps_current_model(manager, fake_ollama):
    fake_ollama.pull_error = "file does not exist"
    manager.select("made-up-model")
    assert wait_for(lambda: manager.download["done"])
    assert manager.download["status"] == "failed" and "does not exist" in manager.download["error"]
    assert manager.llm.model_name == "mistral" and fake_ollama.unloaded == []


def test_only_one_download_at_a_time(manager, fake_ollama):
    manager.download = {"model": "big", "status": "downloading", "completed": 1, "total": 9,
                        "done": False, "error": None}
    with pytest.raises(ValueError, match="still downloading"):
        manager.select("llama3.2")


@pytest.mark.parametrize("bad", ["", "  ", "rm -rf /", "../../etc", "a" * 300, "name with spaces", "-flag"])
def test_invalid_names(manager, bad):
    with pytest.raises(ValueError):
        manager.select(bad)


def test_status_when_ollama_is_down(tmp_path):
    manager = ModelManager(LLMInterface("mistral", 0.5, 100, "http://127.0.0.1:9"), tmp_path / "s.json")
    status = manager.status()
    assert status["current"] == "mistral" and status["installed"] == [] and "Can't connect" in status["error"]
    assert status["suggestions"] and status["current_installed"] is False


def test_saved_choice_is_read_by_config(tmp_path, monkeypatch):
    import config
    settings = tmp_path / "user_settings.json"
    monkeypatch.setattr(config, "USER_SETTINGS_PATH", settings)
    assert config._saved_setting("model") is None
    settings.write_text('{"model": "qwen3:4b", "other": 1}', encoding="utf-8")
    assert config._saved_setting("model") == "qwen3:4b"
    settings.write_text("[1, 2]", encoding="utf-8")
    assert config._saved_setting("model") is None


# ---------------- web endpoints and streaming

@pytest.fixture
def client(fake_ollama):
    original = sv.llm_interface.model_name
    sv.model_manager.download = None
    sv.conversation_history.start_new_conversation()
    yield ws.app.test_client()
    sv.llm_interface.model_name = original
    sv.model_manager.download = None


def sse_events(response):
    return [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data: ")]


def test_models_endpoint(client, fake_ollama):
    data = client.get("/api/models").get_json()
    assert data["success"] and data["current"] == sv.llm_interface.model_name
    assert data["installed"][0]["name"] == "mistral:latest" and len(data["suggestions"]) >= 4


def test_select_endpoint_download_and_switch(client, fake_ollama):
    response = client.post("/api/models/select", json={"model": "llama3.2"}).get_json()
    assert response["success"] and response["action"] == "downloading"
    assert wait_for(lambda: client.get("/api/models").get_json()["download"]["done"])
    data = client.get("/api/models").get_json()
    assert data["current"] == "llama3.2" and data["download"]["status"] == "success"
    client.post("/api/chat", json={"message": "hi"})
    assert fake_ollama.requests[-1]["model"] == "llama3.2"  # chats use the new model
    back = client.post("/api/models/select", json={"model": "mistral"}).get_json()
    assert back["action"] == "switched" and "llama3.2" in fake_ollama.unloaded


def test_select_endpoint_rejects_bad_names(client):
    response = client.post("/api/models/select", json={"model": "bad name!"})
    assert response.status_code == 400 and "valid model name" in response.get_json()["error"]


def test_streaming_hides_thinking(client, fake_ollama):
    fake_ollama.reply = "<think>The user wants a greeting.</think> Hello there!"
    events = sse_events(client.post("/api/chat-stream", json={"message": "greet me"}))
    assert {"thinking": True} in events
    assert "".join(e.get("token", "") for e in events) == "Hello there!"
    assert sv.conversation_history.get_all_messages(limit=1)[0]["content"] == "Hello there!"


def test_thinking_model_can_still_search(client, fake_ollama, monkeypatch):
    monkeypatch.setattr(sv.web_searcher, "search", lambda q, num_results=5: f"RESULTS {q}")
    fake_ollama.replies = ["<think>I don't know this.</think> SEARCH: population of Vilnius",
                           "<think>Found it.</think> About 600,000 people."]
    events = sse_events(client.post("/api/chat-stream", json={"message": "How many people live in Vilnius?"}))
    assert {"searching": "population of Vilnius"} in events
    assert "".join(e.get("token", "") for e in events) == "About 600,000 people."
    data = client.post("/api/chat", json={"message": "again"}).get_json()  # non-streaming path too
    assert "SEARCH" not in data["response"]
