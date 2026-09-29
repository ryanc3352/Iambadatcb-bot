import json
import logging
import platform
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, Response, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

# config loads the .env file, so import it before anything that reads settings
from config import (
    BASE_DIR, DATABASE_PATH, VECTOR_DB_PATH, AI_FILES_PATH, BACKUPS_PATH, LOGS_PATH,
    OLLAMA_URL, MODEL_NAME, MODEL_TEMPERATURE, MODEL_MAX_TOKENS, MODEL_CONTEXT_TOKENS, MODEL_TIMEOUT,
    CONTEXT_MESSAGES, SEARCH_TOP_K, SYSTEM_PROMPT,
    ENABLE_CODE_EXECUTION, CODE_EXECUTION_TIMEOUT, ENABLE_SELF_IMPROVEMENT, LEARNING_ENABLED,
    HOST, PORT, DEBUG, MAX_UPLOAD_MB, UPGRADEABLE_FILES, USER_SETTINGS_PATH,
)
from llm_interface import LLMInterface, LLMError, ThinkFilter
from model_manager import ModelManager
from conversation_history import ConversationHistory
from memory import Memory
from code_executor import CodeExecutor
from file_handler import FileHandler
from upgrade_manager import UpgradeManager
from knowledge_base import KnowledgeBase
from web_search import WebSearcher
from conversation_manager import ConversationManager
from weather_provider import WeatherProvider
from folder_manager import FolderManager
from self_analyzer import SelfAnalyzer
from learning_system import LearningSystem
from autonomous_improver import AutonomousImprover
from calculator import math_context
from app_logging import setup_logging, recent_lines

setup_logging(LOGS_PATH)  # before Flask sets up its own logger
log = logging.getLogger("assistant")

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

# Limits for uploaded ZIP folders (protects against zip bombs)
MAX_ZIP_FILES = 5000
MAX_ZIP_UNCOMPRESSED = 500 * 1024 * 1024

conversation_history = ConversationHistory(DATABASE_PATH)
llm_interface = LLMInterface(MODEL_NAME, MODEL_TEMPERATURE, MODEL_MAX_TOKENS, OLLAMA_URL,
                             context_tokens=MODEL_CONTEXT_TOKENS, timeout=MODEL_TIMEOUT)
memory = Memory(VECTOR_DB_PATH)
code_executor = CodeExecutor(working_dir=AI_FILES_PATH, timeout=CODE_EXECUTION_TIMEOUT)
file_handler = FileHandler(AI_FILES_PATH)
web_searcher = WebSearcher()
weather_provider = WeatherProvider()
conversation_manager = ConversationManager(DATABASE_PATH)
knowledge_base = KnowledgeBase(VECTOR_DB_PATH)
upgrade_manager = UpgradeManager(BASE_DIR, BACKUPS_PATH, UPGRADEABLE_FILES)
folder_manager = FolderManager(AI_FILES_PATH)
analyzer = SelfAnalyzer(BASE_DIR, BACKUPS_PATH)
learner = LearningSystem(BACKUPS_PATH, enabled=LEARNING_ENABLED)
improver = AutonomousImprover(analyzer, learner, BACKUPS_PATH)
model_manager = ModelManager(llm_interface, USER_SETTINGS_PATH)
log.info("App starting with model %s", llm_interface.model_name)

WEATHER_KEYWORDS = ['weather', 'forecast', 'temperature', 'rain', 'snow', 'sunny', 'cloudy',
                    'celsius', 'fahrenheit', 'degrees', 'wind']
# Clear signs a question needs live data (the model can also ask for a search itself)
SEARCH_KEYWORDS = ['news', 'latest', 'breaking', 'stock price', 'exchange rate', 'time in']
TIME_WORDS = r'(?:today|tomorrow|tonight|right now|now|this weekend|this week|morning|afternoon|evening|night)'
# Words that can follow "in/for/at" or sit next to "weather" but are not places
NOT_PLACES = {'a', 'an', 'my', 'your', 'our', 'their', 'this', 'that', 'some', 'any', 'i', 'it', 'what',
              'how', 'is', 'will', 'the', 'good', 'nice', 'bad', 'current', 'general', 'python', 'code'}
# Largest file whose code is added to the prompt when the user names it
MAX_CODE_CONTEXT_CHARS = 12000
# Files the AI saves for the user
MAX_SAVED_FILE_CHARS = 1_000_000
FILE_WORDS = ['file', 'files', 'save', 'saved', 'note', 'notes', 'list', 'document', 'create', 'add',
              'folder', 'folders', 'directory', 'ai_files']
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
# Folders picked in the browser: skip bulky tool folders
SKIPPED_UPLOAD_PARTS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.idea', '.vscode'}


