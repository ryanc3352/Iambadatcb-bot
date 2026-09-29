import shutil
import json
from pathlib import Path
from datetime import datetime

TEXT_SUFFIXES = {'.txt', '.md', '.json', '.py', '.js', '.ts', '.html', '.css', '.csv',
                 '.yaml', '.yml', '.toml', '.ini', '.cfg', '.sh', '.sql', '.xml'}


class FolderManager:
    """Manage user folders that the AI can access"""

    def __init__(self, base_dir="./ai_files"):
        self.uploads_path = Path(base_dir) / "user_uploads"
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

    def add_folder(self, folder_path, folder_name=None):
        """
        Copy a folder to uploads and register it

        Args:
            folder_path: Path to folder to upload
            folder_name: Name to give the folder (optional)
        """
        try:
            source = Path(folder_path)

            if not source.exists():
                return False, f"Folder not found: {folder_path}"

            if not source.is_dir():
                return False, f"Not a directory: {folder_path}"

            # Use provided name or source folder name
            if not folder_name:
                folder_name = source.name

            folder_name = Path(folder_name).name
            if not folder_name or folder_name in ('.', '..'):
                return False, "Invalid folder name"
            destination = self.uploads_path / folder_name

            # Create destination if it exists, replace it
            if destination.exists():
                shutil.rmtree(destination)

            # Copy folder
            shutil.copytree(source, destination)

            # Register it
            self.folders[folder_name] = {
                'path': str(destination),
                'original_path': str(source),
                'size': self._get_folder_size(destination),
                'file_count': sum(1 for p in destination.rglob('*') if p.is_file()),
                'uploaded_at': datetime.now().isoformat()
            }

            self.save_registry()
            return True, f"✅ Folder '{folder_name}' uploaded successfully"

        except Exception as e:
            return False, f"Error uploading folder: {str(e)}"

    def get_folder_contents(self, folder_name):
        """Get list of files in an uploaded folder"""
        if folder_name not in self.folders:
            return None, f"Folder not found: {folder_name}"

        try:
            folder_path = Path(self.folders[folder_name]['path'])
            files = []

            for file_path in folder_path.rglob('*'):
                if file_path.is_file():
                    rel_path = file_path.relative_to(folder_path)
                    files.append({
                        'name': file_path.name,
                        'path': str(rel_path),
                        'size': file_path.stat().st_size,
                        'type': file_path.suffix
                    })

            return files, None

        except Exception as e:
            return None, str(e)

    def read_file(self, folder_name, file_path):
        """Read a file from an uploaded folder"""
        if folder_name not in self.folders:
            return None, f"Folder not found: {folder_name}"

        try:
            folder_base = Path(self.folders[folder_name]['path']).resolve()
            full_path = (folder_base / file_path).resolve()

            # Security check - ensure file is within folder
            if not full_path.is_relative_to(folder_base):
                return None, "Access denied: file outside folder"

            if not full_path.exists():
                return None, f"File not found: {file_path}"

            # Read based on file type
            if full_path.suffix.lower() in TEXT_SUFFIXES:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                return content, None
            else:
                return f"[Binary file: {full_path.name}]", None

        except Exception as e:
            return None, str(e)

    def list_all_folders(self):
        """List all uploaded folders"""
        return self.folders

    def delete_folder(self, folder_name):
        """Delete an uploaded folder"""
        try:
            if folder_name not in self.folders:
                return False, "Folder not found"

            folder_path = Path(self.folders[folder_name]['path'])

            if folder_path.exists():
                shutil.rmtree(folder_path)

            del self.folders[folder_name]
            self.save_registry()

            return True, f"✅ Folder '{folder_name}' deleted"

        except Exception as e:
            return False, f"Error deleting folder: {str(e)}"

    def get_folder_summary(self, folder_name):
        """Get a text summary of folder contents"""
        files, error = self.get_folder_contents(folder_name)

        if error:
            return f"Error: {error}"

        if not files:
            return f"Folder '{folder_name}' is empty"

        summary = f"📁 Folder: {folder_name}\n"
        summary += f"Files: {len(files)}\n\n"
        summary += "Contents:\n"

        by_type = {}
        for file in files:
            file_type = file['type'] or 'unknown'
            if file_type not in by_type:
                by_type[file_type] = []
            by_type[file_type].append(file['name'])

        for file_type, file_names in sorted(by_type.items()):
            summary += f"\n{file_type} files ({len(file_names)}):\n"
            for name in sorted(file_names)[:10]:  # Show first 10
                summary += f"  • {name}\n"
            if len(file_names) > 10:
                summary += f"  ... and {len(file_names) - 10} more\n"

        return summary

    def _get_folder_size(self, folder_path):
        """Get total size of folder in MB"""
        total = 0
        for file_path in Path(folder_path).rglob('*'):
            if file_path.is_file():
                total += file_path.stat().st_size
        return round(total / (1024 * 1024), 2)
