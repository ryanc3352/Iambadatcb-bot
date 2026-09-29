"""Switch Ollama models from the web page.

Picking a model that isn't downloaded yet asks Ollama to download it (in the
background, with progress). When the switch happens the previous model is
unloaded from memory and the new one is loaded. The choice is saved, so the app
starts with it next time.
"""
import json
import re
import threading
from pathlib import Path

from llm_interface import LLMError

# Ollama names: "mistral", "qwen3:8b", "library/llama3.2", "hf.co/user/repo:Q4_K_M"
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:]{0,199}$")

# Shown in the picker; any other Ollama model name can be typed in
SUGGESTED_MODELS = [
    {'name': 'mistral', 'size': '4.1 GB', 'note': 'Good all-rounder (default)'},
    {'name': 'qwen3:8b', 'size': '5.2 GB', 'note': 'Much better at maths and reasoning'},
    {'name': 'qwen3:4b', 'size': '2.6 GB', 'note': 'Good maths, faster on slower PCs'},
    {'name': 'llama3.2', 'size': '2.0 GB', 'note': 'Small and fast'},
    {'name': 'gemma3', 'size': '3.3 GB', 'note': "Google's model, good at writing"},
    {'name': 'deepseek-r1:8b', 'size': '5.2 GB', 'note': 'Thinks step by step before answering'},
]


def same_model(a, b):
    """'mistral' and 'mistral:latest' are the same model."""
    def full(name):
        return name if ':' in name.split('/')[-1] else f"{name}:latest"
    return full(a) == full(b)


class ModelManager:
    """Keeps track of the active model, downloads and switches."""

    def __init__(self, llm, settings_path):
        self.llm = llm
        self.settings_path = Path(settings_path)
        self._lock = threading.Lock()
        self.download = None  # progress of the current/last download

    # ---- saved choice

    def _read_settings(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_model(self, name):
        data = self._read_settings()
        data['model'] = name
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ---- status

    def status(self):
        """Everything the picker shows. Works (with an error message) when Ollama is down."""
        current = self.llm.model_name
        result = {'current': current, 'installed': [], 'loaded': [], 'suggestions': SUGGESTED_MODELS,
                  'download': self.download, 'error': None}
        try:
            result['installed'] = self.llm.list_models()
            result['loaded'] = self.llm.running_models()
        except LLMError as e:
            result['error'] = str(e)
        result['current_installed'] = any(same_model(m['name'], current) for m in result['installed'])
        return result

    def is_downloading(self):
        return bool(self.download and not self.download['done'])

    # ---- switching

    def select(self, name):
        """Switch to a model, downloading it first if needed.

        Returns:
            dict: {'action': 'switched' | 'downloading' | 'unchanged', 'message': ...}

        Raises:
            ValueError: For an invalid model name or while another download runs
            LLMError: If Ollama isn't reachable
        """
        name = str(name).strip()
        if not MODEL_NAME_PATTERN.match(name):
            raise ValueError("That isn't a valid model name (e.g. mistral or qwen3:8b)")
        with self._lock:
            if self.is_downloading():
                raise ValueError(f"Please wait: {self.download['model']} is still downloading")
            installed = [m['name'] for m in self.llm.list_models()]
            if not any(same_model(m, name) for m in installed):
                self.download = {'model': name, 'status': 'starting', 'completed': 0, 'total': 0,
                                 'done': False, 'error': None}
                threading.Thread(target=self._download_then_switch, args=(name,), daemon=True).start()
                return {'action': 'downloading', 'message': f"Downloading {name}..."}
            if same_model(name, self.llm.model_name):
                return {'action': 'unchanged', 'message': f"{name} is already in use"}
            return self._switch(name)

    def _download_then_switch(self, name):
        try:
            for progress in self.llm.pull_model(name):
                self.download.update(status=progress.get('status', ''),
                                     completed=progress.get('completed', self.download['completed']),
                                     total=progress.get('total', self.download['total']))
            with self._lock:
                self._switch(name)
            self.download.update(status='success', done=True)
        except LLMError as e:
            self.download.update(status='failed', error=str(e), done=True)

    def _switch(self, name):
        """Use `name` from now on, unload the previous model and load the new one."""
        previous = self.llm.model_name
        self.llm.model_name = name
        self._save_model(name)
        if previous and not same_model(previous, name):
            self.llm.unload_model(previous)
        # Load in the background so the first answer is quicker; the page doesn't wait for it
        threading.Thread(target=self.llm.load_model, args=(name,), daemon=True).start()
        return {'action': 'switched', 'message': f"Now using {name}"
                + (f" ({previous} was unloaded from memory)" if previous and not same_model(previous, name) else "")}
