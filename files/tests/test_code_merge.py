import ast
import importlib.util
import textwrap
from pathlib import Path

import pytest

from code_merge import MergeError, definitions, fit
from upgrade_manager import UpgradeManager

OLD = '''"""Runner."""
import os

LIMIT = 3


class Runner:
    """Runs things."""

    def __init__(self):
        self.count = 0

    def run(self, code):
        def time_up():
            return "late"
        return self._process(code)

    def _process(self, code):
        return code.upper()


def feed(process, text):
    return text


if __name__ == "__main__":
    print(Runner().run("x"))
'''


def load(code):
    namespace = {"__name__": "runner"}
    exec(compile(code, "runner.py", "exec"), namespace)
    return namespace


def test_methods_sent_without_their_class_go_back_into_it():
    # What the model sends for "add docstrings": only the changed functions, no class
    new = '''def _process(self, code):
    """Process the code."""
    return code.lower()

def feed(process, text):
    """Feed text to the process."""
    return text * 2
'''
    code, changed, left_out = fit(OLD, new)
    assert changed == ["_process", "feed"] and left_out == []
    runner = load(code)
    assert runner["Runner"]().run("AB") == "ab" and runner["feed"](None, "a") == "aa"
    assert code.count("LIMIT = 3") == 1 and '"""Runs things."""' in code and "import os" in code


def test_a_method_that_slipped_out_of_its_class_is_put_back():
    # A whole file where _process ended up outside the class: every top-level name is still
    # there, but Runner lost a method, so it's merged instead of copied
    new = OLD.replace("    def _process(self, code):\n        return code.upper()",
                      "def _process(self, code):\n    return code.upper() + '!'")
    code, changed, _ = fit(OLD, new)
    assert changed == ["_process"]
    assert load(code)["Runner"]().run("a") == "A!"


def test_placeholders_never_replace_real_code():
    new = '''class Runner:
    def run(self, code):
        ...  # unchanged

    def _process(self, code):
        """Process the code."""
        return code.strip()
'''
    code, changed, left_out = fit(OLD, new)
    assert changed == ["_process"] and left_out == ["run, sent only as a placeholder"]
    assert load(code)["Runner"]().run(" a ") == "a"


def test_a_whole_file_with_placeholders_is_merged_not_copied():
    new = OLD.replace("        return code.upper()", "        ...").replace("    return text\n", "    return text + '!'\n")
    code, changed, _ = fit(OLD, new)
    assert changed == ["feed"] and "return code.upper()" in code


def test_nested_functions_new_functions_settings_and_imports():
    new = '''import time
TIMEOUT = 5

def time_up():
    return "too late"

def helper(x):
    return x + 1

def extra(self):
    return self.count
'''
    code, changed, _ = fit(OLD, new)
    assert changed == ["import time", "TIMEOUT", "time_up", "helper", "extra"]
    runner = load(code)
    assert runner["Runner"]().extra() == 0 and runner["helper"](1) == 2 and runner["TIMEOUT"] == 5
    assert code.index("TIMEOUT = 5") < code.index("class Runner") and code.count("import time") == 1
    assert code.index("def helper") < code.index('if __name__') and code.count("def time_up") == 1
    assert '"too late"' in code


def test_a_function_inside_a_replaced_one_comes_with_it():
    new = '''def run(self, code):
    def time_up():
        return "late!"
    return self._process(code) + "?"

def time_up():
    return "ignored"
'''
    code, changed, _ = fit(OLD, new)
    assert changed == ["run"] and '"late!"' in code and "ignored" not in code
    assert load(code)["Runner"]().run("a") == "A?"


def test_a_function_without_self_does_not_replace_a_method():
    with pytest.raises(MergeError, match="run, a method of Runner sent without self"):
        fit(OLD, "def run(code):\n    return code\n")


def test_turning_a_class_into_a_function_is_refused():
    with pytest.raises(MergeError, match="would lose Runner.__init__, Runner._process, Runner.run"):
        fit(OLD, "def Runner():\n    return 1\n")


def test_example_code_alone_changes_nothing():
    with pytest.raises(MergeError, match="nothing in the new code fits"):
        fit(OLD, "runner = Runner()\nprint(runner.run('x'))\n")


def test_a_complete_new_version_replaces_the_file():
    new = OLD.replace("LIMIT = 3", "LIMIT = 4") + "\n\ndef more():\n    return 1\n"
    assert fit(OLD, new) == (new, None, [])


def test_the_auto_improve_answer_for_code_executor_fits(tmp_path):
    """The kind of answer behind "the new code removes CodeExecutor, RUN_FILE_PREFIX, ...":
    the functions Auto-Improve named, each with a docstring added, without their class."""
    old = (Path(__file__).parent.parent / "code_executor.py").read_text(encoding="utf-8")
    lines = old.splitlines()
    tree = ast.parse(old)
    nodes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    answer = []
    for name in ["feed", "_was_stopped", "_install", "_run"]:
        node = nodes[name]
        body_start = node.body[0].lineno - 1
        indent = " " * node.body[0].col_offset
        function = lines[node.lineno - 1:body_start] + [f'{indent}"""{name} docstring."""'] + \
            lines[body_start:node.end_lineno]
        answer.append(textwrap.dedent("\n".join(function)))
    (tmp_path / "code_executor.py").write_text(old, encoding="utf-8")
    um = UpgradeManager(tmp_path, tmp_path / "backups", allowed_files=["code_executor.py"])

    ok, message = um.apply_upgrade("code_executor.py", "```python\n" + "\n\n".join(answer) + "\n```", "docstrings")

    assert ok, message
    assert "changed feed, _was_stopped, _install, _run; the rest is as it was" in message
    merged = (tmp_path / "code_executor.py").read_text(encoding="utf-8")
    assert definitions(ast.parse(merged)).keys() == definitions(tree).keys()
    assert merged.count('docstring."""') == 4
    # The upgraded runner still runs code
    spec = importlib.util.spec_from_file_location("upgraded_executor", tmp_path / "code_executor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ok, out = module.CodeExecutor(tmp_path / "run", timeout=20).execute_code("print(6 * 7)")
    assert ok and "42" in out
