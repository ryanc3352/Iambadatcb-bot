from pathlib import Path


class FileHandler:
    """Safe file operations for the AI, restricted to one directory."""

    def __init__(self, allowed_directory="./ai_files"):
        """
        Initialize file handler with a safe directory

        Args:
            allowed_directory: Only allow reading/writing in this directory
        """
        self.allowed_directory = Path(allowed_directory).resolve()
        self.allowed_directory.mkdir(parents=True, exist_ok=True)

    def _resolve(self, file_path):
        """
        Resolve a path relative to the allowed directory.

        Raises:
            PermissionError: If the path points outside the allowed directory
        """
        path = Path(file_path)
        if not path.is_absolute():
            path = self.allowed_directory / path
        try:
            path = path.resolve()
        except (OSError, ValueError) as e:
            raise PermissionError(f"Invalid path: {file_path} ({e})")
        if not path.is_relative_to(self.allowed_directory):
            raise PermissionError(f"Cannot access files outside {self.allowed_directory}")
        return path

    def read_file(self, file_path):
        """Read a UTF-8 text file and return its contents."""
        path = self._resolve(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        try:
            return path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            raise ValueError(f"File encoding error (not UTF-8): {file_path}")

    def write_file(self, file_path, content):
        """Write content to a file, creating parent folders if needed."""
        path = self._resolve(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return f"File written successfully: {path}"

    def append_file(self, file_path, content):
        """Append content to a file."""
        path = self._resolve(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(content)
        return f"Content appended successfully: {path}"

    def list_files(self, directory=None):
        """List file names in a directory (relative to the allowed directory)."""
        target_dir = self._resolve(directory or ".")
        if not target_dir.is_dir():
            return []
        return sorted(item.name for item in target_dir.iterdir() if item.is_file())

    def delete_file(self, file_path):
        """Delete a file."""
        path = self._resolve(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        path.unlink()
        return f"File deleted: {path}"
