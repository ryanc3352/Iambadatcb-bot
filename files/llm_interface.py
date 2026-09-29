import json
import re

import requests


class LLMError(Exception):
    """Raised when Ollama can't produce a response (not running, model missing, timeout...)."""


THINK_OPEN, THINK_CLOSE = "<think>", "</think>"


def strip_thinking(text):
    """Remove the <think>...</think> reasoning that models like Qwen3 and DeepSeek-R1 write first."""
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    return text.split(THINK_OPEN, 1)[0] if THINK_OPEN in text else text  # unfinished thinking


class ThinkFilter:
    """Removes <think>...</think> from streamed text, even when a tag is split across tokens."""

    def __init__(self):
        self.pending = ""
        self.inside = False
        self.started = False       # a thinking block was seen
        self.trim_start = False    # drop the blank lines right after </think>

    def feed(self, token):
        """Returns the visible part of the text streamed so far."""
        self.pending += token
        visible = ""
        while True:
            tag = THINK_CLOSE if self.inside else THINK_OPEN
            index = self.pending.find(tag)
            if index >= 0:
                if not self.inside:
                    visible += self.pending[:index]
                    self.started = True
                self.pending = self.pending[index + len(tag):]
                self.trim_start = self.inside or self.trim_start
                self.inside = not self.inside
                continue
            # keep a possible partial tag (e.g. "<thi") for the next token
            keep = next((n for n in range(len(tag) - 1, 0, -1) if self.pending.endswith(tag[:n])), 0)
            ready = self.pending[:len(self.pending) - keep]
            self.pending = self.pending[len(self.pending) - keep:]
            if not self.inside:
                visible += ready
            if self.trim_start:
                visible = visible.lstrip()
                self.trim_start = not visible
            return visible

    def flush(self):
        """Text held back at the end of the stream."""
        rest, self.pending = ("" if self.inside else self.pending), ""
        return rest


