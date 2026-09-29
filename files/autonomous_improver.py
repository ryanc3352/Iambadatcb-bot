"""Improvement proposals from the code analysis and from what the learning system has seen."""


class AutonomousImprover:
    """Turns code analysis and usage data into improvement proposals."""

    def __init__(self, analyzer, learner):
        # The server's own instances, so learning data isn't read from a stale copy
        self.analyzer = analyzer
        self.learner = learner

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