def json_body():
    """Return the request's JSON object, or {} if there is none."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _contains_word(text, words):
    return any(re.search(rf'\b{re.escape(w)}\b', text) for w in words)


def extract_location(user_input):
    """Find the place name in a weather question, e.g. 'weather in New York tomorrow?'."""
    # Drop trailing time words ("... tomorrow morning?"), then take the place after the LAST in/for/at
    text = re.sub(rf"(?:\s*\b(?:for\s+)?{TIME_WORDS}\b)+[?.!]*\s*$", "", user_input.strip(), flags=re.IGNORECASE)
    match = re.search(r".*\b(?:in|for|at)\s+([A-Za-z][A-Za-z .,'-]*?)[?.!]*\s*$", text, re.IGNORECASE)
    if match:
        location = re.sub(r"^the\s+", "", match.group(1).strip(" ,."), flags=re.IGNORECASE)
        if location and location.split()[0].lower() not in NOT_PLACES:
            return location
        return None

    # "Tokyo weather" / "weather Berlin": capitalized words right before or after a weather word
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)

    def is_place_word(word):
        return word[0].isupper() and word.lower() not in NOT_PLACES

    for i, word in enumerate(words):
        if word.lower() not in WEATHER_KEYWORDS:
            continue
        after = []
        for w in words[i + 1:]:
            if not is_place_word(w):
                break
            after.append(w)
        before = []
        for w in reversed(words[:i]):
            if not is_place_word(w):
                break
            before.insert(0, w)
        if after or before:
            return ' '.join(after or before)
    return None


def get_live_context(user_input, found_locally=False):
    """Fetch weather or web search results when the question needs live data.

    The keyword web search is skipped when the user's documents already cover the
    question: local first, the internet second.
    """
    text = user_input.lower()
    try:
        if _contains_word(text, WEATHER_KEYWORDS):
            location = extract_location(user_input)
            if location:
                learner.log_feature_usage('weather')
                if 'tomorrow' in text:
                    report = weather_provider.get_weather_for_tomorrow(location)
                else:
                    report = weather_provider.get_weather(location)
                # A lowercase guess ("weather for running") that isn't a real place: add nothing
                if not (report.startswith("❌ Could not find location") and location[:1].islower()):
                    return report

        if _contains_word(text, SEARCH_KEYWORDS) and not found_locally:
            learner.log_web_search()
            return web_searcher.search(user_input, num_results=5)
    except Exception as e:
        return f"(Search error: {e})"
    return ""


def get_file_context(user_input, recent_conversation=""):
    """What's really in the user's ai_files folder, when files come up or the model offered one
    recently (so it doesn't make files up), and the content of files the user names."""
    files = [f['path'] for f in file_handler.list_all_files()]
    text = user_input.lower()
    named = [f for f in files if f.lower() in text or Path(f).name.lower() in text][:2]
    if not (named or _contains_word(text, FILE_WORDS) or "SAVE_FILE:" in recent_conversation):
        return ""
    if not files:
        return "The user's ai_files folder is empty: no files have been saved yet."
    listing = ", ".join(files[:30]) + (f" and {len(files) - 30} more" if len(files) > 30 else "")
    parts = [f"Files saved in the user's ai_files folder right now (the complete list: no other files exist "
             f"there, and a file you offered only exists once the user clicked Save): {listing}"]
    for name in named:
        try:
            content = file_handler.read_file(name)
        except (OSError, ValueError, PermissionError):
            continue
        shown = content[:4000] + ("\n[... rest of file not shown]" if len(content) > 4000 else "")
        parts.append(f"Current content of {name}:\n```\n{shown}\n```")
    return "\n\n".join(parts)


def wants_file(user_input):
    """Whether the user asks for a file to be created or changed (not how to do it themselves)."""
    return not HOW_TO_QUESTION.match(user_input) and bool(FILE_REQUEST.search(user_input))


def find_file_saves(response, user_input=""):
    """Files to offer the user: SAVE_FILE blocks -> [{'path', 'content', 'exists'}].

    Small models often answer a file request with "I can't create files, but you can...".
    Then the answer itself is offered as the file.
    """
    saves = []
    for match in SAVE_FILE_BLOCK.finditer(response):
        try:
            path = file_handler.clean_relative_path(match.group(1))
        except ValueError:
            continue
        saves.append({'path': path, 'content': match.group(2)})
    if not saves and user_input and "UPGRADE_REQUEST:" not in response and wants_file(user_input):
        suggestion = suggest_file(user_input, response)
        if suggestion:
            saves.append(suggestion)
    existing = {f['path'] for f in file_handler.list_all_files()}
    for save in saves:
        save['exists'] = save['path'] in existing
    return saves[:5]


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
    names = FILE_NAME.findall(user_input) or FILE_NAME.findall(before)[-1:] or FILE_NAME.findall(after)[:1]
    extension = LANGUAGE_EXTENSIONS.get(language.lower(), 'txt')
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


def get_code_context(user_input):
    """Add the current code of upgradeable files the user names, so upgrades start from the real file.

    Files are added in the order they are mentioned, within one size budget.
    """
    mentioned = []
    for name in UPGRADEABLE_FILES:
        match = re.search(rf"\b{re.escape(name)}\b", user_input, re.IGNORECASE)
        if match:
            mentioned.append((match.start(), name))

    parts, budget = [], MAX_CODE_CONTEXT_CHARS
    for _, name in sorted(mentioned):
        success, code = upgrade_manager.get_file_code(name)
        if not success:
            continue
        if len(code) <= budget:
            parts.append(f"Current code of {name}:\n```python\n{code}\n```")
            budget -= len(code)
        else:
            parts.append(f"{name} is too large to show here ({len(code)} characters). "
                         f"Suggest specific changes instead of a full-file UPGRADE_REQUEST.")
    return "\n\n".join(parts)


def build_prompt(user_input, extra_context=""):
    """Build prompt with context from memory, documents, conversation history, weather, and web search.

    Call this before saving the new message, so it isn't repeated in 'Recent conversation'.
    """
    # Local knowledge first; the web is only searched if nothing relevant is found here
    similar_context = memory.get_context_from_search(user_input, SEARCH_TOP_K)
    doc_context = knowledge_base.get_context_from_documents(user_input, top_k=3)
    if doc_context:
        learner.log_knowledge_base_query()
    # Only the user's own documents count: an old chat about "latest news" looks similar
    # to a new question but its answer is out of date
    live_context = get_live_context(user_input, found_locally=bool(doc_context))
    calculator_context = math_context(user_input)
    code_context = get_code_context(user_input)
    recent_messages = conversation_history.get_last_n_messages(CONTEXT_MESSAGES)
    formatted_history = conversation_history.format_for_prompt(recent_messages)
    file_context = get_file_context(user_input, formatted_history)
    feedback = learner.get_feedback_guidance()

    now = datetime.now().strftime("%A %d %B %Y, %H:%M")
    sections = [SYSTEM_PROMPT, f"Current date and time: {now}", feedback, extra_context, code_context, file_context,
                live_context, calculator_context, doc_context, similar_context,
                f"Recent conversation:\n{formatted_history}" if formatted_history else "",
                FILE_REQUEST_NOTE if wants_file(user_input) else ""]  # last, so small models don't miss it
    context = "\n\n".join(s.strip() for s in sections if s and s.strip())
    return f"{context}\n\nUser: {user_input}\nAssistant:"


SEARCH_PREFIX = "SEARCH:"


def search_request(text):
    """The query if the model's reply is a 'SEARCH: ...' request, else None."""
    match = re.match(r"\s*SEARCH:[ \t]*(.+)", text, re.IGNORECASE)
    return match.group(1).strip()[:200] if match and match.group(1).strip() else None


def search_context(query):
    """Run a search the model asked for and phrase the results for the second pass."""
    learner.log_web_search()
    log.info("Web search: %s", query)
    results = web_searcher.search(query)
    return (f"You asked to search the web for '{query}'. Results:\n{results}\n\n"
            f"Answer the user's question now using these results. Do not reply with SEARCH again.")


def generate_answer(user_input, extra_context=""):
    """Get the model's answer; if it asks to search first, search and ask again."""
    response = llm_interface.generate_response(build_prompt(user_input, extra_context))
    query = search_request(response)
    if not query:
        return response
    extra = "\n\n".join(part for part in (extra_context, search_context(query)) if part)
    response = llm_interface.generate_response(build_prompt(user_input, extra))
    if search_request(response):
        return f"I searched the web for '{query}' but couldn't find a clear answer."
    return response


def stream_answer(user_input, prompt, extra_context=""):
    """Stream the model's answer as ('token', text) events.

    If the reply starts with 'SEARCH: <query>', that reply is dropped, a ('search', query)
    event is sent, and the answer written with the search results is streamed instead.
    Reasoning models' <think>...</think> text is hidden; a ('thinking', True) event is sent.
    """
    raw = llm_interface.generate_response_stream(prompt)
    stream = _visible_tokens(raw)
    buffer, passthrough = "", False
    for token in stream:
        if isinstance(token, _Thinking):
            yield 'thinking', True
            continue
        if passthrough:
            yield 'token', token
            continue
        buffer += token
        head = buffer.lstrip()
        if len(head) < len(SEARCH_PREFIX) and SEARCH_PREFIX.startswith(head.upper()):
            continue                      # too short to tell yet
        if head.upper().startswith(SEARCH_PREFIX):
            if "\n" in head.strip():      # the query line is complete
                break
            continue
        passthrough = True
        yield 'token', buffer
    stream.close()                        # stop the model if it's still writing
    raw.close()
    if passthrough:
        return
    query = search_request(buffer)
    if not query:
        if buffer:
            yield 'token', buffer
        return
    yield 'search', query
    extra = "\n\n".join(part for part in (extra_context, search_context(query)) if part)
    for token in _visible_tokens(llm_interface.generate_response_stream(build_prompt(user_input, extra))):
        yield ('thinking', True) if isinstance(token, _Thinking) else ('token', token)


class _Thinking(str):
    """Marker yielded by _visible_tokens when a model starts thinking."""


def _visible_tokens(tokens):
    """Tokens without <think>...</think>; yields a _Thinking marker when thinking starts."""
    think = ThinkFilter()
    announced = False
    for token in tokens:
        visible = think.feed(token)
        if think.started and not announced:
            announced = True
            yield _Thinking()
        if visible:
            yield visible
    rest = think.flush()
    if rest:
        yield rest


def find_runnable_code(response):
    """Code the user may run. Upgrades and files to save are not run, so they don't count."""
    if "UPGRADE_REQUEST:" in response or "SAVE_FILE:" in response:
        return False, None
    return code_executor.extract_code(response)


def _short(text, limit):
    """One line of at most `limit` characters, for the log."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def log_exchange(user_input, response, files, error=None):
    """Log a question, its answer and the files offered (shortened), for the 🐞 logs button."""
    log.info("Question: %s", _short(user_input, 300))
    if error:
        log.warning("Answer failed: %s", error)
    else:
        log.info("Answer from %s: %s", llm_interface.model_name, _short(response, 800))
    if files:
        log.info("Offered to save: %s", ", ".join(
            f['path'] + (" (replaces the saved one)" if f.get('exists') else "") for f in files))


def record_exchange(user_input, response):
    """Save a user/assistant exchange to history, vector memory and learning logs."""
    conversation_history.add_message("User", user_input)
    message_id = conversation_history.add_message("Assistant", response)
    if message_id is not None:
        memory.add_conversation(user_input, response, message_id)
    if LEARNING_ENABLED:
        learner.log_conversation(user_input, response)


@app.errorhandler(LLMError)
def handle_llm_error(e):
    """The model couldn't answer (Ollama not running, model missing, timeout)."""
    log.warning("Model error: %s", e)
    return jsonify({'error': str(e)}), 503


WINDOWS_WRITE_HINT = ("Windows may be blocking Python from writing in this folder (Controlled folder access, "
                      "OneDrive, or a read-only location). Move the project to a simple folder like C:\\AI "
                      "or set DATA_DIR in .env.")


@app.errorhandler(PermissionError)
def handle_permission_error(e):
    """Our own path checks explain themselves; errors from the operating system get a hint."""
    if getattr(e, 'errno', None) is None:
        return jsonify({'error': str(e)}), 403
    app.logger.error("Write blocked: %s", e)
    return jsonify({'error': f"{e}. {WINDOWS_WRITE_HINT}"}), 500


@app.errorhandler(Exception)
def handle_error(e):
    """Return errors as JSON so the web page can show them."""
    if isinstance(e, HTTPException):
        return jsonify({'error': e.description}), e.code
    app.logger.exception("Unhandled error")
    return jsonify({'error': str(e)}), 500


@app.route('/')
def index():
    """Serve the web interface"""
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat requests (non-streaming)"""
    user_input = str(json_body().get('message', '')).strip()
    if not user_input:
        return jsonify({'error': 'Empty message'}), 400

    response = generate_answer(user_input)
    record_exchange(user_input, response)

    has_code, code = find_runnable_code(response)
    files = find_file_saves(response, user_input)
    log_exchange(user_input, response, files)
    return jsonify({'response': response, 'has_code': has_code, 'code': code, 'files': files})


@app.route('/api/chat-stream', methods=['POST'])
def chat_stream():
    """Handle chat requests with streaming response"""
    user_input = str(json_body().get('message', '')).strip()
    if not user_input:
        return jsonify({'error': 'Empty message'}), 400

    prompt = build_prompt(user_input)

    def generate():
        """Stream the response tokens, then a final 'done' event"""
        response_text = ""
        error = None
        try:
            for kind, value in stream_answer(user_input, prompt):
                if kind == 'search':
                    yield f"data: {json.dumps({'searching': value})}\n\n"
                    continue
                if kind == 'thinking':
                    yield f"data: {json.dumps({'thinking': True})}\n\n"
                    continue
                response_text += value
                yield f"data: {json.dumps({'token': value})}\n\n"
            record_exchange(user_input, response_text)
        except Exception as e:
            if not isinstance(e, LLMError):
                app.logger.exception("Streaming failed")
            error = str(e)

        has_code, code = (False, None) if error else find_runnable_code(response_text)
        files = [] if error else find_file_saves(response_text, user_input)
        log_exchange(user_input, response_text, files, error)
        done = {
            'done': True,
            'has_code': has_code,
            'code': code,
            'has_upgrade': "UPGRADE_REQUEST:" in response_text,
            'files': files,
            'error': error,
        }
        yield f"data: {json.dumps(done)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@app.route('/api/models', methods=['GET'])
def list_models():
    """Current model, downloaded models, models in memory, suggestions and download progress"""
    return jsonify({'success': True, **model_manager.status()})


@app.route('/api/models/select', methods=['POST'])
def select_model():
    """Switch model; downloads it first if needed and unloads the previous one"""
    try:
        result = model_manager.select(json_body().get('model', ''))
    except ValueError as e:
        log.warning("Model change refused: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, **result, 'current': llm_interface.model_name})


@app.route('/api/execute-code', methods=['POST'])
def execute_code():
    """Run code the user approved in the browser"""
    if not ENABLE_CODE_EXECUTION:
        return jsonify({'success': False, 'error': 'Code execution is disabled (ENABLE_CODE_EXECUTION)'}), 403

    code = str(json_body().get('code', '')).strip()
    if not code:
        return jsonify({'error': 'No code provided'}), 400

    success, output = code_executor.execute_code(code)
    learner.log_code_execution(success)
    log.info("Ran code: %s", "worked" if success else f"failed: {_short(output, 300)}")
    return jsonify({'success': success, 'output': output})


@app.route('/api/search', methods=['POST'])
def search():
    """Search the web"""
    query = str(json_body().get('query', '')).strip()
    if not query:
        return jsonify({'error': 'No search query'}), 400

    learner.log_web_search()
    return jsonify({'success': True, 'results': web_searcher.search(query)})


@app.route('/api/weather', methods=['POST'])
def get_weather():
    """Get weather for a specific location"""
    data = json_body()
    location = str(data.get('location', '')).strip()
    forecast_type = data.get('type', 'current')  # 'current' or 'tomorrow'

    if not location:
        return jsonify({'error': 'No location provided'}), 400

    if forecast_type == 'tomorrow':
        result = weather_provider.get_weather_for_tomorrow(location)
    else:
        result = weather_provider.get_weather(location)

    return jsonify({'success': True, 'location': location, 'weather': result, 'type': forecast_type})


@app.route('/api/history', methods=['GET'])
def get_history():
    """Get conversation history"""
    messages = conversation_history.get_all_messages(limit=request.args.get('limit', type=int))
    for message in messages:
        message['role'] = message['role'].lower()
    return jsonify({'success': True, 'messages': messages})


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get AI statistics"""
    total = conversation_history.count_messages()
    return jsonify({
        'success': True,
        'message_count': total,
        'conversations': total // 2,
        'files': len(file_handler.list_all_files()),
        'code_runs': learner.metrics.get('code_executions', 0),
    })


@app.route('/api/conversations', methods=['GET'])
def list_conversations():
    """List all saved conversations"""
    return jsonify({'sessions': conversation_manager.get_all_sessions()})


@app.route('/api/conversations/new', methods=['POST'])
def new_conversation():
    """Start a fresh conversation: earlier messages stop being sent to the model"""
    conversation_history.start_new_conversation()
    return jsonify({'success': True})


@app.route('/api/conversations', methods=['POST'])
def create_conversation():
    """Create a new conversation session"""
    data = json_body()
    name = str(data.get('name', '')).strip() or 'Untitled Conversation'
    tags = str(data.get('tags', '')).strip()

    session_id = conversation_manager.create_session(name, tags)
    return jsonify({'success': True, 'session_id': session_id, 'message': f'Conversation created: {name}'})


@app.route('/api/conversations/<int:session_id>', methods=['PUT'])
def update_conversation(session_id):
    """Rename a conversation"""
    new_name = str(json_body().get('name', '')).strip()
    if not new_name:
        return jsonify({'error': 'Name required'}), 400

    success = conversation_manager.update_session_name(session_id, new_name)
    return jsonify({'success': success,
                    'message': 'Conversation updated' if success else 'Conversation not found'})


@app.route('/api/conversations/<int:session_id>', methods=['DELETE'])
def delete_conversation(session_id):
    """Delete a conversation"""
    success = conversation_manager.delete_session(session_id)
    return jsonify({'success': success,
                    'message': 'Conversation deleted' if success else 'Conversation not found'})


@app.route('/api/knowledge-base/upload', methods=['POST'])
def upload_document():
    """Upload a document to knowledge base"""
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    filename = secure_filename(file.filename)
    if not filename:
        return jsonify({'error': 'Invalid file name'}), 400

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        file_path = Path(temp_dir) / filename
        file.save(str(file_path))
        success, message = knowledge_base.add_document(file_path)

    return jsonify({'success': success, 'message': message})


@app.route('/api/knowledge-base/list', methods=['GET'])
def list_documents():
    """List all documents in knowledge base"""
    docs = knowledge_base.list_documents()
    return jsonify({'documents': docs, 'count': len(docs)})


@app.route('/api/knowledge-base/delete/<document_name>', methods=['DELETE'])
def delete_document(document_name):
    """Delete a document from knowledge base"""
    success, message = knowledge_base.delete_document(document_name)
    return jsonify({'success': success, 'message': message})


@app.route('/api/knowledge-base/search', methods=['POST'])
def search_documents():
    """Search documents"""
    query = str(json_body().get('query', '')).strip()
    if not query:
        return jsonify({'error': 'No query provided'}), 400

    learner.log_knowledge_base_query()
    results = knowledge_base.search(query, top_k=5)
    return jsonify({'results': results, 'count': len(results)})


@app.route('/api/upgrade/request', methods=['POST'])
def request_upgrade():
    """AI requests upgrade - user must approve"""
    data = json_body()
    upgrade_description = data.get('description', '')
    file_to_upgrade = data.get('file', '')
    new_code = data.get('code', '')

    if not all([upgrade_description, file_to_upgrade, new_code]):
        return jsonify({'error': 'Missing required fields'}), 400

    return jsonify({
        'type': 'upgrade_request',
        'file': file_to_upgrade,
        'description': upgrade_description,
        'code': new_code,
        'requires_approval': True
    })


@app.route('/api/upgrade/apply', methods=['POST'])
def apply_upgrade():
    """Apply an upgrade the user approved"""
    if not ENABLE_SELF_IMPROVEMENT:
        return jsonify({'success': False, 'message': 'Self-improvement is disabled (ENABLE_SELF_IMPROVEMENT)'}), 403

    data = json_body()
    file_name = str(data.get('file', '')).strip()
    new_code = str(data.get('code', ''))
    description = str(data.get('description', ''))

    if not file_name or not new_code.strip():
        return jsonify({'error': 'Missing file or code'}), 400

    success, message = upgrade_manager.apply_upgrade(file_name, new_code, description)
    return jsonify({'success': success, 'message': message, 'requires_restart': success})


@app.route('/api/upgrade/history', methods=['GET'])
def upgrade_history():
    """Get upgrade history"""
    return jsonify({'history': upgrade_manager.get_upgrade_history()})


@app.route('/api/upgrade/backups', methods=['GET'])
def list_backups():
    """List available backups"""
    return jsonify({'backups': upgrade_manager.list_backups()})


@app.route('/api/upgrade/rollback', methods=['POST'])
def rollback():
    """Restore a file from a backup (pass the name from /api/upgrade/backups)"""
    backup_name = str(json_body().get('backup_path', '')).strip()
    if not backup_name:
        return jsonify({'error': 'Backup name required'}), 400

    success, message = upgrade_manager.rollback(backup_name)
    return jsonify({'success': success, 'message': message})


@app.route('/api/upgrade/get-code', methods=['GET'])
def get_file_code():
    """Get current code from an upgradeable file"""
    file_name = request.args.get('file', '')
    if not file_name:
        return jsonify({'error': 'File path required'}), 400

    success, code = upgrade_manager.get_file_code(file_name)
    return jsonify({'success': success, 'code': code if success else '', 'error': '' if success else code})


@app.route('/api/system/restart', methods=['POST'])
def restart_system():
    """Request system restart (manual restart needed)"""
    return jsonify({
        'message': 'Server restart required. Please restart manually: python web_server.py',
        'restart_required': True
    })


@app.route('/api/upgrade/available-files', methods=['GET'])
def available_files():
    """List files that can be upgraded"""
    return jsonify({'files': UPGRADEABLE_FILES})


@app.route('/api/folders/upload', methods=['POST'])
def upload_folder():
    """Upload a folder as ZIP file"""
    zip_file = request.files.get('folder')
    if not zip_file or not zip_file.filename:
        return jsonify({'error': 'No folder provided'}), 400
    if not zip_file.filename.lower().endswith('.zip'):
        return jsonify({'error': 'Please upload a ZIP file'}), 400

    folder_name = secure_filename(request.form.get('folder_name', '')) or 'uploaded_folder'

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        zip_path = Path(temp_dir) / "upload.zip"
        zip_file.save(str(zip_path))
        extract_path = Path(temp_dir) / folder_name

        try:
            with zipfile.ZipFile(zip_path) as archive:
                members = archive.infolist()
                if len(members) > MAX_ZIP_FILES:
                    return jsonify({'error': f'ZIP has more than {MAX_ZIP_FILES} files'}), 400
                if sum(m.file_size for m in members) > MAX_ZIP_UNCOMPRESSED:
                    return jsonify({'error': 'ZIP is too large when extracted'}), 400
                # extractall drops absolute paths and '..' parts, so files stay inside extract_path
                archive.extractall(extract_path)
        except zipfile.BadZipFile:
            return jsonify({'error': 'Not a valid ZIP file'}), 400

        success, message = folder_manager.add_folder(extract_path, folder_name)

    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'success': False, 'error': message}), 400


