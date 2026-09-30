import json

import pytest

from upgrade_manager import UpgradeManager

ORIGINAL = '''"""Tools module"""
LIMIT = 3


def helper():
    return 1


class Thing:
    pass
'''


@pytest.fixture
def um(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "tools.py").write_text(ORIGINAL)
    (project / "secret.py").write_text("PASSWORD = 'x'\n")
    return UpgradeManager(project, tmp_path / "backups", allowed_files=["tools.py"])


def test_apply_upgrade_strips_fences_and_backs_up(um):
    new = ORIGINAL + "\n\ndef extra():\n    return 2\n"
    ok, message = um.apply_upgrade("tools.py", f"```python\n{new}```", "add extra")
    assert ok, message
    assert (um.project_dir / "tools.py").read_text() == new.strip() + "\n"
    backups = um.list_backups()
    assert len(backups) == 1 and (um.backup_dir / backups[0]).read_text() == ORIGINAL
    history = um.get_upgrade_history()
    assert history[-1]["description"] == "add extra" and history[-1]["backup"].endswith(backups[0])


def test_rejects_syntax_errors(um):
    ok, message = um.apply_upgrade("tools.py", "def broken(:\n")
    assert not ok and message.startswith("Syntax error")
    assert (um.project_dir / "tools.py").read_text() == ORIGINAL


@pytest.mark.parametrize("name", ["secret.py", "../outside.py", "/etc/passwd", "sub/tools2.py"])
def test_rejects_files_not_allowed(um, name):
    ok, message = um.apply_upgrade(name, "x = 1\n")
    assert not ok and "not an upgradeable file" in message


def test_path_components_are_ignored(um):
    # only the file name counts, so this still targets the allowed project file
    ok, _ = um.apply_upgrade("../../tools.py", ORIGINAL + "\nMORE = 1\n")
    assert ok


def test_a_partial_upgrade_keeps_the_rest(um):
    ok, message = um.apply_upgrade("tools.py", "def helper():\n    return 5\n")
    assert ok and message == "✅ Upgraded tools.py: changed helper; the rest is as it was."
    code = (um.project_dir / "tools.py").read_text()
    assert "LIMIT = 3" in code and "class Thing" in code and "return 5" in code


def test_an_indented_method_sent_alone_goes_into_the_class(um):
    ok, message = um.apply_upgrade("tools.py", "```python\n    def go(self):\n        return 1\n```")
    assert ok, message
    namespace = {}
    exec((um.project_dir / "tools.py").read_text(), namespace)
    assert namespace["Thing"]().go() == 1


def test_rollback(um):
    um.apply_upgrade("tools.py", ORIGINAL + "\nNEW = 1\n", "v2")
    backup = um.list_backups()[0]
    ok, message = um.rollback(backup)
    assert ok, message
    assert (um.project_dir / "tools.py").read_text() == ORIGINAL
    assert len(um.list_backups()) == 2  # the upgraded version was saved before restoring
    assert um.rollback("nope_backup_1.py") == (False, "Backup not found: nope_backup_1.py")


def test_rollback_needs_log_entry(um):
    stray = um.backup_dir / "stray_backup_1.py"
    stray.write_text("x = 1\n")
    assert um.rollback(stray.name) == (False, "No upgrade log entry for this backup")


def test_get_file_code(um):
    assert um.get_file_code("tools.py") == (True, ORIGINAL)
    ok, message = um.get_file_code("secret.py")
    assert not ok and "not an upgradeable file" in message


def test_corrupt_log_is_tolerated(um):
    um.log_file.write_text("{not json")
    assert um.get_upgrade_history() == []
    assert um.apply_upgrade("tools.py", ORIGINAL + "\nZ = 1\n")[0]
    assert len(json.loads(um.log_file.read_text())) == 1


def test_new_allowed_file_can_be_created(tmp_path):
    um = UpgradeManager(tmp_path, tmp_path / "b", allowed_files=["fresh.py"])
    assert um.apply_upgrade("fresh.py", "x = 1\n")[0]
    assert (tmp_path / "fresh.py").read_text() == "x = 1\n"
