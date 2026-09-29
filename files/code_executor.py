import re
import subprocess
import sys
from pathlib import Path


class CodeExecutor:
    """Runs Python code in a separate process with a time limit.

    This is NOT a security sandbox: the code runs with your user's permissions.
    Only execute code you have read and trust.
    """

    CODE_PATTERN = re.compile(r'```(?:python|py)?[ \t]*\n([\s\S]*?)\n```')

    def __init__(self, working_dir="./ai_files", timeout=30):
        """
        Args:
            working_dir: Folder the code runs in (relative file paths land here)
            timeout (int): Seconds before the process is stopped
        """
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout

    def extract_code(self, text: str) -> tuple:
        """Extract the first Python code block from text.

        Returns:
            tuple: (has_code, code_content)
        """
        match = self.CODE_PATTERN.search(text)
        if match:
            return True, match.group(1)
        return False, None

    def execute_code(self, code: str) -> tuple:
        """Execute code in a child Python process.

        Returns:
            tuple: (success, output)
        """
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-c", code],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            return False, f"TimeoutError: code ran longer than {self.timeout}s and was stopped"
        except OSError as e:
            return False, f"Could not start Python: {e}"

        output = result.stdout
        if result.returncode != 0:
            return False, (output + result.stderr).strip() or f"Exited with code {result.returncode}"
        if result.stderr.strip():
            output += "\n" + result.stderr
        return True, output.strip() or "✅ Code executed successfully"
