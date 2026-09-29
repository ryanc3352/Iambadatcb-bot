import json
import re
import tempfile
import zipfile
from pathlib import Path

from flask import Flask, render_template, request, jsonify, Response
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

# config loads the .env file, so import it before anything that reads settings
from config import (
    BASE_DIR, DATABASE_PATH, VECTOR_DB_PATH, AI_FILES_PATH, BACKUPS_PATH,
    OLLAMA_URL, MODEL_NAME, MODEL_TEMPERATURE, MODEL_MAX_TOKENS,
    CONTEXT_MESSAGES, SEARCH_TOP_K, SYSTEM_PROMPT,
    ENABLE_CODE_EXECUTION, CODE_EXECUTION_TIMEOUT, ENABLE_SELF_IMPROVEMENT, LEARNING_ENABLED,
    HOST, PORT, DEBUG, MAX_UPLOAD_MB, UPGRADEABLE_FILES,
)
from llm_interface import LLMInterface
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

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

# Limits for uploaded ZIP folders (protects against zip bombs)
MAX_ZIP_FILES = 5000
MAX_ZIP_UNCOMPRESSED = 500 * 1024 * 1024

conversation_history = ConversationHistory(DATABASE_PATH)
llm_interface = LLMInterface(MODEL_NAME, MODEL_TEMPERATURE, MODEL_MAX_TOKENS, OLLAMA_URL)
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
learner = LearningSystem(BACKUPS_PATH)
improver = AutonomousImprover(analyzer, learner, BACKUPS_PATH)

WEATHER_KEYWORDS = ['weather', 'forecast', 'temperature', 'rain', 'snow', 'sunny', 'cloudy',
                    'celsius', 'fahrenheit', 'degrees', 'wind']
SEARCH_KEYWORDS = ['news', 'latest', 'current', 'breaking', 'recent', 'price', 'stock', 'time in']
TIME_WORDS = r'(?:today|tomorrow|tonight|right now|now|this weekend|this week|morning|afternoon|evening|night)'


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
        return match.group(1).strip(" ,.")

    # Fallback: the first capitalized word after a weather keyword ("Tokyo weather" is not handled)
    words = user_input.split()
    for i, word in enumerate(words):
        if word.lower().strip('.,!?') in WEATHER_KEYWORDS:
            for j in range(i + 1, len(words)):
                if words[j][:1].isupper():
                    location = ' '.join(words[j:]).rstrip('.,!?')
                    return re.sub(rf'\s+\b{TIME_WORDS}\b.*$', '', location, flags=re.IGNORECASE).strip()
    return None


def get_live_context(user_input):
    """Fetch weather or web search results when the question needs live data."""
    text = user_input.lower()
    try:
        if _contains_word(text, WEATHER_KEYWORDS):
            location = extract_location(user_input)
            if not location:
                return "(No location found in the weather question - ask the user which place they mean.)"
            learner.log_feature_usage('weather')
            if 'tomorrow' in text:
                return weather_provider.get_weather_for_tomorrow(location)
            return weather_provider.get_weather(location)

        if any(keyword in text for keyword in SEARCH_KEYWORDS):
            learner.log_web_search()
            return web_searcher.search(user_input, num_results=5)
    except Exception as e:
        return f"(Search error: {e})"
    return ""


def build_prompt(user_input, extra_context=""):
    """Build prompt with context from memory, documents, conversation history, weather, and web search.

    Call this before saving the new message, so it isn't repeated in 'Recent conversation'.
    """
    live_context = get_live_context(user_input)
    recent_messages = conversation_history.get_last_n_messages(CONTEXT_MESSAGES)
    formatted_history = conversation_history.format_for_prompt(recent_messages)
    similar_context = memory.get_context_from_search(user_input, SEARCH_TOP_K)
    doc_context = knowledge_base.get_context_from_documents(user_input, top_k=3)
    if doc_context:
        learner.log_knowledge_base_query()

    sections = [SYSTEM_PROMPT, extra_context, live_context, doc_context, similar_context,
                f"Recent conversation:\n{formatted_history}" if formatted_history else ""]
    context = "\n\n".join(s.strip() for s in sections if s and s.strip())
    return f"{context}\n\nUser: {user_input}\nAssistant:"


def record_exchange(user_input, response):
    """Save a user/assistant exchange to history, vector memory and learning logs."""
    conversation_history.add_message("User", user_input)
    message_id = conversation_history.add_message("Assistant", response)
    if message_id is not None:
        memory.add_conversation(user_input, response, message_id)
    if LEARNING_ENABLED:
        learner.log_conversation(user_input, response)


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

    prompt = build_prompt(user_input)
    response = llm_interface.generate_response(prompt)
    record_exchange(user_input, response)

    has_code, code = code_executor.extract_code(response)
    return jsonify({'response': response, 'has_code': has_code, 'code': code})


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
        try:
            for token in llm_interface.generate_response_stream(prompt):
                response_text += token
                yield f"data: {json.dumps({'token': token})}\n\n"
            record_exchange(user_input, response_text)
        except Exception as e:
            app.logger.exception("Streaming failed")
            error_token = {'token': f"\n[Error: {e}]"}
            yield f"data: {json.dumps(error_token)}\n\n"

        has_code, code = code_executor.extract_code(response_text)
        done = {
            'done': True,
            'has_code': has_code,
            'code': code,
            'has_upgrade': "UPGRADE_REQUEST:" in response_text,
        }
        yield f"data: {json.dumps(done)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


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
    messages = conversation_history.get_all_messages()
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
        'files': len(file_handler.list_files()),
    })


@app.route('/api/conversations', methods=['GET'])
def list_conversations():
    """List all saved conversations"""
    return jsonify({'sessions': conversation_manager.get_all_sessions()})


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

    with tempfile.TemporaryDirectory() as temp_dir:
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

    with tempfile.TemporaryDirectory() as temp_dir:
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

    folder_context = f"""📁 FOLDER ACCESS:
The user has shared a folder with you: {folder_name}

{folder_manager.get_folder_summary(folder_name)}

Answer based on the folder contents: discuss them, suggest improvements,
or write code that works with these files."""

    response = llm_interface.generate_response(build_prompt(message, folder_context))
    record_exchange(message, response)
    learner.log_feature_usage('folder_chat')

    return jsonify({'response': response, 'folder': folder_name})


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


@app.route('/api/self/improvement-prompt', methods=['GET'])
def get_improvement_prompt():
    """Get a prompt to trigger AI self-improvement"""
    analyses = analyzer.analyze_all_files()
    proposals = improver.analyze_and_propose(analyses)
    prompt = f"""I want you to improve yourself. Here's my analysis:

Code Quality Score: {analyzer.get_code_quality_score(analyses)}/100

{improver.format_improvement_suggestions(proposals)}

Based on this analysis, what improvements would you suggest?
Look at:
1. Code quality issues
2. Features that are heavily used
3. User feedback areas
4. New features to add

Propose ONE specific UPGRADE_REQUEST block for the highest-priority improvement.
Upgradeable files: {', '.join(UPGRADEABLE_FILES)}"""

    return jsonify({
        'success': True,
        'prompt': prompt,
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

    last_message_id = conversation_history.count_messages()
    learner.log_feedback(last_message_id, rating, str(data.get('feedback', '')))
    return jsonify({'success': True, 'message': 'Feedback logged for improvement'})


if __name__ == '__main__':
    print("Starting Personal AI Web Interface...")
    llm_interface.test_connection()
    print(f"Open your browser and go to: http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=DEBUG)