class LLMInterface:
    """Interface for communicating with Ollama LLM service.

    Handles all interactions with the local Ollama server including
    generating responses (streaming and non-streaming).
    """

    def __init__(self, model_name, temperature, max_tokens, base_url="http://localhost:11434",
                 context_tokens=8192, timeout=600):
        """Initialize the LLM interface.

        Args:
            model_name (str): Name of the model to use (e.g., 'mistral')
            temperature (float): Temperature for response generation (0.0-1.0)
            max_tokens (int): Maximum tokens to generate per response
            base_url (str): Address of the Ollama server
            context_tokens (int): Context window. Ollama's default is small and it silently
                drops the start of longer prompts (which is where the system prompt is)
            timeout (int): Seconds to wait for the model (CPU-only PCs can be slow)
        """
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.context_tokens = context_tokens
        self.base_url = base_url.rstrip("/")
        self.timeout = (10, timeout)  # (connect, read)

    def test_connection(self):
        """Check if Ollama is running and accessible.

        Returns:
            bool: True if Ollama answered
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                print("✓ Connected to Ollama")
                return True
            print(f"✗ Ollama error: {response.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"✗ ERROR: Can't connect to Ollama at {self.base_url}. Make sure: ollama serve")
        except requests.exceptions.RequestException as e:
            print(f"✗ ERROR: Request failed: {e}")
        return False

    def _payload(self, prompt, stream):
        """Build the request body. Ollama reads sampling settings from 'options'."""
        return {
            "model": self.model_name,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
                "num_ctx": self.context_tokens,
            },
        }

    @staticmethod
    def _error_text(response):
        """Pull Ollama's error message out of a failed response."""
        try:
            return response.json().get("error") or response.text[:200]
        except ValueError:
            return response.text[:200]

    def generate_response(self, prompt):
        """Send prompt to Ollama and get response (non-streaming).

        Args:
            prompt (str): The prompt to send to the model

        Returns:
            str: The model's response text

        Raises:
            LLMError: If Ollama can't answer
        """
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=self._payload(prompt, stream=False),
                timeout=self.timeout
            )
            if response.status_code != 200:
                raise LLMError(f"Ollama returned {response.status_code}: {self._error_text(response)}")
            return strip_thinking(response.json().get("response", "")).strip()

        except requests.exceptions.Timeout:
            raise LLMError("The model took too long to answer")
        except requests.exceptions.ConnectionError:
            raise LLMError(f"Can't connect to Ollama at {self.base_url}. Is it running?")
        except ValueError as e:
            raise LLMError(f"Invalid JSON response from Ollama - {e}")
        except requests.exceptions.RequestException as e:
            raise LLMError(f"Request failed - {e}")

    def generate_response_stream(self, prompt):
        """Stream response tokens from Ollama one at a time.

        Args:
            prompt (str): The prompt to send to the model

        Yields:
            str: Individual response tokens as they're generated

        Raises:
            LLMError: If Ollama can't answer
        """
        try:
            with requests.post(
                f"{self.base_url}/api/generate",
                json=self._payload(prompt, stream=True),
                timeout=self.timeout,
                stream=True
            ) as response:
                if response.status_code != 200:
                    raise LLMError(f"Ollama returned {response.status_code}: {self._error_text(response)}")

                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # Skip malformed lines, keep streaming
                    if data.get("error"):
                        raise LLMError(data["error"])
                    if data.get("response"):
                        yield data["response"]
                    if data.get("done"):
                        return

        except requests.exceptions.Timeout:
            raise LLMError("The model took too long to answer")
        except requests.exceptions.ConnectionError:
            raise LLMError(f"Can't connect to Ollama at {self.base_url}. Is it running?")
        except requests.exceptions.RequestException as e:
            raise LLMError(f"Request failed - {e}")

    # ---- model management (used by the model picker)

    def _get(self, path, timeout=10):
        try:
            response = requests.get(f"{self.base_url}{path}", timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            raise LLMError(f"Can't connect to Ollama at {self.base_url}. Is it running?")
        except (requests.exceptions.RequestException, ValueError) as e:
            raise LLMError(f"Ollama request failed - {e}")

    def list_models(self):
        """Downloaded models: [{'name', 'size'}] (size in bytes)."""
        return [{'name': m['name'], 'size': m.get('size', 0)} for m in self._get("/api/tags").get('models', [])]

    def running_models(self):
        """Names of the models currently loaded in memory."""
        return [m['name'] for m in self._get("/api/ps").get('models', [])]

    def pull_model(self, name):
        """Download a model. Yields Ollama's progress updates ({'status', 'completed', 'total'}).

        Raises:
            LLMError: If the download fails (e.g. unknown model name)
        """
        try:
            with requests.post(f"{self.base_url}/api/pull", json={"model": name, "name": name, "stream": True},
                               timeout=(10, 600), stream=True) as response:
                if response.status_code != 200:
                    raise LLMError(f"Ollama returned {response.status_code}: {self._error_text(response)}")
                for line in response.iter_lines():
                    if not line:
                        continue
                    status = json.loads(line)
                    if status.get("error"):
                        raise LLMError(status["error"])
                    yield status
        except requests.exceptions.ConnectionError:
            raise LLMError(f"Can't connect to Ollama at {self.base_url}. Is it running?")
        except (requests.exceptions.RequestException, ValueError) as e:
            raise LLMError(f"Download failed - {e}")

    def _load_or_unload(self, name, keep_alive=None):
        payload = {"model": name}
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        try:
            response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=(10, 300))
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def load_model(self, name):
        """Load a model into memory now, so the first answer comes faster."""
        return self._load_or_unload(name)

    def unload_model(self, name):
        """Free the memory a model uses (Ollama unloads it when keep_alive is 0)."""
        return self._load_or_unload(name, keep_alive=0)

    def test_model(self):
        """Test the model with a simple request."""
        print(f"Testing {self.model_name}...")
        try:
            print(f"Model response: {self.generate_response('Say hello and nothing else.')}\n")
        except LLMError as e:
            print(f"✗ {e}\n")
