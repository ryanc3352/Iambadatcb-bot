"""The one-click launcher (start.py). Creating .venv itself is checked by the CI setup step."""
import subprocess

import pytest

import start


def test_read_settings(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# my settings\nMODEL_NAME='qwen3:8b'\nPORT=6000\nOTHER=x\nHOST = 0.0.0.0\n", encoding="utf-8")
    settings = start.read_settings(env, environ={"PORT": "7000", "DATA_DIR": str(tmp_path)})
    assert settings == {"MODEL_NAME": "qwen3:8b", "OLLAMA_URL": "http://localhost:11434",
                        "HOST": "0.0.0.0", "PORT": "7000", "DATA_DIR": str(tmp_path)}
    assert start.read_settings(tmp_path / "missing.env", environ={"DATA_DIR": str(tmp_path)})["MODEL_NAME"] == "mistral"


def test_model_picked_in_the_app_wins(tmp_path):
    (tmp_path / "user_settings.json").write_text('{"model": "llama3.2"}', encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("MODEL_NAME=qwen3:8b\n", encoding="utf-8")
    assert start.read_settings(env, environ={"DATA_DIR": str(tmp_path)})["MODEL_NAME"] == "llama3.2"
    (tmp_path / "user_settings.json").write_text("{broken", encoding="utf-8")
    assert start.read_settings(env, environ={"DATA_DIR": str(tmp_path)})["MODEL_NAME"] == "qwen3:8b"


def test_model_installed():
    assert start.model_installed(["mistral:latest"], "mistral")
    assert start.model_installed(["qwen3:8b"], "qwen3:8b")
    assert not start.model_installed(["qwen3:4b"], "qwen3:8b")


def test_ollama_models(fake_ollama):
    assert start.ollama_models(fake_ollama.url) == ["mistral:latest"]
    assert start.ollama_models("http://127.0.0.1:9") is None


def test_ensure_ollama_with_model_present(fake_ollama):
    assert start.ensure_ollama({"OLLAMA_URL": fake_ollama.url, "MODEL_NAME": "mistral"}) is True
    assert fake_ollama.pulled == []


def test_ensure_ollama_downloads_missing_model(fake_ollama, capsys):
    assert start.ensure_ollama({"OLLAMA_URL": fake_ollama.url, "MODEL_NAME": "qwen3:8b"}) is True
    assert fake_ollama.pulled == ["qwen3:8b"]
    assert "50%" in capsys.readouterr().out


def test_pull_error_is_reported(fake_ollama):
    fake_ollama.pull_error = "file does not exist"
    with pytest.raises(RuntimeError, match="file does not exist"):
        start.pull_model(fake_ollama.url, "nonsense-model")


def test_ensure_ollama_when_not_installed(monkeypatch, capsys):
    monkeypatch.setattr(start.shutil, "which", lambda name: None)
    assert start.ensure_ollama({"OLLAMA_URL": "http://127.0.0.1:9", "MODEL_NAME": "mistral"}) is False
    assert "ollama.com/download" in capsys.readouterr().out


def test_browser_url_and_open(fake_ollama, monkeypatch):
    assert start.browser_url({"HOST": "0.0.0.0", "PORT": "5000"}) == "http://127.0.0.1:5000"
    assert start.browser_url({"HOST": "127.0.0.1", "PORT": "8080"}) == "http://127.0.0.1:8080"
    opened = []
    monkeypatch.setattr(start.webbrowser, "open", opened.append)
    assert start.open_browser_when_ready(fake_ollama.url + "/api/tags", attempts=3) is True
    assert opened == [fake_ollama.url + "/api/tags"]
    monkeypatch.setattr(start.time, "sleep", lambda s: None)
    assert start.open_browser_when_ready("http://127.0.0.1:9", attempts=2) is False


def test_main_setup_only_and_failures(monkeypatch, capsys):
    monkeypatch.setattr(start, "ensure_environment", lambda: None)
    assert start.main(["--setup-only"]) == 0

    def pip_fails():
        raise subprocess.CalledProcessError(1, ["pip", "install"])

    monkeypatch.setattr(start, "ensure_environment", pip_fails)
    assert start.main([]) == 1
    assert "Python 3.12 or 3.13" in capsys.readouterr().out


def test_app_restarts_after_an_update(monkeypatch):
    exit_codes = [start.RESTART_EXIT_CODE, 0]
    calls, setups = [], []
    monkeypatch.setattr(start.subprocess, "call", lambda cmd, cwd, env: calls.append(env) or exit_codes.pop(0))
    monkeypatch.setattr(start, "ensure_environment", lambda: setups.append(1))
    assert start.run_assistant() == 0
    assert len(calls) == 2 and setups == [1]  # new libraries installed between the two runs
    assert calls[0]["AI_ASSISTANT_LAUNCHER"] == "start.py"


def test_requirements_hash_changes_with_file(tmp_path, monkeypatch):
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("flask\n")
    monkeypatch.setattr(start, "REQUIREMENTS", reqs)
    first = start.requirements_hash()
    reqs.write_text("flask\nrequests\n")
    assert start.requirements_hash() != first
