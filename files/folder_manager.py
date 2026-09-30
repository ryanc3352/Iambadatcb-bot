import json
import shutil
from datetime import datetime
from pathlib import Path

TEXT_SUFFIXES = {'.txt', '.md', '.json', '.py', '.js', '.ts', '.html', '.css', '.csv',
                 '.yaml', '.yml', '.toml', '.ini', '.cfg', '.sh', '.sql', '.xml'}


class FolderManager:
    """Manage user folders that the AI can access"""

    def __init__(self, base_dir="./ai_files"):
        self.uploads_path = Path(base_dir).resolve() / "user_uploads"
        self.uploads_path.mkdir(parents=True, exist_ok=True)
        self.registry_path = Path(base_dir) / "folder_registry.json"
        self.load_registry()

    def load_registry(self):
        """Load list of accessible folders"""
        self.folders = {}
        if self.registry_path.exists():
            try:
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    self.folders = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                print(f"Could not read folder registry, starting empty: {e}")

    def save_registry(self):
        """Save folder registry"""
        with open(self.registry_path, 'w', encoding='utf-8') as f:
            json.dump(self.folders, f, indent=2)

    def folder_path(self, folder_name):
        """Path of a registered project folder, or None."""
        return self._folder_path(folder_name)

    def _folder_path(self, folder_name):
        """Path of a registered folder. Always inside the uploads folder, whatever the registry says."""
        if folder_name not in self.folders:
            return None
        return self.uploads_path / Path(folder_name).name

    def add_folder(self, folder_path, folder_name=None):
        """
        Copy a folder to uploads and register it (replaces a folder with the same name)

        Args:
            folder_path: Path to folder to upload
            folder_name: Name to give the folder (optional)

        Returns:
            tuple: (success, message)
        """
        source = Path(folder_path)
        if not source.is_dir():
            return False, f"Folder not found: {folder_path}"

        folder_name = Path(folder_name or source.name).name
        if not folder_name or folder_name in ('.', '..'):
            return False, "Invalid folder name"

        destination = self.uploads_path / folder_name
        try:
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
        except OSError as e:
            return False, f"Error uploading folder: {e}"

        files = [p for p in destination.rglob('*') if p.is_file()]
        self.folders[folder_name] = {
            'size': round(sum(p.stat().st_size for p in files) / (1024 * 1024), 2),  # MB
            'file_count': len(files),
            'uploaded_at': datetime.now().isoformat()
        }
        self.save_registry()
        return True, f"✅ Folder '{folder_name}' uploaded successfully"

    def get_folder_contents(self, folder_name):
        """Get list of files in an uploaded folder

        Returns:
            tuple: (files, error)
        """
        folder_path = self._folder_path(folder_name)
        if folder_path is None or not folder_path.is_dir():
            return None, f"Folder not found: {folder_name}"

        files = []
        for file_path in sorted(folder_path.rglob('*')):
            if file_path.is_file():
                files.append({
                    'name': file_path.name,
                    'path': file_path.relative_to(folder_path).as_posix(),
                    'size': file_path.stat().st_size,
                    'type': file_path.suffix
                })
        return files, None

    def read_file(self, folder_name, file_path):
        """Read a file from an uploaded folder

        Returns:
            tuple: (content, error)
        """
        folder_base = self._folder_path(folder_name)
        if folder_base is None:
            return None, f"Folder not found: {folder_name}"

        full_path = (folder_base / file_path).resolve()
        # Security check - ensure file is within folder
        if not full_path.is_relative_to(folder_base.resolve()):
            return None, "Access denied: file outside folder"
        if not full_path.is_file():
            return None, f"File not found: {file_path}"

        if full_path.suffix.lower() not in TEXT_SUFFIXES:
            return f"[Binary file: {full_path.name}]", None
        try:
            return full_path.read_text(encoding='utf-8', errors='ignore'), None
        except OSError as e:
            return None, str(e)

    def list_all_folders(self):
        """List all uploaded folders"""
        return self.folders

    def delete_folder(self, folder_name):
        """Delete an uploaded folder

        Returns:
            tuple: (success, message)
        """
        folder_path = self._folder_path(folder_name)
        if folder_path is None:
            return False, "Folder not found"
        try:
            if folder_path.exists():
                shutil.rmtree(folder_path)
        except OSError as e:
            return False, f"Error deleting folder: {e}"
        del self.folders[folder_name]
        self.save_registry()
        return True, f"✅ Folder '{folder_name}' deleted"

    def get_folder_summary(self, folder_name):
        """Get a text summary of folder contents"""
        files, error = self.get_folder_contents(folder_name)
        if error:
            return f"Error: {error}"
        if not files:
            return f"Folder '{folder_name}' is empty"

        summary = f"📁 Folder: {folder_name}\nFiles: {len(files)}\n\nContents:\n"

        by_type = {}
        for file in files:
            by_type.setdefault(file['type'] or 'unknown', []).append(file['path'])

        for file_type, file_names in sorted(by_type.items()):
            summary += f"\n{file_type} files ({len(file_names)}):\n"
            for name in file_names[:10]:  # Show first 10
                summary += f"  • {name}\n"
            if len(file_names) > 10:
                summary += f"  ... and {len(file_names) - 10} more\n"
        return summary

    def get_folder_context(self, folder_name, max_chars=8000, max_file_chars=3000):
        """Summary plus the text of the folder's files, for the model to read.

        Files are added in path order until `max_chars` is used up; long files are cut
        to `max_file_chars`.

        Returns:
            tuple: (context, error)
        """
        files, error = self.get_folder_contents(folder_name)
        if error:
            return None, error

        parts = [self.get_folder_summary(folder_name)]
        budget = max_chars
        skipped = 0
        for file in files:
            if file['type'].lower() not in TEXT_SUFFIXES:
                continue
            if budget <= 0:
                skipped += 1
                continue
            content, _ = self.read_file(folder_name, file['path'])
            if content is None:
                continue
            content = content[:min(max_file_chars, budget)]
            budget -= len(content)
            parts.append(f"--- {file['path']} ---\n{content}")
        if skipped:
            parts.append(f"({skipped} more text files not shown to keep the prompt short)")
        return "\n\n".join(parts), None
