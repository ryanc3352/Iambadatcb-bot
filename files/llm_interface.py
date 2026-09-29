import json

import requests


class LLMError(Exception):
    """Raised when Ollama can't produce a response (not running, model missing, timeout...)."""


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
            return response.json().get("response", "").strip()

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

    def test_model(self):
        """Test the model with a simple request."""
        print(f"Testing {self.model_name}...")
        try:
            print(f"Model response: {self.generate_response('Say hello and nothing else.')}\n")
        except LLMError as e:
            print(f"✗ {e}\n")
