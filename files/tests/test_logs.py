"""The 🐞 logs button: the last few minutes of the app's log, with versions and settings."""
import logging
from datetime import datetime

import web_server as ws
import config
from app_logging import recent_lines


def test_recent_lines_keeps_the_last_minutes_and_tracebacks(tmp_path):
    (tmp_path / "app.log.1").write_text("2026-09-29 11:50:00 INFO a: old\n"
                                        "2026-09-29 11:56:00 INFO a: rotated but recent\n", encoding="utf-8")
    (tmp_path / "app.log").write_text("2026-09-29 11:57:00 ERROR a: boom\nTraceback (most recent call last):\n"
                                      "  File \"x.py\"\n2026-09-29 12:00:00 INFO a: now\n", encoding="utf-8")
    assert recent_lines(tmp_path, 5, now=datetime(2026, 9, 29, 12, 0, 30)) == [
        "2026-09-29 11:56:00 INFO a: rotated but recent", "2026-09-29 11:57:00 ERROR a: boom",
        "Traceback (most recent call last):", "  File \"x.py\"", "2026-09-29 12:00:00 INFO a: now"]
    assert recent_lines(tmp_path / "missing", 5) == []


def test_report_has_the_conversation_versions_and_settings(fake_ollama):
    client = ws.app.test_client()
    fake_ollama.reply = "Why did the chicken cross the road?"
    client.post("/api/chat", json={"message": "tell me a joke"})
    report = client.get("/api/logs").get_json()["report"]
    assert report.startswith("AI Assistant logs: the last 5 minutes")
    assert "Question: tell me a joke" in report and "Why did the chicken cross the road?" in report
    assert "Python" in report and "App files dated" in report
    assert "(Ollama running)" in report and "(can write: yes)" in report
    assert "the last 60 minutes" in client.get("/api/logs?minutes=999").get_json()["report"]
    assert "the last 5 minutes" in client.get("/api/logs?minutes=abc").get_json()["report"]


def test_problems_are_logged(fake_ollama):
    client = ws.app.test_client()
    client.post("/api/files/save", json={"path": "a.txt", "content": "x"})
    fake_ollama.reply = "I can't create files, but you can paste this into a file:\n```\nhello\n```"
    client.post("/api/chat", json={"message": "make a file that says hello"})
    report = client.get("/api/logs").get_json()["report"]
    assert "Saved file a.txt (1 characters)" in report
    assert "Offered to save: notes" in report


def test_routine_requests_and_colour_codes_are_left_out():
    server = logging.getLogger("werkzeug")
    server.info('127.0.0.1 - - [x] "GET /api/stats HTTP/1.1" 200 -')
    server.info('127.0.0.1 - - [x] "\x1b[36mGET /static/a.js HTTP/1.1\x1b[0m" 304 -')
    server.info('127.0.0.1 - - [x] "\x1b[33mPOST /api/chat HTTP/1.1\x1b[0m" 500 -')
    lines = "\n".join(recent_lines(config.LOGS_PATH, 1))
    assert "GET /api/stats" not in lines and "GET /static/a.js" not in lines
    assert '"POST /api/chat HTTP/1.1" 500 -' in lines and "\x1b" not in lines
