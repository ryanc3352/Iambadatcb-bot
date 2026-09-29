import json
import re
import shutil
import time
from pathlib import Path


class UpgradeManager:
    """Manages code upgrades with backup and rollback.

    Only files in `allowed_files` (relative to `project_dir`) can be read,
    upgraded or restored.
    """

    def __init__(self, project_dir=".", backup_dir="./backups", allowed_files=()):
        self.project_dir = Path(project_dir).resolve()
        self.allowed_files = set(allowed_files)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.backup_dir / "upgrade_log.json"

    def _resolve(self, file_name):
        """Map a requested file name to a real project file, or raise PermissionError."""
        name = Path(str(file_name).strip()).name
        if name not in self.allowed_files:
            raise PermissionError(f"'{file_name}' is not an upgradeable file")
        return self.project_dir / name

    @staticmethod
    def _strip_fences(code):
        """Remove a surrounding ```python ... ``` fence if present."""
        code = code.strip()
        match = re.fullmatch(r"```[\w-]*\n?([\s\S]*?)\n?```", code)
        return (match.group(1) if match else code).strip() + "\n"

    def _backup(self, file_path):
        """Copy a file into the backup folder and return the backup path."""
        stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{time.time_ns() % 1_000_000:06d}"
        backup_path = self.backup_dir / f"{file_path.stem}_backup_{stamp}{file_path.suffix}"
        shutil.copy2(file_path, backup_path)
        return backup_path

    def apply_upgrade(self, file_name, code, description=""):
        """Back up the file, then replace it with new code that compiles.

        Returns:
            tuple: (success, message)
        """
        try:
            file_path = self._resolve(file_name)
            code = self._strip_fences(code)
            compile(code, str(file_path), 'exec')
        except PermissionError as e:
            return False, str(e)
        except SyntaxError as e:
            return False, f"Syntax error: {e}"

        try:
            backup_path = self._backup(file_path) if file_path.exists() else None
            tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
            tmp_path.write_text(code, encoding="utf-8")
            tmp_path.replace(file_path)
            self.log_upgrade(file_path, description, backup_path)
            return True, f"✅ Upgraded {file_path.name}"
        except OSError as e:
            return False, f"Upgrade failed: {e}"

    def rollback(self, backup_name):
        """Restore a file from a backup listed by list_backups().

        Returns:
            tuple: (success, message)
        """
        backup_path = self.backup_dir / Path(backup_name).name
        if not backup_path.is_file():
            return False, f"Backup not found: {backup_name}"

        entry = next((e for e in self.get_upgrade_history()
                      if e.get("backup") and Path(e["backup"]).name == backup_path.name), None)
        if not entry:
            return False, "No upgrade log entry for this backup"

        try:
            file_path = self._resolve(Path(entry["file"]).name)
            safety_backup = self._backup(file_path) if file_path.exists() else None
            shutil.copy2(backup_path, file_path)
            self.log_upgrade(file_path, f"Rollback to {backup_path.name}", safety_backup)
            return True, f"✅ Restored {file_path.name} from {backup_path.name}"
        except (PermissionError, OSError) as e:
            return False, f"Rollback failed: {e}"

    def log_upgrade(self, file_path, description, backup_path):
        logs = self.get_upgrade_history()
        logs.append({
            "timestamp": time.time(),
            "file": str(file_path),
            "description": description,
            "backup": str(backup_path) if backup_path else None
        })
        try:
            self.log_file.write_text(json.dumps(logs, indent=2), encoding="utf-8")
        except OSError as e:
            print(f"Could not write upgrade log: {e}")

    def get_upgrade_history(self):
        try:
            if self.log_file.exists():
                return json.loads(self.log_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"Could not read upgrade log: {e}")
        return []

    def list_backups(self):
        return sorted((f.name for f in self.backup_dir.glob("*_backup_*.py")), reverse=True)

    def get_file_code(self, file_name):
        try:
            return True, self._resolve(file_name).read_text(encoding="utf-8")
        except PermissionError as e:
            return False, str(e)
        except OSError:
            return False, "File not found"
