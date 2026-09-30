"""Files the AI offers to save: its SAVE_FILE blocks, or its answer when it wouldn't write one.

Small models (like mistral) often answer "I can't create files, but you can...", so saving a
file never depends on the model using the SAVE_FILE format.
"""
import re

from services import conversation_history, file_handler


SAVE_FILE_BLOCK = re.compile(
    r"SAVE_FILE:\**[ \t]*`?([^\n`*]+?)`?\**[ \t]*\n+```[\w+.-]*[ \t]*\n(.*?)\n?```", re.DOTALL)

# Requests to create or change a file: "make a file with...", "save this as notes.md", "add eggs to shopping.txt"
FILE_NAME = re.compile(
    r"(?<![\w/.-])((?:[\w-]+/)*[\w-]+\.(?:txt|md|py|js|ts|html|css|json|csv|xml|ya?ml|toml|ini|cfg|log|sql|bat|ps1|sh))\b",
    re.IGNORECASE)

FILE_REQUEST = re.compile(
    r"\b(?:create|make|write|save|generate|put|store|export|add|update|edit|change|append|turn|draft)\b"
    rf"[^.?!\n]*?(?:\b(?:files?|documents?|txt)\b|{FILE_NAME.pattern})"
    r"|\bsave (?:it|this|that|them)\b|\bsave\b[^.?!\n]*?\b(?:list|notes?)\b", re.IGNORECASE)

# "main_fixed.py", "new_main.py", "main_v2.py": a changed copy of main.py
VARIANT_WORDS = r"(?:new|updated?|fixed|fix|modified|improved|final|edited|revised|corrected|copy)"
VARIANT = re.compile(rf"^(?:{VARIANT_WORDS}[_-])*(.+?)(?:[_-](?:{VARIANT_WORDS}|v?\d{{1,2}}))*$", re.IGNORECASE)
NEW_FILE_REQUEST = re.compile(r"\b(?:new|another|separate|second|copy|duplicate|create)\b[^.?!\n]*\bfiles?\b"
                              r"|\bsave (?:it |this |that )?as\b", re.IGNORECASE)

HOW_TO_QUESTION = re.compile(r"\s*how (?:do|can|could|should|would) (?:i|we|you)\b|\s*how to\b", re.IGNORECASE)

FILE_REQUEST_NOTE = ("The user wants a file. You CAN create and change files: write a SAVE_FILE block "
                     "(the line 'SAVE_FILE: name.ext', then the complete content in a ``` block) and the app "
                     "shows the user a Save button. Don't say you can't create files, and don't tell the user "
                     "to create, copy or paste the file themselves.")

CODE_FENCE = re.compile(r"```([\w+.-]*)[ \t]*\n(.*?)\n?```", re.DOTALL)

LANGUAGE_EXTENSIONS = {'python': 'py', 'py': 'py', 'javascript': 'js', 'js': 'js', 'typescript': 'ts', 'ts': 'ts',
                       'html': 'html', 'css': 'css', 'json': 'json', 'markdown': 'md', 'md': 'md', 'csv': 'csv',
                       'xml': 'xml', 'yaml': 'yaml', 'yml': 'yaml', 'toml': 'toml', 'ini': 'ini', 'sql': 'sql',
                       'bash': 'sh', 'sh': 'sh', 'shell': 'sh', 'batch': 'bat', 'bat': 'bat', 'cmd': 'bat',
                       'powershell': 'ps1', 'ps1': 'ps1'}

# Lines where the model talks about the file instead of writing it: "I can't create files, but you can..."
FILE_TALK = re.compile(r"\b(?:files?|save|saving|saved|create|creating|copy|paste|notepad|text editor)\b",
                       re.IGNORECASE)

TALKING_TO_USER = re.compile(r"\b(?:i|you|your)\b", re.IGNORECASE)


def wants_file(user_input):
    """Whether the user asks for a file to be created or changed (not how to do it themselves)."""
    return not HOW_TO_QUESTION.match(user_input) and bool(FILE_REQUEST.search(user_input))


