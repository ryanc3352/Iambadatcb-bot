"""The prompt: the system prompt plus memory, documents, live data, files and the recent chat."""
import re
from datetime import datetime
from pathlib import Path

from calculator import math_context
from config import CONTEXT_MESSAGES, SEARCH_TOP_K, SYSTEM_PROMPT, UPGRADEABLE_FILES
from file_offers import FILE_REQUEST_NOTE, wants_file
from services import (conversation_history, file_handler, github_reader, knowledge_base, learner, memory,
                      upgrade_manager, weather_provider, web_searcher)


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


def code_length(path):
    """How many characters of a file the model sees: \\r\\n (Windows checkouts) counts as one."""
    return len(path.read_text(encoding='utf-8', errors='replace'))

FILE_WORDS = ['file', 'files', 'save', 'saved', 'note', 'notes', 'list', 'document', 'create', 'add',
              'folder', 'folders', 'directory', 'ai_files']


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
    recent_messages = conversation_history.get_last_n_messages(CONTEXT_MESSAGES)
    # a follow-up about a GitHub link in the previous message still gets what the link points to
    previous = next((m["content"] for m in reversed(recent_messages) if m["role"] == "User"), "")
    github_context = github_reader.context_for(user_input, previous)
    code_context = get_code_context(user_input)
    formatted_history = conversation_history.format_for_prompt(recent_messages)
    file_context = get_file_context(user_input, formatted_history)
    feedback = learner.get_feedback_guidance()

    now = datetime.now().strftime("%A %d %B %Y, %H:%M")
    sections = [SYSTEM_PROMPT, f"Current date and time: {now}", feedback, extra_context, code_context, file_context,
                live_context, github_context, calculator_context, doc_context, similar_context,
                f"Recent conversation:\n{formatted_history}" if formatted_history else "",
                FILE_REQUEST_NOTE if wants_file(user_input) else ""]  # last, so small models don't miss it
    context = "\n\n".join(s.strip() for s in sections if s and s.strip())
    return f"{context}\n\nUser: {user_input}\nAssistant:"
