"""The model's answer to a message (after a web search when it asks for one), and recording it."""
import re

from config import LEARNING_ENABLED
from file_offers import find_file_saves
from llm_interface import ThinkFilter
from prompts import build_prompt
from services import code_executor, conversation_history, learner, llm_interface, log, memory, web_searcher


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


def answer_cards(user_input, response):
    """What to show under an answer: code the user may run, and files to save.

    Content offered as a file isn't also offered to run ("milk, eggs" is a list, not Python).
    """
    files = find_file_saves(response, user_input)
    has_code, code = find_runnable_code(response)
    if code and any(f['content'].strip() == code.strip() for f in files):
        has_code, code = False, None
    return has_code, code, files


def find_runnable_code(response):
    """Code the user may run. Upgrades and files to save are not run, so they don't count."""
    if "UPGRADE_REQUEST:" in response or "SAVE_FILE:" in response:
        return False, None
    return code_executor.extract_code(response)


def shorten(text, limit):
    """One line of at most `limit` characters, for the log."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def log_exchange(user_input, response, files, error=None):
    """Log a question, its answer and the files offered (shortened), for the 🐞 logs button."""
    log.info("Question: %s", shorten(user_input, 300))
    if error:
        log.warning("Answer failed: %s", error)
    else:
        log.info("Answer from %s: %s", llm_interface.model_name, shorten(response, 800))
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
