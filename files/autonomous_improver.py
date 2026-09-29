from self_analyzer import SelfAnalyzer
from learning_system import LearningSystem
from pathlib import Path
import json
from datetime import datetime

class AutonomousImprover:
    """AI autonomous improvement system"""

    def __init__(self, analyzer=None, learner=None, data_dir="./backups"):
        # Share the server's instances so learning data isn't read from a stale copy
        self.analyzer = analyzer or SelfAnalyzer(data_dir=data_dir)
        self.learner = learner or LearningSystem(data_dir=data_dir)
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.improvement_queue = Path(data_dir) / "improvement_queue.json"
        self.improvement_history = Path(data_dir) / "improvement_history.json"
        self.load_queues()

    @staticmethod
    def _read_list(path):
        """Read a JSON list, returning [] if the file is missing or corrupt"""
        try:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError) as e:
            print(f"Could not read {path.name}, starting fresh: {e}")
        return []

    def load_queues(self):
        """Load improvement queues"""
        self.queue = self._read_list(self.improvement_queue)
        self.history = self._read_list(self.improvement_history)

    def save_queues(self):
        """Save improvement queues"""
        with open(self.improvement_queue, 'w', encoding='utf-8') as f:
            json.dump(self.queue, f, indent=2)

        with open(self.improvement_history, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, indent=2)

    def analyze_and_propose(self, all_analyses=None):
        """
        Analyze all code and propose improvements
        Returns: List of proposed improvements
        """
        if all_analyses is None:
            all_analyses = self.analyzer.analyze_all_files()
        code_quality_score = self.analyzer.get_code_quality_score(all_analyses)
        improvement_plan = self.analyzer.get_improvement_plan(all_analyses)

        proposals = []

        # Propose based on code quality
        if code_quality_score < 60:
            proposals.append({
                'type': 'code_quality',
                'priority': 'high',
                'description': f'Code quality score is {code_quality_score}/100. Refactor to improve structure.',
                'target_files': [issue.split(':')[0] for issue in improvement_plan['high_priority']][:3]
            })

        # Propose based on issues found
        for issue in improvement_plan['high_priority'][:2]:
            proposals.append({
                'type': 'bug_fix',
                'priority': 'high',
                'description': issue,
                'requires_approval': True
            })

        # Propose based on learning data
        for recommendation in self.learner.get_improvement_recommendations()[:2]:
            proposals.append({
                'type': 'feature_improvement',
                'priority': 'medium',
                'description': recommendation,
                'requires_approval': False
            })

        # Propose new features based on usage patterns
        features = self.learner.get_most_used_features()

        if features.get('knowledge_base', 0) > 10:
            proposals.append({
                'type': 'feature_enhancement',
                'priority': 'medium',
                'description': 'Knowledge base is frequently used. Add caching for faster queries.',
                'target_file': 'knowledge_base.py'
            })

        if features.get('code_execution', 0) > 15:
            proposals.append({
                'type': 'feature_enhancement',
                'priority': 'medium',
                'description': 'Code execution is heavily used. Add async execution for parallel processing.',
                'target_file': 'code_executor.py'
            })

        return proposals

    def queue_improvement(self, improvement_proposal):
        """Add improvement to queue"""
        entry = {
            'id': len(self.queue) + 1,
            'timestamp': datetime.now().isoformat(),
            'status': 'pending',
            'proposal': improvement_proposal
        }

        self.queue.append(entry)
        self.save_queues()

        return entry['id']

    def generate_improvement_prompt(self, improvement):
        """Generate a prompt for the AI to implement improvement"""
        proposal = improvement['proposal']

        if proposal['type'] == 'code_quality':
            prompt = f"""
Please improve the code quality of my system. Current score: {proposal['description']}

Analyze these files and suggest refactoring:
{', '.join(proposal.get('target_files', []))}

Focus on:
- Adding type hints
- Improving error handling
- Better code organization
- Adding docstrings

Generate complete improved versions of the files."""

        elif proposal['type'] == 'bug_fix':
            prompt = f"""
There's a code issue to fix:
"{proposal['description']}"

Please:
1. Identify the exact problem
2. Provide the fixed code
3. Explain the improvement

Format as an UPGRADE_REQUEST with the complete fixed file."""

        elif proposal['type'] == 'feature_enhancement':
            prompt = f"""
Suggestion: {proposal['description']}

File to enhance: {proposal.get('target_file', 'appropriate file')}

Please:
1. Analyze the current implementation
2. Propose specific improvements
3. Show the enhanced code with new features

Format as an UPGRADE_REQUEST."""

        else:
            prompt = f"Please implement this improvement: {proposal['description']}"

        return prompt

    def get_next_improvement(self):
        """Get the next pending improvement"""
        for improvement in self.queue:
            if improvement['status'] == 'pending':
                return improvement
        return None

    def format_improvement_suggestions(self, proposals=None):
        """Format all suggestions as readable text"""
        if proposals is None:
            proposals = self.analyze_and_propose()

        text = """
🤖 AUTONOMOUS IMPROVEMENT SUGGESTIONS
=====================================

The AI has analyzed itself and found these improvements:

"""

        for i, proposal in enumerate(proposals, 1):
            priority_emoji = "🔴" if proposal['priority'] == 'high' else "🟡"
            text += f"\n{i}. {priority_emoji} [{proposal['type'].upper()}] {proposal['description']}\n"

        return text

    def create_improvement_file(self, all_analyses=None):
        """
        Create a special file that the AI reads to understand
        what improvements to work on
        """
        if all_analyses is None:
            all_analyses = self.analyzer.analyze_all_files()
        plan = self.analyzer.get_improvement_plan(all_analyses)
        insights = self.learner.get_learning_insights()

        high_priority_files = sorted({issue.split(':')[0] for issue in plan['high_priority']})[:3]
        popular_features = ', '.join(f"{k}({v})" for k, v in insights['most_used_features'].items())
        feedback_areas = ', '.join(insights.get('improvement_areas', [])[:2])

        return {
            'timestamp': datetime.now().isoformat(),
            'code_quality_score': self.analyzer.get_code_quality_score(all_analyses),
            'total_issues': sum(len(plan[c]) for c in ('high_priority', 'medium_priority', 'low_priority')),
            'proposals': self.analyze_and_propose(all_analyses),
            'learning_insights': insights,
            'instructions': f"""
You can improve yourself by:
1. Analyzing the proposals below
2. Suggesting UPGRADE_REQUEST for approved improvements
3. Refactoring existing files for better quality

Current state analysis shows:
- Code quality issues in: {', '.join(high_priority_files) or 'none'}
- Most used features: {popular_features or 'none yet'}
- User feedback areas: {feedback_areas or 'none'}

Priority improvements:
1. Address code quality issues
2. Optimize frequently used features
3. Add missing error handling
4. Improve documentation

Always format upgrades as UPGRADE_REQUEST blocks.
"""
        }

    def log_improvement_applied(self, improvement_id, file_modified, success):
        """Log when an improvement is applied"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'improvement_id': improvement_id,
            'file_modified': file_modified,
            'success': success
        }

        self.history.append(entry)

        # Mark as completed in queue
        for improvement in self.queue:
            if improvement['id'] == improvement_id:
                improvement['status'] = 'completed'
                break

        self.save_queues()