@app.route('/api/folders/upload-files', methods=['POST'])
def upload_folder_files():
    """Upload a folder picked in the browser (no ZIP needed). Each file's name is its path in the folder."""
    uploads = request.files.getlist('files')
    if not uploads:
        return jsonify({'error': 'No files provided'}), 400

    first = uploads[0].filename.replace('\\', '/').split('/')
    folder_name = secure_filename(request.form.get('folder_name', '') or first[0]) or 'uploaded_folder'
    saved = 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir) / folder_name
        for upload in uploads:
            parts = upload.filename.replace('\\', '/').split('/')
            parts = parts[1:] if len(parts) > 1 else parts  # drop the folder's own name
            if SKIPPED_UPLOAD_PARTS & set(parts):
                continue
            safe_parts = [secure_filename(p) for p in parts]
            if not all(safe_parts):
                continue
            target = root.joinpath(*safe_parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            upload.save(str(target))
            saved += 1
        if not saved:
            return jsonify({'error': 'No usable files in that folder'}), 400
        success, message = folder_manager.add_folder(root, folder_name)

    if success:
        return jsonify({'success': True, 'message': message, 'folder': folder_name, 'files': saved})
    return jsonify({'success': False, 'error': message}), 400


# ---------------- files the AI saves for the user (ai_files folder)

@app.route('/api/files', methods=['GET'])
def list_saved_files():
    """Files in the user's ai_files folder"""
    return jsonify({'success': True, 'files': file_handler.list_all_files()})


@app.route('/api/files/save', methods=['POST'])
def save_file():
    """Save a file the AI proposed (the user clicked Save)"""
    data = json_body()
    content = data.get('content')
    if not isinstance(content, str):
        return jsonify({'error': 'No file content provided'}), 400
    if len(content) > MAX_SAVED_FILE_CHARS:
        return jsonify({'error': 'File is too large'}), 400
    try:
        path = file_handler.clean_relative_path(data.get('path', ''))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    file_handler.write_file(path, content)
    learner.log_file_operation('save', True)
    log.info("Saved file %s (%d characters)", path, len(content))
    return jsonify({'success': True, 'path': path,
                    'message': f"✅ Saved {path} (on your PC: {file_handler.allowed_directory / path})"})


def system_summary():
    """Versions and settings for the top of the 🐞 logs report."""
    try:
        with tempfile.NamedTemporaryFile(dir=AI_FILES_PATH):
            writable = "yes"
    except OSError as e:
        writable = f"NO ({e})"
    ollama = "running" if llm_interface.test_connection() else f"NOT reachable at {OLLAMA_URL}"
    saved = [f['path'] for f in file_handler.list_all_files()]
    return [f"System: {platform.platform()}, Python {platform.python_version()}",
            f"App files dated: {datetime.fromtimestamp(Path(__file__).stat().st_mtime):%Y-%m-%d %H:%M}",
            f"Model: {llm_interface.model_name} (Ollama {ollama})",
            f"Saved files folder: {AI_FILES_PATH} (can write: {writable})",
            f"Saved files: {', '.join(saved[:30]) or 'none'}"]


@app.route('/api/logs', methods=['GET'])
def get_logs():
    """The last few minutes of the app's log with versions, for the 🐞 button."""
    minutes = min(max(request.args.get('minutes', 5, type=int), 1), 60)
    report = [f"AI Assistant logs: the last {minutes} minutes (made {datetime.now():%Y-%m-%d %H:%M:%S})",
              *system_summary(), "", "--- App log ---",
              *(recent_lines(LOGS_PATH, minutes) or ["(nothing logged)"])]
    return jsonify({'report': "\n".join(report)})


@app.route('/api/files/download', methods=['GET'])
def download_file():
    """Download one of the user's saved files"""
    try:
        path = file_handler._resolve(file_handler.clean_relative_path(request.args.get('path', '')))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if not path.is_file():
        return jsonify({'error': 'File not found'}), 404
    return send_file(path, as_attachment=True, download_name=path.name)


@app.route('/api/files', methods=['DELETE'])
def delete_saved_file():
    """Delete one of the user's saved files"""
    try:
        path = file_handler.clean_relative_path(request.args.get('path', ''))
        file_handler.delete_file(path)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404
    return jsonify({'success': True, 'message': f"Deleted {path}"})


@app.route('/api/folders/list', methods=['GET'])
def list_folders():
    """List all uploaded folders"""
    folder_list = [{
        'name': name,
        'file_count': info.get('file_count', 0),
        'size': info.get('size', 0),
        'uploaded_at': info.get('uploaded_at', '')
    } for name, info in folder_manager.list_all_folders().items()]
    return jsonify({'success': True, 'folders': folder_list})


@app.route('/api/folders/<folder_name>/contents', methods=['GET'])
def get_folder_contents(folder_name):
    """Get contents of a folder"""
    files, error = folder_manager.get_folder_contents(folder_name)
    if error:
        return jsonify({'error': error}), 404
    return jsonify({'success': True, 'files': files})


@app.route('/api/folders/<folder_name>/file', methods=['POST'])
def read_folder_file(folder_name):
    """Read a specific file from a folder"""
    file_path = json_body().get('file_path')
    if not file_path:
        return jsonify({'error': 'No file path provided'}), 400

    content, error = folder_manager.read_file(folder_name, file_path)
    if error:
        return jsonify({'error': error}), 404
    return jsonify({'success': True, 'content': content})


@app.route('/api/folders/<folder_name>/summary', methods=['GET'])
def get_folder_summary(folder_name):
    """Get a summary of folder contents"""
    summary = folder_manager.get_folder_summary(folder_name)
    return jsonify({'success': True, 'summary': summary, 'folder_name': folder_name})


@app.route('/api/folders/<folder_name>/delete', methods=['DELETE'])
def delete_folder(folder_name):
    """Delete an uploaded folder"""
    success, message = folder_manager.delete_folder(folder_name)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'success': False, 'error': message}), 400


