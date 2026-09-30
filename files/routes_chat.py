"""Chat: answers (streamed, or about a project folder), running approved code, history, stats, feedback."""
import json
import queue
import threading
import uuid

from flask import Blueprint, Response, jsonify, request

from answers import NO_CARDS, answer_cards, generate_answer, log_exchange, record_exchange, shorten, stream_answer
from config import ENABLE_CODE_EXECUTION
from llm_interface import LLMError
from prompts import build_prompt
from routes_common import json_body
from services import code_executor, conversation_history, file_handler, folder_manager, learner, log, memory

bp = Blueprint('chat', __name__)


@bp.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat requests (non-streaming)"""
    user_input = str(json_body().get('message', '')).strip()
    if not user_input:
        return jsonify({'error': 'Empty message'}), 400

    response = generate_answer(user_input)
    record_exchange(user_input, response)

    cards = answer_cards(user_input, response)
    log_exchange(user_input, response, cards['files'])
    return jsonify({'response': response, **cards})


@bp.route('/api/chat-stream', methods=['POST'])
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
                log.exception("Streaming failed")
            error = str(e)

        cards = NO_CARDS if error else answer_cards(user_input, response_text)
        log_exchange(user_input, response_text, cards['files'], error)
        done = {
            'done': True,
            **cards,
            'has_upgrade': "UPGRADE_REQUEST:" in response_text,
            'error': error,
        }
        yield f"data: {json.dumps(done)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@bp.route('/api/chat/with-folder', methods=['POST'])
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

    cards = answer_cards(message, response)
    log_exchange(message, response, cards['files'])
    return jsonify({'response': response, 'folder': folder_name, **cards})


@bp.route('/api/execute-code', methods=['POST'])
def execute_code():
    """Run code the user approved in the browser, streaming its output.

    Events: {'run_id'} first (for the Stop button), {'output': line} while it runs,
    then {'done', 'success', 'output'}. There's no time limit, so the code can run for hours.
    """
    if not ENABLE_CODE_EXECUTION:
        return jsonify({'success': False, 'error': 'Code execution is disabled (ENABLE_CODE_EXECUTION)'}), 403

    data = json_body()
    code = str(data.get('code', '')).strip()
    if not code:
        return jsonify({'error': 'No code provided'}), 400
    packages = [p for p in data.get('packages') or [] if isinstance(p, str)][:20]
    stdin_text = str(data.get('input') or '')
    run_id = str(data.get('run_id') or '')[:64] or uuid.uuid4().hex

    updates = queue.Queue()

    def run():
        try:
            result = code_executor.execute_code(code, packages, stdin_text, run_id, on_output=updates.put)
        except Exception as e:
            log.exception("Running code failed")
            result = (False, f"Couldn't run the code: {e}")
        updates.put(result)  # a tuple marks the end

    threading.Thread(target=run, daemon=True).start()

    def generate():
        yield f"data: {json.dumps({'run_id': run_id})}\n\n"
        while True:
            try:
                item = updates.get(timeout=15)
            except queue.Empty:
                yield ": still running\n\n"  # keeps the browser from giving up on a long run
                continue
            if isinstance(item, tuple):
                break
            yield f"data: {json.dumps({'output': item})}\n\n"
        success, output = item
        learner.log_code_execution(success)
        log.info("Ran code: %s", "worked" if success else f"failed: {shorten(output, 300)}")
        yield f"data: {json.dumps({'done': True, 'success': success, 'output': output})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


@bp.route('/api/stop-code', methods=['POST'])
def stop_code():
    """The ⏹ Stop button: end a program started with /api/execute-code"""
    return jsonify({'success': code_executor.stop(str(json_body().get('run_id', '')))})


@bp.route('/api/history', methods=['GET'])
def get_history():
    """Get conversation history"""
    messages = conversation_history.get_all_messages(limit=request.args.get('limit', type=int))
    for message in messages:
        message['role'] = message['role'].lower()
    return jsonify({'success': True, 'messages': messages})


@bp.route('/api/stats', methods=['GET'])
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


@bp.route('/api/conversations/new', methods=['POST'])
def new_conversation():
    """Start a fresh conversation: earlier messages stop being sent to the model"""
    conversation_history.start_new_conversation()
    return jsonify({'success': True})


@bp.route('/api/conversations', methods=['GET'])
def list_conversations():
    """The past chats, most recently used first, and which one is open"""
    return jsonify({'success': True, 'current': conversation_history.current_conversation_id(),
                    'conversations': conversation_history.list_conversations()})


def chat_not_found():
    return jsonify({'success': False, 'error': 'That chat no longer exists'}), 404


@bp.route('/api/conversations/<int:chat_id>', methods=['GET'])
def get_conversation(chat_id):
    """A chat's messages"""
    chat = conversation_history.get_conversation(chat_id)
    if chat is None:
        return chat_not_found()
    for message in chat['messages']:
        message['role'] = message['role'].lower()
    return jsonify({'success': True, **chat})


@bp.route('/api/conversations/<int:chat_id>/open', methods=['POST'])
def open_conversation(chat_id):
    """Carry on an earlier chat: it becomes the one new messages go to"""
    if not conversation_history.open_conversation(chat_id):
        return chat_not_found()
    return get_conversation(chat_id)


@bp.route('/api/conversations/<int:chat_id>/rename', methods=['POST'])
def rename_conversation(chat_id):
    """Rename a chat (an empty name goes back to its first question)"""
    title = json_body().get('title')
    if not isinstance(title, str):
        return jsonify({'success': False, 'error': 'Give the chat a name'}), 400
    if not conversation_history.rename_conversation(chat_id, title):
        return chat_not_found()
    return jsonify({'success': True})


@bp.route('/api/conversations/<int:chat_id>', methods=['DELETE'])
def delete_conversation(chat_id):
    """Delete a chat; the AI's long-term memory forgets it too"""
    deleted = conversation_history.delete_conversation(chat_id)
    if deleted is None:
        return chat_not_found()
    memory.forget(deleted)
    log.info("Deleted chat %s (%d messages)", chat_id, len(deleted))
    return jsonify({'success': True, 'current': conversation_history.current_conversation_id()})


@bp.route('/api/feedback', methods=['POST'])
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
