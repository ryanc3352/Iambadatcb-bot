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
    # The text between a ```bash block and the Python block used to be offered as code
    ("Install:\n```bash\npip install requests\n```\nThen run this.\n```python\nimport requests\n```", "import requests"),
    ("```Python\nprint(1)\n```\nThis prints 1.\n```\nOutput: 1\n```", "print(1)"),
    ("```text\nnotes\n```\nexplanation\n```\nz = 4\n```", "z = 4"),
    ("1. Run:\n   ```python\n   if True:\n       go()\n   ```", "if True:\n    go()"),
])
def test_extract_code(ex, text, expected):
    assert ex.extract_code(text) == (True, expected)


def test_extract_code_none(ex):
    assert ex.extract_code("no code here") == (False, None)
    assert ex.extract_code("inline `code` only") == (False, None)
    assert ex.extract_code("```bash\npip install requests\n```\nThat's all.") == (False, None)
    assert ex.extract_code("```\npip install requests\n```") == (False, None)
    assert ex.extract_code("```python\nprint('cut off by the model") == (False, None)


def test_find_packages(ex):
    text = ("```bash\npip install requests beautifulsoup4==4.12 -U\npython -m pip install -r requirements.txt pillow\n```\n"
            "Or run `pip install numpy` first. Pip install the colorama library for colors.\n"
            "```python\n!pip install pandas\nimport pandas\n```")
    assert ex.find_packages(text) == ["requests", "beautifulsoup4==4.12", "pillow", "pandas", "numpy"]
    assert ex.find_packages("```bash\npip install requests && python app.py\n```") == ["requests"]
    assert ex.find_packages("```bash\npip install git+https://x.test/r.git\n```") == []


def test_split_pip_lines(ex):
    code, packages = ex.split_pip_lines("!pip install pandas numpy\npip install rich\nimport pandas")
    assert (code, packages) == ("import pandas", ["pandas", "numpy", "rich"])


def test_package_for(ex):
    assert ex.package_for("cv2") == "opencv-python"
    assert ex.package_for("PIL.Image") == "pillow"
    assert ex.package_for("requests") == "requests"
    assert ex.package_for("tkinter") is None  # part of Python, pip can't install it
    (ex.working_dir / "helper.py").write_text("")
    assert ex.package_for("helper") is None  # the user's own file


def test_missing_package_is_installed_and_code_runs_again(ex, monkeypatch):
    installed = []

    def fake_install(packages, run_id, report):
        installed.extend(packages)
        (ex.working_dir / "installed.flag").write_text("yes")
        return True, "Successfully installed"

    monkeypatch.setattr(ex, "install", fake_install)
    code = ("import os\nif not os.path.exists('installed.flag'):\n"
            "    raise ModuleNotFoundError(\"No module named 'cv2'\")\nprint('ran')")
    lines = []
    ok, out = ex.execute_code(code, on_output=lines.append)
    assert ok and installed == ["opencv-python"]
    assert out == "📦 Installed opencv-python\nran"
    assert any("Installing opencv-python" in line for line in lines)


def test_packages_are_installed_before_running(ex, monkeypatch):
    installed = []
    monkeypatch.setattr(ex, "install", lambda packages, run_id, report: (installed.extend(packages), (True, ""))[1])
    assert ex.execute_code("!pip install rich\nprint('ok')", packages=["requests"]) == \
        (True, "📦 Installed requests, rich\nok")
    assert installed == ["requests", "rich"]


def test_failed_install_is_reported(ex, monkeypatch):
    monkeypatch.setattr(ex, "install", lambda packages, run_id, report: (False, "ERROR: No matching distribution"))
    ok, out = ex.execute_code("import surely_not_a_real_module_xyz")
    assert not ok and "ModuleNotFoundError" in out
    assert "Couldn't install surely-not-a-real-module-xyz" in out and "No matching distribution" in out


def test_missing_stdlib_module_is_not_installed(ex, monkeypatch):
    monkeypatch.setattr(ex, "install", lambda *a: pytest.fail("pip must not run"))
    ok, out = ex.execute_code("raise ModuleNotFoundError(\"No module named 'tkinter'\")")
    assert not ok and "tkinter" in out


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
    assert ok is False and "EOFError" in out and "Typed answers" in out


def test_execute_with_typed_answers(ex):
    code = "name = input('Name? ')\nage = input('Age? ')\nprint(f'{name} is {age}')"
    assert ex.execute_code(code, stdin_text="Ana\n30") == (True, "Name? Age? Ana is 30")


def test_no_time_limit_by_default(tmp_path):
    ex = CodeExecutor(tmp_path)
    assert ex.timeout == 0
    assert ex.execute_code("import time\ntime.sleep(1.5)\nprint('slow but done')") == (True, "slow but done")


def test_stop_ends_a_running_program(ex):
    import threading
    import time
    lines = []
    worker = threading.Thread(target=lambda: lines.append(ex.execute_code(
        "print('started', flush=True)\nwhile True: pass", run_id="r1")))
    worker.start()
    for _ in range(100):
        if ex.stop("r1"):
            break
        time.sleep(0.1)
    worker.join(10)
    assert not worker.is_alive()
    ok, out = lines[0]
    assert not ok and "⏹ Stopped" in out
    assert ex.stop("r1") is False  # nothing running any more


def test_execute_warnings_are_kept(ex):
    ok, out = ex.execute_code("import sys\nprint('out')\nprint('warn', file=sys.stderr)")
    assert ok and "out" in out and "warn" in out