@app.route('/api/chat/with-folder', methods=['POST'])
def chat_with_folder():
    """Chat with AI while giving it access to a folder"""
    data = json_body()
    message = str(data.get('message', '')).strip()
    folder_name = data.get('folder_name')

    if not message:
        return jsonify({'error': 'Empty message'}), 400
    if not folder_name:
        return jsonify({'error': 'No folder specified'}), 400

    folder_text, error = folder_manager.get_folder_context(folder_name)
    if error:
        return jsonify({'error': error}), 404

    folder_context = f"""📁 FOLDER ACCESS:
The user has shared a folder with you: {folder_name}

{folder_text}

Answer based on the folder contents: discuss them, suggest improvements,
or write code that works with these files."""

    response = generate_answer(message, folder_context)
    record_exchange(message, response)
    learner.log_feature_usage('folder_chat')

    has_code, code = find_runnable_code(response)
    files = find_file_saves(response, message)
    log_exchange(message, response, files)
    return jsonify({'response': response, 'folder': folder_name, 'has_code': has_code, 'code': code,
                    'files': files})


# ==================== SELF-IMPROVEMENT ENDPOINTS ====================

@app.route('/api/self/analyze', methods=['GET'])
def self_analyze():
    """Analyze own code quality"""
    analyses = analyzer.analyze_all_files()
    return jsonify({
        'success': True,
        'report': analyzer.format_analysis_report(analyses),
        'quality_score': analyzer.get_code_quality_score(analyses)
    })


@app.route('/api/self/learning', methods=['GET'])
def self_learning():
    """Get AI learning statistics"""
    return jsonify({
        'success': True,
        'insights': learner.get_learning_insights(),
        'report': learner.format_learning_report()
    })


@app.route('/api/self/improvements', methods=['GET'])
def get_improvements():
    """Get proposed improvements"""
    proposals = improver.analyze_and_propose()
    return jsonify({
        'success': True,
        'proposals': proposals,
        'suggestions_text': improver.format_improvement_suggestions(proposals),
        'count': len(proposals)
    })


def pick_improvement_target(analyses):
    """The upgradeable file with the most issues that is small enough to show the model in full."""
    candidates = []
    for name in UPGRADEABLE_FILES:
        analysis = analyses.get(name)
        if not isinstance(analysis, dict) or 'issues' not in analysis:
            continue
        path = upgrade_manager.project_dir / name
        size = path.stat().st_size if path.exists() else 0
        if 0 < size <= MAX_CODE_CONTEXT_CHARS and analysis['issues']:
            candidates.append((len(analysis['issues']), name))
    return max(candidates)[1] if candidates else None


@app.route('/api/self/improvement-prompt', methods=['GET'])
def get_improvement_prompt():
    """Get a prompt to trigger AI self-improvement.

    It names ONE file, so the chat adds that file's current code (see get_code_context)
    and the model edits the real code instead of rewriting it from memory.
    """
    analyses = analyzer.analyze_all_files()
    proposals = improver.analyze_and_propose(analyses)
    target = pick_improvement_target(analyses)

    past = upgrade_manager.get_upgrade_history()[-5:]
    past_text = "\n".join(f"- {Path(u['file']).name}: {u.get('description') or 'no description'}"
                          for u in past) or "- none yet"

    score = analyzer.get_code_quality_score(analyses)
    if target:
        issues = "\n".join(f"- {issue}" for issue in analyses[target]['issues'][:10])
        # The target is named first so the chat attaches ITS code (see get_code_context)
        prompt = f"""Improve {target}. Its current code is shown above. Issues found in it:
{issues}

Overall code quality score: {score}/100

Upgrades already applied:
{past_text}

Propose ONE UPGRADE_REQUEST for {target} that fixes these issues. Start from its current
code, keep every existing class, function and setting, and don't repeat earlier upgrades."""
    else:
        prompt = f"""Overall code quality score: {score}/100. No upgradeable file has issues right now.

{improver.format_improvement_suggestions(proposals)}
Upgrades already applied:
{past_text}

Suggest improvements in words; don't send an UPGRADE_REQUEST."""

    return jsonify({
        'success': True,
        'prompt': prompt,
        'target_file': target,
        'analysis': improver.create_improvement_file(analyses)
    })


@app.route('/api/feedback', methods=['POST'])
def log_feedback():
    """Log user feedback for learning"""
    data = json_body()
    try:
        rating = min(5, max(1, int(data.get('rating', 3))))
    except (TypeError, ValueError):
        return jsonify({'error': 'Rating must be a number from 1 to 5'}), 400

    recent = conversation_history.get_all_messages(limit=2)
    last_answer = next((m['content'] for m in reversed(recent) if m['role'] == 'Assistant'), '')
    learner.log_feedback(conversation_history.count_messages(), rating, str(data.get('feedback', '')), last_answer)
    return jsonify({'success': True, 'message': 'Feedback logged for improvement'})


if __name__ == '__main__':
    print("Starting Personal AI Web Interface...")
    llm_interface.test_connection()
    print(f"Open your browser and go to: http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=DEBUG)
