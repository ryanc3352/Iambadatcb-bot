import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_frontend_javascript():
    tests = Path(__file__).with_name("frontend.test.js")
    result = subprocess.run(["node", "--test", str(tests)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr
