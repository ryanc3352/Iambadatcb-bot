"""One-click start: sets everything up the first time, then runs the assistant.

Windows:   double-click "Start AI.bat"   (or run:  py start.py)
Mac/Linux: python3 start.py

The first run creates a private Python environment (.venv) and installs the
libraries (a few minutes), makes sure Ollama is running and downloads the AI
model if it's missing. Later runs start straight away.

Options: --setup-only (install and stop), --no-browser (don't open the browser)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_DIR = HERE / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIREMENTS = HERE / "requirements.txt"
STAMP = VENV_DIR / "installed-requirements.sha256"
MIN_PYTHON = (3, 10)
DEFAULTS = {"MODEL_NAME": "mistral", "OLLAMA_URL": "http://localhost:11434", "HOST": "127.0.0.1", "PORT": "5000",
            "DATA_DIR": ""}


def read_settings(env_file=HERE / ".env", environ=os.environ):
    """The settings start.py needs, from .env and the environment (the environment wins,
    like in config.py). Works before python-dotenv is installed."""
    settings = dict(DEFAULTS)
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            key = key.strip()
            if sep and key in settings and not key.startswith("#"):
                settings[key] = value.strip().strip("'\"")
    for key in settings:
        settings[key] = environ.get(key, settings[key])
    # A model picked in the app (Model button) wins, like in config.py
    saved = Path(settings["DATA_DIR"] or HERE) / "user_settings.json"
    try:
        model = json.loads(saved.read_text(encoding="utf-8")).get("model")
        if isinstance(model, str) and model:
            settings["MODEL_NAME"] = model
    except (OSError, ValueError, AttributeError):
        pass
    return settings


def requirements_hash():
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def run(command):
    subprocess.run([str(part) for part in command], check=True)


def ensure_environment():
    """Create .venv and install the libraries (again only when requirements.txt changes)."""
    if sys.version_info < MIN_PYTHON:
        raise RuntimeError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is needed "
                           f"(this is {sys.version.split()[0]}). Get it from https://www.python.org/downloads/")
    if not VENV_PYTHON.exists():
        print("First run: creating a Python environment in .venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    if not STAMP.exists() or STAMP.read_text(encoding="utf-8").strip() != requirements_hash():
        print("Installing the libraries (the first time takes a few minutes) ...")
        run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"])
        run([VENV_PYTHON, "-m", "pip", "install", "-r", REQUIREMENTS])
        STAMP.write_text(requirements_hash(), encoding="utf-8")


def ollama_models(url):
    """Names of the models Ollama has, or None if Ollama isn't reachable."""
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as response:
            return [m["name"] for m in json.load(response).get("models", [])]
    except (OSError, ValueError):
        return None


def model_installed(models, name):
    """'mistral' matches 'mistral:latest'; 'qwen3:8b' must match exactly."""
    return name in models or f"{name}:latest" in models


def pull_model(url, name):
    """Download a model through Ollama's API, showing progress."""
    request = urllib.request.Request(f"{url}/api/pull", data=json.dumps({"model": name, "name": name}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        for line in response:
            status = json.loads(line or b"{}")
            if status.get("error"):
                raise RuntimeError(f"Ollama couldn't download '{name}': {status['error']}")
            done, total = status.get("completed"), status.get("total")
            progress = f" {done * 100 // total}%" if done and total else ""
            print(f"\r  {status.get('status', '')}{progress}".ljust(60), end="", flush=True)
    print()


def ensure_ollama(settings):
    """Make sure Ollama runs and has the model. Returns True if the assistant can answer."""
    url, model = settings["OLLAMA_URL"].rstrip("/"), settings["MODEL_NAME"]
    models = ollama_models(url)
    if models is None and shutil.which("ollama"):
        print("Starting Ollama ...")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: no extra console window
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags)
        for _ in range(30):
            time.sleep(1)
            models = ollama_models(url)
            if models is not None:
                break
    if models is None:
        print("\n⚠️  Ollama isn't running. Install it from https://ollama.com/download and start it,\n"
              "   then run this again. The app starts anyway but can't answer until Ollama runs.\n")
        return False
    if not model_installed(models, model):
        print(f"Downloading the AI model '{model}' (a few GB, only the first time) ...")
        pull_model(url, model)
    return True


def browser_url(settings):
    host = settings["HOST"]
    return f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{settings['PORT']}"


def open_browser_when_ready(url, attempts=120):
    for _ in range(attempts):
        try:
            urllib.request.urlopen(url, timeout=2).close()
            webbrowser.open(url)
            return True
        except OSError:
            time.sleep(1)
    return False


def main(args):
    try:
        ensure_environment()
        if "--setup-only" in args:
            print("Setup complete.")
            return 0
        settings = read_settings()
        ensure_ollama(settings)
        url = browser_url(settings)
        if "--no-browser" not in args:
            threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()
        print(f"Starting the assistant at {url}  (close this window or press Ctrl+C to stop)")
        return subprocess.call([str(VENV_PYTHON), str(HERE / "web_server.py")], cwd=HERE)
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print(f"\n❌ {e}")
        if isinstance(e, subprocess.CalledProcessError):
            print("Installing the libraries failed. Check your internet connection. If it keeps failing,\n"
                  "install Python 3.12 or 3.13 from python.org, delete the .venv folder and try again.")
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):  # Windows pipes may not support emoji
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    exit_code = main(sys.argv[1:])
    # Double-clicked on Windows: keep the window open so the message can be read
    if exit_code and os.name == "nt" and sys.stdin and sys.stdin.isatty():
        input("\nPress Enter to close...")
    sys.exit(exit_code)
