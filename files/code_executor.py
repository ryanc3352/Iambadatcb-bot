import os
import signal
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from code_parsing import (INLINE_PIP, MISSING_MODULE, PIP_LINE, PIP_NAMES, PYTHON_LANGUAGES, code_blocks,
                          only_pip_lines, packages_in)

# Code from the chat is written to a hidden file with this prefix in the folder it runs in
RUN_FILE_PREFIX = ".ai_run_"


class CodeExecutor:
    """Runs Python code in a separate process, installing missing packages first.

    This is NOT a security sandbox: the code runs with your user's permissions.
    Only execute code you have read and trust.
    """

    def __init__(self, working_dir="./ai_files", timeout=0):
        """
        Args:
            working_dir: Folder the code runs in (relative file paths land here)
            timeout (int): Seconds before the process is stopped; 0 means no limit
        """
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._running = {}  # run id -> process, for the Stop button
        self._stopped = set()
        self._lock = threading.Lock()

    def extract_code(self, text: str) -> tuple:
        """The first Python code block (or, without one, the first unlabelled block).

        Returns:
            tuple: (has_code, code_content)
        """
        blocks = [(language, code) for language, code in code_blocks(text) if code.strip()]
        for language, code in blocks:
            if language in PYTHON_LANGUAGES:
                return True, code
        for language, code in blocks:
            if not language and not only_pip_lines(code):
                return True, code
        return False, None

    def find_packages(self, text: str) -> list:
        """Packages the answer says to pip install (in code blocks or `pip install x`), without repeats."""
        commands = [match.group(1) for _, code in code_blocks(text) for match in PIP_LINE.finditer(code)]
        commands += [match.group(1) for match in INLINE_PIP.finditer(text or "")]
        names = []
        for command in commands:
            names += packages_in(command)
        return list(dict.fromkeys(names))

    def split_pip_lines(self, code):
        """Remove 'pip install x' / '!pip install x' lines (not valid Python) and return their packages."""
        packages, kept = [], []
        for line in code.splitlines():
            match = PIP_LINE.match(line)
            if match:
                packages += packages_in(match.group(1))
            else:
                kept.append(line)
        return "\n".join(kept), packages

    def package_for(self, module, folder=None):
        """The pip package that provides an import name, or None when pip can't help."""
        top = module.split(".")[0]
        folder = Path(folder or self.working_dir)
        if top in getattr(sys, "stdlib_module_names", ()):
            return None  # part of Python itself (e.g. tkinter left out of the install)
        if (folder / f"{top}.py").exists() or (folder / top).is_dir():
            return None  # the user's own file, not a package from the internet
        return PIP_NAMES.get(top, top.replace("_", "-"))

    def execute_code(self, code: str, packages=(), stdin_text="", run_id=None, on_output=None,
                     folder=None, script=None) -> tuple:
        """Install the packages (and any the code turns out to miss), then run the code.

        Args:
            packages: pip package names to install first
            stdin_text: what the program reads with input(), one answer per line
            run_id: name for stop()
            on_output: called with each line of output while the code runs
            folder: where the code runs (default: the working folder), e.g. a project folder
            script: run this saved .py file in its own folder instead of `code`

        Returns:
            tuple: (success, output)
        """
        run_id = run_id or uuid.uuid4().hex
        report = on_output or (lambda text: None)
        if script:
            script = Path(script)
            folder = script.parent
            code, notebook_packages = script.read_text(encoding="utf-8", errors="replace"), []
        else:
            code, notebook_packages = self.split_pip_lines(code)
        folder = Path(folder or self.working_dir)
        notes = []
        try:
            wanted = list(dict.fromkeys([*packages, *notebook_packages]))
            if wanted:
                ok, output = self._install(wanted, run_id, report, notes)
                if not ok:
                    return False, "\n".join(notes + [output])
            tried = set()
            while True:
                success, output = self._run(code, stdin_text, run_id, report, folder, script)
                missing = None if success else MISSING_MODULE.search(output)
                package = missing and self.package_for(missing.group(1), folder)
                if not package or package in tried or len(tried) >= 5 or self._was_stopped(run_id):
                    break
                tried.add(package)
                ok, install_output = self._install([package], run_id, report, notes)
                if not ok:
                    output += "\n\n" + install_output
                    break
                report("🔁 Running the code again ...\n")
            if not success and "EOFError" in output and not stdin_text and "input(" in code:
                output += ("\n\nThis program asks you to type something. Put your answers in the "
                           "\"Typed answers\" box (one per line) and run it again.")
            return success, "\n".join(notes + [output]).strip()
        finally:
            with self._lock:
                self._running.pop(run_id, None)
                self._stopped.discard(run_id)

    def install(self, packages, run_id, report):
        """pip install into the Python the app runs on (the .venv made by start.py).

        Returns:
            tuple: (success, pip output)
        """
        command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *packages]
        return self._process(command, None, run_id, report, None, self.working_dir)

    def stop(self, run_id) -> bool:
        """Stop a running program (and anything it started). Returns False if nothing was running."""
        with self._lock:
            process = self._running.get(run_id)
            if process is None:
                return False
            self._stopped.add(run_id)
        kill_tree(process)
        return True

    def _was_stopped(self, run_id):
        with self._lock:
            return run_id in self._stopped

    def _install(self, packages, run_id, report, notes):
        names = ", ".join(packages)
        report(f"📦 Installing {names} (only the first time) ...\n")
        ok, output = self.install(packages, run_id, lambda text: None)
        if ok:
            notes.append(f"📦 Installed {names}")
            return True, output
        tail = "\n".join(output.strip().splitlines()[-15:])
        return False, f"📦 Couldn't install {names}:\n{tail}"

    def _run(self, code, stdin_text, run_id, report, folder, script=None):
        # Code from the chat goes in a hidden file in the folder it runs in: the program's input()
        # reads the typed answers, and it can import the other .py files in that folder
        path = script or folder / f"{RUN_FILE_PREFIX}{uuid.uuid4().hex[:12]}.py"
        try:
            if not script:
                path.write_text(code, encoding="utf-8")
            # -E -s: ignore the user's Python settings (but keep the script's folder importable);
            # -u: show output as it comes; -X utf8: emoji/non-English text work on Windows consoles
            command = [sys.executable, "-E", "-s", "-u", "-X", "utf8", str(path)]
            success, output = self._process(command, stdin_text, run_id, report, self.timeout or None, folder)
        except OSError as e:
            return False, f"Couldn't write the code to {folder}: {e}"
        finally:
            if not script:
                try:
                    path.unlink()
                except OSError:
                    pass
        if success:
            return True, output.strip() or "✅ Code executed successfully"
        return False, output.strip() or "The code stopped with an error"

    def _process(self, command, stdin_text, run_id, report, timeout, cwd):
        """Run a command in cwd, passing each output line to report. Returns (success, all output)."""
        try:
            process = subprocess.Popen(
                command, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt")
        except OSError as e:
            return False, f"Could not start Python: {e}"
        with self._lock:
            if run_id in self._stopped:
                kill_tree(process)
            self._running[run_id] = process
        if stdin_text:
            text = stdin_text if stdin_text.endswith("\n") else stdin_text + "\n"
            threading.Thread(target=feed, args=(process, text), daemon=True).start()
        timer = None
        timed_out = threading.Event()
        if timeout:
            def time_up():
                timed_out.set()
                kill_tree(process)
            timer = threading.Timer(timeout, time_up)
            timer.start()
        lines = []
        for line in process.stdout:
            lines.append(line)
            report(line)
        process.wait()
        if timer:
            timer.cancel()
        output = "".join(lines)
        if self._was_stopped(run_id):
            return False, (output + "\n⏹ Stopped").strip()
        if timed_out.is_set():
            return False, (output + f"\nTimeoutError: code ran longer than {timeout}s and was stopped").strip()
        return process.returncode == 0, output


def feed(process, text):
    try:
        process.stdin.write(text)
        process.stdin.close()
    except OSError:
        pass  # the program ended without reading everything


def kill_tree(process):
    """Stop a process and the programs it started (windows, servers, ...)."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    if process.poll() is None:
        process.kill()