def find_file_saves(response, user_input=""):
    """Files to offer the user: SAVE_FILE blocks -> [{'path', 'content', 'exists'}].

    Small models often answer a file request with "I can't create files, but you can...".
    Then the answer itself is offered as the file.
    """
    saves = []
    existing = {f['path'] for f in file_handler.list_all_files()}
    for match in SAVE_FILE_BLOCK.finditer(response):
        try:
            path = file_handler.clean_relative_path(match.group(1))
        except ValueError:
            continue
        saves.append({'path': existing_original(path, existing, user_input), 'content': match.group(2)})
    if not saves and user_input and "UPGRADE_REQUEST:" not in response and wants_file(user_input):
        suggestion = suggest_file(user_input, response)
        if suggestion:
            saves.append(suggestion)
    for save in saves:
        save['exists'] = save['path'] in existing
    return saves[:5]


def existing_original(path, existing, user_input=""):
    """'main_fixed.py' -> 'main.py' when main.py is saved: a change goes back into the same file,
    unless the user asked for a new file or named this one."""
    if path in existing or path.lower() in user_input.lower() or NEW_FILE_REQUEST.search(user_input):
        return path
    folder, _, name = path.rpartition('/')
    stem, dot, extension = name.rpartition('.')
    if not dot or not stem:
        return path
    original = (f"{folder}/" if folder else "") + f"{VARIANT.match(stem).group(1)}.{extension}"
    return original if original in existing else path


def recent_file(extension):
    """The saved file with this extension named last in the chat (the one being changed), or None."""
    existing = {f['path'] for f in file_handler.list_all_files()}
    for message in reversed(conversation_history.get_last_n_messages(6)):
        for name in reversed(FILE_NAME.findall(message['content'])):
            try:
                path = file_handler.clean_relative_path(name)
            except ValueError:
                continue
            if path in existing and path.lower().endswith(f".{extension}"):
                return path
    return None


def suggest_file(user_input, response):
    """The answer as a file: its largest code block, or else its text without the lines
    about creating the file. None if there's nothing to save."""
    blocks = [block for block in CODE_FENCE.finditer(response) if not _is_folder_listing(block.group(2))]
    if blocks:
        block = max(blocks, key=lambda b: len(b.group(2)))
        language, content = block.group(1), block.group(2)
        before, after = response[:block.start()], response[block.end():]
    else:
        lines = response.splitlines()
        kept = [line for line in lines if not (FILE_TALK.search(line) and TALKING_TO_USER.search(line))]
        if len(kept) == len(lines):       # not about a file at all, e.g. a question back
            return None
        language, content, before, after = '', "\n".join(kept).strip(), response, ''
    if not content.strip():
        return None
    # The name the user gave, else the one the model mentions just before (or after) the content
    extension = LANGUAGE_EXTENSIONS.get(language.lower(), 'txt')
    # ...or the file this chat is about ("fix it"), before making up a new name
    names = (FILE_NAME.findall(user_input) or FILE_NAME.findall(before)[-1:] or FILE_NAME.findall(after)[:1]
             or [name for name in [recent_file(extension)] if name])
    for name in names + [_unused_name('notes' if extension == 'txt' else 'new_file', extension)]:
        try:
            return {'path': file_handler.clean_relative_path(name), 'content': content}
        except ValueError:
            continue
    return None


def _is_folder_listing(text):
    """A tree like '├── encrypt.py' (the model showing files), not file content."""
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(lines) and sum(any(c in line for c in '├└│') for line in lines) >= len(lines) / 2


def _unused_name(stem, extension):
    """stem.ext, or stem_2.ext etc. if that file already exists."""
    existing = {f['path'] for f in file_handler.list_all_files()}
    name, number = f"{stem}.{extension}", 2
    while name in existing:
        name, number = f"{stem}_{number}.{extension}", number + 1
    return name
