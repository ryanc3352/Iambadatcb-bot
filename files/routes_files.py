"""The user's files: files the AI saved (ai_files), uploaded documents and project folders."""
import tempfile
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

from github_reader import GitHubError
from routes_common import json_body
from services import file_handler, folder_manager, github_reader, knowledge_base, learner, log

bp = Blueprint('files', __name__)


# Limits for uploaded ZIP folders (protects against zip bombs)
MAX_ZIP_FILES = 5000

MAX_ZIP_UNCOMPRESSED = 500 * 1024 * 1024

# Files the AI saves for the user
MAX_SAVED_FILE_CHARS = 1_000_000

# Folders picked in the browser: skip bulky tool folders
SKIPPED_UPLOAD_PARTS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.idea', '.vscode'}


@bp.route('/api/files', methods=['GET'])
def list_saved_files():
    """Files in the user's ai_files folder"""
    return jsonify({'success': True, 'files': file_handler.list_all_files()})


@bp.route('/api/files/save', methods=['POST'])
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


@bp.route('/api/files/download', methods=['GET'])
def download_file():
    """Download one of the user's saved files"""
    try:
        path = file_handler._resolve(file_handler.clean_relative_path(request.args.get('path', '')))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if not path.is_file():
        return jsonify({'error': 'File not found'}), 404
    return send_file(path, as_attachment=True, download_name=path.name)


@bp.route('/api/files', methods=['DELETE'])
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


@bp.route('/api/knowledge-base/upload', methods=['POST'])
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


@bp.route('/api/knowledge-base/list', methods=['GET'])
def list_documents():
    """List all documents in knowledge base"""
    docs = knowledge_base.list_documents()
    return jsonify({'documents': docs, 'count': len(docs)})


@bp.route('/api/knowledge-base/delete/<document_name>', methods=['DELETE'])
def delete_document(document_name):
    """Delete a document from knowledge base"""
    success, message = knowledge_base.delete_document(document_name)
    return jsonify({'success': success, 'message': message})


@bp.route('/api/folders/upload', methods=['POST'])
def upload_folder():
    """Upload a folder as ZIP file"""
    zip_file = request.files.get('folder')
    if not zip_file or not zip_file.filename:
        return jsonify({'error': 'No folder provided'}), 400
    if not zip_file.filename.lower().endswith('.zip'):
        return jsonify({'error': 'Please upload a ZIP file'}), 400

    folder_name = secure_filename(request.form.get('folder_name', '')) or 'uploaded_folder'
    return add_zip_folder(zip_file.save, folder_name)


@bp.route('/api/folders/github', methods=['POST'])
def add_github_folder():
    """🐙 Add from GitHub: download a repository and add it as a project folder"""
    links = github_reader.links(str(json_body().get('url', '')))
    if not links:
        return jsonify({'error': 'Paste a link like https://github.com/owner/repository'}), 400
    owner, repo = links[0][:2]
    try:
        data = github_reader.download_zip(owner, repo)
    except GitHubError as e:
        return jsonify({'success': False, 'error': f"Couldn't download {owner}/{repo}: {e}"}), 400
    learner.log_feature_usage('github_folder')
    return add_zip_folder(lambda path: Path(path).write_bytes(data), secure_filename(repo) or 'github_repo',
                          unwrap=True)


def add_zip_folder(save_zip, folder_name, unwrap=False):
    """Extract a ZIP (written by save_zip(path)) and add it as a project folder.
    unwrap: the ZIP holds one folder (like GitHub's "owner-repo-1a2b3c/"): add what's inside it."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        zip_path = Path(temp_dir) / "upload.zip"
        save_zip(str(zip_path))
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

        source = extract_path
        inside = list(extract_path.iterdir()) if extract_path.is_dir() else []
        if unwrap and len(inside) == 1 and inside[0].is_dir():
            source = inside[0]
        success, message = folder_manager.add_folder(source, folder_name)

    if success:
        return jsonify({'success': True, 'message': message, 'folder': folder_name})
    return jsonify({'success': False, 'error': message}), 400


@bp.route('/api/folders/upload-files', methods=['POST'])
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


@bp.route('/api/folders/list', methods=['GET'])
def list_folders():
    """List all uploaded folders"""
    folder_list = [{
        'name': name,
        'file_count': info.get('file_count', 0),
        'size': info.get('size', 0),
        'uploaded_at': info.get('uploaded_at', '')
    } for name, info in folder_manager.list_all_folders().items()]
    return jsonify({'success': True, 'folders': folder_list})


@bp.route('/api/folders/<folder_name>/contents', methods=['GET'])
def get_folder_contents(folder_name):
    """Get contents of a folder"""
    files, error = folder_manager.get_folder_contents(folder_name)
    if error:
        return jsonify({'error': error}), 404
    return jsonify({'success': True, 'files': files})


@bp.route('/api/folders/<folder_name>/file', methods=['POST'])
def read_folder_file(folder_name):
    """Read a specific file from a folder"""
    file_path = json_body().get('file_path')
    if not file_path:
        return jsonify({'error': 'No file path provided'}), 400

    content, error = folder_manager.read_file(folder_name, file_path)
    if error:
        return jsonify({'error': error}), 404
    return jsonify({'success': True, 'content': content})


@bp.route('/api/folders/<folder_name>/summary', methods=['GET'])
def get_folder_summary(folder_name):
    """Get a summary of folder contents"""
    summary = folder_manager.get_folder_summary(folder_name)
    return jsonify({'success': True, 'summary': summary, 'folder_name': folder_name})


@bp.route('/api/folders/<folder_name>/delete', methods=['DELETE'])
def delete_folder(folder_name):
    """Delete an uploaded folder"""
    success, message = folder_manager.delete_folder(folder_name)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'success': False, 'error': message}), 400
