import pytest

from code_executor import CodeExecutor
from file_handler import FileHandler


# ---------------- FileHandler

@pytest.fixture
def fh(tmp_path):
    return FileHandler(tmp_path / "ai_files")


def test_write_read_list_delete(fh):
    fh.write_file("notes/a.txt", "hello world")
    assert fh.read_file("notes/a.txt") == "hello world"
    fh.write_file("top.txt", "x")
    assert sorted(f["path"] for f in fh.list_all_files()) == ["notes/a.txt", "top.txt"]
    fh.delete_file("notes/a.txt")
    with pytest.raises(FileNotFoundError):
        fh.read_file("notes/a.txt")
    with pytest.raises(FileNotFoundError):
        fh.delete_file("notes/a.txt")


@pytest.mark.parametrize("bad", ["../outside.txt", "notes/../../outside.txt", "/etc/passwd",
                                 "../ai_files_evil/x.txt"])
def test_paths_outside_are_blocked(fh, bad):
    with pytest.raises(PermissionError):
        fh.write_file(bad, "x")
    with pytest.raises(PermissionError):
        fh.read_file(bad)


def test_absolute_path_inside_is_allowed(fh):
    fh.write_file(str(fh.allowed_directory / "abs.txt"), "ok")
    assert fh.read_file("abs.txt") == "ok"


def test_non_utf8_file(fh):
    (fh.allowed_directory / "latin.txt").write_bytes(b"\xff\xfe\xfa")
    with pytest.raises(ValueError):
        fh.read_file("latin.txt")


# ---------------- CodeExecutor

@pytest.fixture
def ex(tmp_path):
    return CodeExecutor(working_dir=tmp_path / "run", timeout=5)


@pytest.mark.parametrize("text,expected", [
    ("Try:\n```python\nprint(1)\n```", "print(1)"),
    ("```py\nx = 2\n```", "x = 2"),
    ("```\ny = 3\n```", "y = 3"),
    ("```python\nfirst()\n```\ntext\n```python\nsecond()\n```", "first()"),
])
def test_extract_code(ex, text, expected):
    assert ex.extract_code(text) == (True, expected)


def test_extract_code_none(ex):
    assert ex.extract_code("no code here") == (False, None)
    assert ex.extract_code("inline `code` only") == (False, None)


def test_execute_success_and_working_dir(ex):
    ok, out = ex.execute_code("open('made.txt', 'w').write('hi')\nprint('done')")
    assert (ok, out) == (True, "done")
    assert (ex.working_dir / "made.txt").read_text() == "hi"


def test_execute_no_output(ex):
    assert ex.execute_code("x = 1") == (True, "✅ Code executed successfully")


def test_execute_error_returns_traceback(ex):
    ok, out = ex.execute_code("print('before')\n1/0")
    assert ok is False and "before" in out and "ZeroDivisionError" in out


def test_execute_timeout(tmp_path):
    ok, out = CodeExecutor(tmp_path, timeout=1).execute_code("while True: pass")
    assert ok is False and "Timeout" in out


def test_execute_unicode_output(ex):
    assert ex.execute_code("print('✅ café 日本')") == (True, "✅ café 日本")


def test_execute_long_code(ex):
    code = "\n".join(f"v{i} = {i}" for i in range(6000)) + "\nprint(v5999)"
    assert len(code) > 40000
    assert ex.execute_code(code) == (True, "5999")


def test_execute_input_gets_eof(ex):
    ok, out = ex.execute_code("input('name? ')")
    assert ok is False and "EOFError" in out


def test_execute_warnings_are_kept(ex):
    ok, out = ex.execute_code("import sys\nprint('out')\nprint('warn', file=sys.stderr)")
    assert ok and "out" in out and "warn" in out
