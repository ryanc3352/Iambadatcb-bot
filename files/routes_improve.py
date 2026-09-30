"""Self-improvement: code quality, learning stats, and upgrades the user approves."""
from pathlib import Path

from flask import Blueprint, jsonify

from config import ENABLE_SELF_IMPROVEMENT, UPGRADEABLE_FILES
from prompts import MAX_CODE_CONTEXT_CHARS, code_length
from routes_common import json_body
from services import analyzer, improver, learner, upgrade_manager

bp = Blueprint('improve', __name__)


@bp.route('/api/self/analyze', methods=['GET'])
def self_analyze():
    """Analyze own code quality"""
    analyses = analyzer.analyze_all_files()
    return jsonify({
        'success': True,
        'report': analyzer.format_analysis_report(analyses),
        'quality_score': analyzer.get_code_quality_score(analyses)
    })


@bp.route('/api/self/learning', methods=['GET'])
def self_learning():
    """Get AI learning statistics"""
    return jsonify({
        'success': True,
        'insights': learner.get_learning_insights(),
        'report': learner.format_learning_report()
    })


@bp.route('/api/self/improvements', methods=['GET'])
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
        size = code_length(path) if path.exists() else 0
        if 0 < size <= MAX_CODE_CONTEXT_CHARS and analysis['issues']:
            candidates.append((len(analysis['issues']), name))
    return max(candidates)[1] if candidates else None


@bp.route('/api/self/improvement-prompt', methods=['GET'])
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

Overall code quality score: {score} out of 100

Upgrades already applied:
{past_text}

Propose ONE UPGRADE_REQUEST for {target} that fixes these issues. Start from its current
code, keep every existing class, function and setting, and don't repeat earlier upgrades."""
    else:
        prompt = f"""Overall code quality score: {score} out of 100. No upgradeable file has issues right now.

{improver.format_improvement_suggestions(proposals)}
Upgrades already applied:
{past_text}

Suggest improvements in words; don't send an UPGRADE_REQUEST."""

    return jsonify({
        'success': True,
        'prompt': prompt,
        'target_file': target,
    })


@bp.route('/api/upgrade/apply', methods=['POST'])
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


@bp.route('/api/upgrade/history', methods=['GET'])
def upgrade_history():
    """Get upgrade history"""
    return jsonify({'history': upgrade_manager.get_upgrade_history()})


@bp.route('/api/upgrade/backups', methods=['GET'])
def list_backups():
    """List available backups"""
    return jsonify({'backups': upgrade_manager.list_backups()})


@bp.route('/api/upgrade/rollback', methods=['POST'])
def rollback():
    """Restore a file from a backup (pass the name from /api/upgrade/backups)"""
    backup_name = str(json_body().get('backup_path', '')).strip()
    if not backup_name:
        return jsonify({'error': 'Backup name required'}), 400

    success, message = upgrade_manager.rollback(backup_name)
    return jsonify({'success': success, 'message': message})
