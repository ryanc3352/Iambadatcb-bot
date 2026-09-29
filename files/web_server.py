"""The web app: the page, error handling, and the /api routes from the routes_*.py files.

Start it with "Start AI.bat" (or python start.py), which sets everything up first.
"""
from flask import Flask, jsonify, render_template
from werkzeug.exceptions import HTTPException

import routes_chat
import routes_files
import routes_improve
import routes_system
from config import DEBUG, HOST, MAX_UPLOAD_MB, PORT
from llm_interface import LLMError
from services import llm_interface, log

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024
for routes in (routes_chat, routes_files, routes_improve, routes_system):
    app.register_blueprint(routes.bp)


WINDOWS_WRITE_HINT = ("Windows may be blocking Python from writing in this folder (Controlled folder access, "
                      "OneDrive, or a read-only location). Move the project to a simple folder like C:\\AI "
                      "or set DATA_DIR in .env.")


@app.errorhandler(LLMError)
def handle_llm_error(e):
    """The model couldn't answer (Ollama not running, model missing, timeout)."""
    log.warning("Model error: %s", e)
    return jsonify({'error': str(e)}), 503


@app.errorhandler(PermissionError)
def handle_permission_error(e):
    """Our own path checks explain themselves; errors from the operating system get a hint."""
    if getattr(e, 'errno', None) is None:
        return jsonify({'error': str(e)}), 403
    log.error("Write blocked: %s", e)
    return jsonify({'error': f"{e}. {WINDOWS_WRITE_HINT}"}), 500


@app.errorhandler(Exception)
def handle_error(e):
    """Return errors as JSON so the web page can show them."""
    if isinstance(e, HTTPException):
        return jsonify({'error': e.description}), e.code
    log.exception("Unhandled error")
    return jsonify({'error': str(e)}), 500


@app.route('/')
def index():
    """Serve the web interface"""
    return render_template('index.html')


if __name__ == '__main__':
    print("Starting Personal AI Web Interface...")
    llm_interface.test_connection()
    print(f"Open your browser and go to: http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=DEBUG)
