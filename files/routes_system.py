"""Models (switching and downloading) and the 🐞 logs report."""
import platform
import tempfile
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from app_logging import recent_lines
from config import AI_FILES_PATH, LOGS_PATH, OLLAMA_URL
from routes_common import json_body
from services import file_handler, llm_interface, log, model_manager

bp = Blueprint('system', __name__)


@bp.route('/api/models', methods=['GET'])
def list_models():
    """Current model, downloaded models, models in memory, suggestions and download progress"""
    return jsonify({'success': True, **model_manager.status()})


@bp.route('/api/models/select', methods=['POST'])
def select_model():
    """Switch model; downloads it first if needed and unloads the previous one"""
    try:
        result = model_manager.select(json_body().get('model', ''))
    except ValueError as e:
        log.warning("Model change refused: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, **result, 'current': llm_interface.model_name})


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
            f"App files dated: {datetime.fromtimestamp(max(p.stat().st_mtime for p in Path(__file__).parent.glob('*.py'))):%Y-%m-%d %H:%M}",
            f"Model: {llm_interface.model_name} (Ollama {ollama})",
            f"Saved files folder: {AI_FILES_PATH} (can write: {writable})",
            f"Saved files: {', '.join(saved[:30]) or 'none'}"]


@bp.route('/api/logs', methods=['GET'])
def get_logs():
    """The last few minutes of the app's log with versions, for the 🐞 button."""
    minutes = min(max(request.args.get('minutes', 5, type=int), 1), 60)
    report = [f"AI Assistant logs: the last {minutes} minutes (made {datetime.now():%Y-%m-%d %H:%M:%S})",
              *system_summary(), "", "--- App log ---",
              *(recent_lines(LOGS_PATH, minutes) or ["(nothing logged)"])]
    return jsonify({'report': "\n".join(report)})
