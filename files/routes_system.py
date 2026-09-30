"""Models (switching and downloading), the 🐞 logs report and the ⬆️ Update button."""
import os
import platform
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

import updater
from app_logging import recent_lines
from config import AI_FILES_PATH, BACKUPS_PATH, BASE_DIR, LOGS_PATH, OLLAMA_URL, RESTART_EXIT_CODE, UPDATE_URL
from llm_interface import LLMError
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


def placement_text(model):
    """Where a loaded model runs: all on the graphics card is fast, any on the processor is slower."""
    size, on_card = model['size'], model['size_vram']
    share = round(100 * on_card / size) if size else 0
    if share >= 100:
        where = "graphics card (100%)"
    elif share == 0:
        where = "processor only, NOT the graphics card (slow: is the NVIDIA driver up to date?)"
    else:
        where = f"{share}% on the graphics card, the rest on the processor (slower: too big for the card?)"
    return f"{model['name']} on {where}, {size / 1e9:.1f} GB"


def model_memory_line():
    try:
        loaded = llm_interface.loaded_models()
    except LLMError:
        return "Model running on: unknown (Ollama didn't answer)"
    if not loaded:
        return "Model running on: nothing loaded right now (the model loads with the next question)"
    return "Model running on: " + "; ".join(placement_text(model) for model in loaded)


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
            model_memory_line(),
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


def can_restart():
    """True when start.py runs the app, so it starts again after exiting."""
    return os.getenv("AI_ASSISTANT_LAUNCHER") == "start.py"


def restart_soon():
    """Exit after the answer has been sent; start.py installs new libraries and starts the app again."""
    threading.Timer(1.5, os._exit, args=(RESTART_EXIT_CODE,)).start()


@bp.route('/api/update', methods=['POST'])
def update_app():
    """The ⬆️ Update button: install the newest version from GitHub, then restart."""
    if not json_body().get('confirm'):  # JSON only, so other websites can't press the button
        return jsonify({'success': False, 'error': 'Send {"confirm": true} to update'}), 400
    try:
        result = updater.update(UPDATE_URL, BASE_DIR, BACKUPS_PATH)
    except updater.UpdateError as e:
        log.warning("Update failed: %s", e)
        return jsonify({'success': False, 'error': str(e)})
    changed = result['changed']
    log.info("Updated %d files: %s (old files in %s)", len(changed), ", ".join(changed[:50]), result['backup'])
    restarting = bool(changed) and can_restart()
    if restarting:
        restart_soon()
    return jsonify({'success': True, 'changed': changed, 'restarting': restarting})
