import json

import requests


class LLMInterface:
    """Interface for communicating with Ollama LLM service.

    Handles all interactions with the local Ollama server including
    generating responses (streaming and non-streaming).
    """

    def __init__(self, model_name, temperature, max_tokens, base_url="http://localhost:11434"):
        """Initialize the LLM interface.

        Args:
            model_name (str): Name of the model to use (e.g., 'mistral')
            temperature (float): Temperature for response generation (0.0-1.0)
            max_tokens (int): Maximum tokens to generate per response
            base_url (str): Address of the Ollama server
        """
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")

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
            },
        }

    def generate_response(self, prompt):
        """Send prompt to Ollama and get response (non-streaming).

        Args:
            prompt (str): The prompt to send to the model

        Returns:
            str: The model's response text
        """
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=self._payload(prompt, stream=False),
                timeout=120
            )
            if response.status_code != 200:
                return f"Error: Ollama returned {response.status_code} - {response.text[:200]}"
            return response.json().get("response", "").strip()

        except requests.exceptions.Timeout:
            return "Error: Model timeout"
        except requests.exceptions.ConnectionError:
            return "Error: Can't connect to Ollama"
        except ValueError as e:
            return f"Error: Invalid JSON response from Ollama - {e}"
        except requests.exceptions.RequestException as e:
            return f"Error: Request failed - {e}"

    def generate_response_stream(self, prompt):
        """Stream response tokens from Ollama one at a time.

        Args:
            prompt (str): The prompt to send to the model

        Yields:
            str: Individual response tokens as they're generated
        """
        try:
            with requests.post(
                f"{self.base_url}/api/generate",
                json=self._payload(prompt, stream=True),
                timeout=120,
                stream=True
            ) as response:
                if response.status_code != 200:
                    yield f"Error: Ollama returned {response.status_code}"
                    return

                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # Skip malformed lines, keep streaming
                    if data.get("error"):
                        yield f"Error: {data['error']}"
                        return
                    if data.get("response"):
                        yield data["response"]
                    if data.get("done"):
                        return

        except requests.exceptions.Timeout:
            yield "Error: Model timeout"
        except requests.exceptions.ConnectionError:
            yield "Error: Can't connect to Ollama"
        except requests.exceptions.RequestException as e:
            yield f"Error: Request failed - {e}"

    def test_model(self):
        """Test the model with a simple request."""
        print(f"Testing {self.model_name}...")
        response = self.generate_response("Say hello and nothing else.")
        print(f"Model response: {response}\n")
