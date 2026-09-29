import re
from pathlib import Path


class FileHandler:
    """Safe file operations for the AI, restricted to one directory."""

    # Managed by FolderManager; not shown or writable as "the user's files"
    INTERNAL = {'user_uploads', 'folder_registry.json'}

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

    def list_all_files(self):
        """Every file saved in the folder (including subfolders), newest first.

        Returns:
            list: [{'path': 'notes/todo.txt', 'size': bytes, 'modified': timestamp}]
        """
        files = []
        for path in self.allowed_directory.rglob('*'):
            relative = path.relative_to(self.allowed_directory)
            if path.is_file() and relative.parts[0] not in self.INTERNAL:
                stat = path.stat()
                files.append({'path': relative.as_posix(), 'size': stat.st_size, 'modified': stat.st_mtime})
        return sorted(files, key=lambda f: f['modified'], reverse=True)

    @classmethod
    def clean_relative_path(cls, file_path):
        """Turn a path the model wrote ('notes\\todo.txt', '/todo.txt', 'C:\\x.txt') into a safe
        relative one, or raise ValueError."""
        text = str(file_path).strip().strip('`"\'').replace('\\', '/')
        text = re.sub(r"^[A-Za-z]:", "", text).lstrip('/')
        parts = [part for part in text.split('/') if part not in ('', '.')]
        if len(parts) > 1 and parts[0].lower() == 'ai_files':  # already inside ai_files, don't nest
            parts = parts[1:]
        if not parts or '..' in parts:
            raise ValueError(f"Not a usable file name: {file_path!r}")
        if parts[0] in cls.INTERNAL:
            raise ValueError(f"'{parts[0]}' is reserved; choose another name")
        return '/'.join(parts)

    def delete_file(self, file_path):
        """Delete a file."""
        path = self._resolve(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        path.unlink()
        return f"File deleted: {path}"
