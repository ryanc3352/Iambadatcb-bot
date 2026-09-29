"""Shared test setup.

- All app data goes to a temporary DATA_DIR, so tests never touch real chats or files.
- A fake Ollama server (same HTTP API as the real one) runs on a random local port.
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))


class FakeOllama:
    """Tiny stand-in for Ollama's /api/tags and /api/generate."""

    def __init__(self):
        self.requests = []
        self.reset()
        handler = self._make_handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reset(self, reply="Hello from the fake model!", status=200, error=None, delay=0, stream_error=None):
        self.reply, self.status, self.error = reply, status, error
        self.delay, self.stream_error = delay, stream_error
        self.replies = []  # if set, each request takes the next reply from here
        self.pulled, self.pull_error = [], None
        self.models = ["mistral:latest"]        # downloaded
        self.loaded, self.unloaded = [], []     # in memory / unloaded via keep_alive=0
        self.token_delay = self.pull_delay = 0  # slow streaming/downloads down (for manual UI tests)
        self.requests.clear()

    def next_reply(self):
        return self.replies.pop(0) if self.replies else self.reply

    @property
    def last_prompt(self):
        return self.requests[-1]["prompt"] if self.requests else None

    def _make_handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send_json(self, status, data):
                body = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send_json(200, {"models": [{"name": m, "size": 4_100_000_000} for m in fake.models]})
                elif self.path == "/api/ps":
                    self._send_json(200, {"models": [{"name": m} for m in fake.loaded]})
                else:
                    self._send_json(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/pull":
                    fake.pulled.append(payload["name"])
                    self.send_response(200)
                    self.end_headers()
                    lines = [{"status": "pulling manifest"}, {"status": "downloading", "completed": 50, "total": 100}]
                    lines.append({"error": fake.pull_error} if fake.pull_error else {"status": "success"})
                    for line in lines:
                        self.wfile.write((json.dumps(line) + "\n").encode())
                        self.wfile.flush()
                        time.sleep(fake.pull_delay)
                    if not fake.pull_error:
                        name = payload["name"]
                        fake.models.append(name if ":" in name else f"{name}:latest")
                    return
                if self.path == "/api/generate" and "prompt" not in payload:
                    # load (no prompt) or unload (keep_alive=0) a model
                    model = payload["model"]
                    if payload.get("keep_alive") == 0:
                        fake.unloaded.append(model)
                        fake.loaded = [m for m in fake.loaded if m.split(":")[0] != model.split(":")[0]]
                        self._send_json(200, {"model": model, "done": True, "done_reason": "unload"})
                    else:
                        fake.loaded.append(model)
                        self._send_json(200, {"model": model, "done": True, "done_reason": "load"})
                    return
                fake.requests.append(payload)
                if payload["model"] not in fake.loaded:  # answering loads the model, like Ollama
                    fake.loaded.append(payload["model"])
                if fake.delay:
                    time.sleep(fake.delay)
                if fake.status != 200:
                    self._send_json(fake.status, {"error": fake.error or "fake failure"})
                    return
                reply = fake.next_reply()
                if not payload.get("stream"):
                    self._send_json(200, {"response": reply, "done": True})
                    return
                # Streaming: one JSON object per line, like Ollama
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                words = reply.split(" ")
                for i, word in enumerate(words):
                    token = word if i == 0 else " " + word
                    self.wfile.write((json.dumps({"response": token, "done": False}) + "\n").encode())
                    self.wfile.flush()
                    time.sleep(fake.token_delay)
                    if fake.stream_error:
                        self.wfile.write((json.dumps({"error": fake.stream_error}) + "\n").encode())
                        return
                self.wfile.write((json.dumps({"response": "", "done": True}) + "\n").encode())

        return Handler


# Set up before any app module is imported (config reads these at import time)
FAKE_OLLAMA = FakeOllama()
DATA_DIR = Path(tempfile.mkdtemp(prefix="ai_test_data_"))
os.environ["DATA_DIR"] = str(DATA_DIR)
os.environ["OLLAMA_URL"] = FAKE_OLLAMA.url
os.environ.setdefault("MODEL_TIMEOUT", "30")


@pytest.fixture(autouse=True)
def no_real_internet(request, monkeypatch):
    """Keep tests fast and repeatable: no real web searches or weather lookups
    (except in the tests that mock those modules' network calls themselves)."""
    if "test_weather_and_search" in request.node.nodeid:
        return
    import weather_provider
    import web_search
    monkeypatch.setattr(web_search.WebSearcher, "search", lambda self, query, num_results=5: "No results found")
    monkeypatch.setattr(weather_provider.WeatherProvider, "find_place", lambda self, place: None)


@pytest.fixture
def fake_ollama():
    FAKE_OLLAMA.reset()
    yield FAKE_OLLAMA
    FAKE_OLLAMA.reset()


class FakeResponse:
    """Minimal stand-in for requests.Response used when mocking requests.get."""

    def __init__(self, data=None, status=200):
        self._data, self.status_code = data, status
        self.text = repr(data)

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error")
