"""Reading code answers: the ``` blocks in them and the packages they say to pip install."""
import re

PYTHON_LANGUAGES = ("python", "py", "python3", "py3")

# Import names whose pip package is called something else
PIP_NAMES = {
    "cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn", "skimage": "scikit-image",
    "yaml": "pyyaml", "bs4": "beautifulsoup4", "dotenv": "python-dotenv", "docx": "python-docx",
    "pptx": "python-pptx", "fitz": "pymupdf", "dateutil": "python-dateutil", "serial": "pyserial",
    "Crypto": "pycryptodome", "win32api": "pywin32", "win32con": "pywin32", "win32gui": "pywin32",
    "win32com": "pywin32", "attr": "attrs", "OpenGL": "PyOpenGL", "usb": "pyusb", "jwt": "PyJWT",
    "telegram": "python-telegram-bot", "discord": "discord.py", "googleapiclient": "google-api-python-client",
    "Levenshtein": "python-Levenshtein", "wx": "wxPython", "gi": "PyGObject", "mpl_toolkits": "matplotlib",
    "speech_recognition": "SpeechRecognition", "pygame_gui": "pygame-gui", "Xlib": "python-xlib",
}

# "pip install x y", "python -m pip install x", "!pip install x" (notebooks), "$ pip install x"
PIP_LINE = re.compile(r'^[ \t]*(?:[$>][ \t]*)?[!%]?[ \t]*(?:(?:py|python3?|python\.exe)[ \t]+(?:-3[ \t]+)?-m[ \t]+)?'
                      r'pip3?[ \t]+install[ \t]+([^\n`]+)', re.MULTILINE)
INLINE_PIP = re.compile(r'`[ \t]*(?:(?:py|python3?)[ \t]+-m[ \t]+)?pip3?[ \t]+install[ \t]+([^`\n]+)`')
OPTIONS_WITH_VALUE = {"-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url",
                      "--extra-index-url", "-f", "--find-links", "-t", "--target"}
PACKAGE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9._,-]+\])?((==|>=|<=|~=|!=|>|<)[A-Za-z0-9.*+!-]+)?$')
MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'")
FENCE = re.compile(r'^(`{3,}|~{3,})[ \t]*([\w+#.-]*)[ \t]*$')


def packages_in(args):
    """Package names from what follows 'pip install'. Options, files and URLs are left out,
    and reading stops at the first word that isn't a package name."""
    names, skip = [], False
    for token in re.split(r'&&|;|\||#', args)[0].split():
        token = token.strip("'\",")
        if skip or token.startswith("-"):
            skip = token in OPTIONS_WITH_VALUE
            continue
        if not PACKAGE_NAME.match(token) or token.endswith((".txt", ".whl", ".zip", ".gz", ".py")):
            break
        names.append(token)
    return names


def code_blocks(text):
    """(language, code) of each complete ``` block, in order. An unfinished block is left out."""
    blocks, fence, language, indent, lines = [], None, "", 0, []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if fence is None:
            match = FENCE.match(stripped)
            if match:
                fence, language, lines = match.group(1), match.group(2).lower(), []
                indent = len(line) - len(line.lstrip())
        elif stripped.startswith(fence) and not stripped.strip(fence[0]):
            blocks.append((language, "\n".join(lines)))
            fence = None
        else:
            # Blocks inside a list are indented: drop the fence's indentation from each line
            lines.append(line[min(indent, len(line) - len(line.lstrip())):])
    return blocks


def only_pip_lines(code):
    lines = [line for line in code.splitlines() if line.strip()]
    return bool(lines) and all(PIP_LINE.match(line) for line in lines)
