import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

class LearningSystem:
    """Track AI performance and learn from interactions"""

    MAX_LOGGED_CONVERSATIONS = 1000

    def __init__(self, data_dir="./backups"):
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        self.learning_log = data_dir / "learning_log.json"
        self.performance_metrics = data_dir / "performance_metrics.json"
        self.load_logs()

    @staticmethod
    def _read_json(path):
        """Read a JSON file, returning {} if it is missing or corrupt."""
        try:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Could not read {path.name}, starting fresh: {e}")
        return {}

    def load_logs(self):
        """Load existing learning data (missing keys get defaults)"""
        data = self._read_json(self.learning_log)
        self.learning_data = {
            'conversations': data.get('conversations', []),
            'improvements': data.get('improvements', []),
            'user_feedback': data.get('user_feedback', []),
            # JSON loads a plain dict; defaultdict lets new features start at 0
            'feature_usage': defaultdict(int, data.get('feature_usage', {}))
        }

        self.metrics = {
            'total_conversations': 0,
            'avg_response_quality': 0,
            'code_execution_success_rate': 0,
            'file_operations_count': 0,
            'knowledge_base_queries': 0,
            'web_searches': 0
        }
        self.metrics.update(self._read_json(self.performance_metrics))

    def save_logs(self):
        """Save learning data"""
        with open(self.learning_log, 'w', encoding='utf-8') as f:
            # Convert defaultdict to regular dict for JSON serialization
            data = self.learning_data.copy()
            data['feature_usage'] = dict(data['feature_usage'])
            json.dump(data, f, indent=2)

        with open(self.performance_metrics, 'w', encoding='utf-8') as f:
            json.dump(self.metrics, f, indent=2)

    def log_conversation(self, user_input, ai_response, metadata=None):
        """Log a conversation for learning"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'user_input': user_input,
            'ai_response': ai_response[:500],  # First 500 chars
            'response_length': len(ai_response),
            'metadata': metadata or {}
        }

        self.learning_data['conversations'].append(entry)
        del self.learning_data['conversations'][:-self.MAX_LOGGED_CONVERSATIONS]
        self.metrics['total_conversations'] += 1
        self.save_logs()

    def log_feature_usage(self, feature_name):
        """Track which features are used most"""
        self.learning_data['feature_usage'][feature_name] += 1
        self.save_logs()

    def log_code_execution(self, success):
        """Track code execution success rate"""
        total = self.metrics.get('code_executions', 0) + 1
        successes = self.metrics.get('code_execution_successes', 0)

        if success:
            successes += 1

        self.metrics['code_executions'] = total
        self.metrics['code_execution_successes'] = successes
        self.metrics['code_execution_success_rate'] = round((successes / total * 100), 2)
        self.save_logs()

    def log_file_operation(self, operation_type, success):
        """Track file operations"""
        self.metrics['file_operations_count'] += 1
        self.log_feature_usage(f'file_{operation_type}')

    def log_knowledge_base_query(self):
        """Track knowledge base usage"""
        self.metrics['knowledge_base_queries'] += 1
        self.log_feature_usage('knowledge_base')

    def log_web_search(self):
        """Track web search usage"""
        self.metrics['web_searches'] += 1
        self.log_feature_usage('web_search')

    def log_feedback(self, conversation_id, rating, feedback_text):
        """Log user feedback for improvement"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'conversation_id': conversation_id,
            'rating': rating,  # 1-5 stars
            'feedback': feedback_text
        }

        self.learning_data['user_feedback'].append(entry)
        self.save_logs()

    def get_most_used_features(self, top_k=5):
        """Get most frequently used features"""
        sorted_features = sorted(
            self.learning_data['feature_usage'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        return dict(sorted_features[:top_k])

    def get_learning_insights(self):
        """Generate insights about AI performance"""
        insights = {
            'timestamp': datetime.now().isoformat(),
            'metrics': self.metrics,
            'most_used_features': self.get_most_used_features(),
            'avg_response_length': 0,
            'total_conversations': self.metrics.get('total_conversations', 0),
            'avg_user_rating': 0,
            'improvement_areas': []
        }

        # Calculate average response length
        if self.learning_data['conversations']:
            avg_length = sum(c['response_length'] for c in self.learning_data['conversations']) / len(self.learning_data['conversations'])
            insights['avg_response_length'] = round(avg_length, 2)

        # Calculate average rating
        if self.learning_data['user_feedback']:
            avg_rating = sum(f['rating'] for f in self.learning_data['user_feedback']) / len(self.learning_data['user_feedback'])
            insights['avg_user_rating'] = round(avg_rating, 2)

            # Find improvement areas (low ratings)
            low_ratings = [f for f in self.learning_data['user_feedback'] if f['rating'] <= 2]
            if low_ratings:
                insights['improvement_areas'] = [f['feedback'] for f in low_ratings[-3:]]

        return insights

    def get_improvement_recommendations(self):
        """AI suggests what to improve based on learning data"""
        insights = self.get_learning_insights()
        recommendations = []

        # Recommend based on low ratings
        if insights['avg_user_rating'] > 0 and insights['avg_user_rating'] < 3.5:
            recommendations.append("User satisfaction is below target. Focus on improving response quality.")

        # Recommend based on unused features
        if not self.learning_data['feature_usage'].get('knowledge_base', 0):
            recommendations.append("Knowledge base feature is unused. Optimize or promote it.")

        if not self.learning_data['feature_usage'].get('web_search', 0):
            recommendations.append("Web search feature is unused. Consider improving integration.")

        # Recommend based on code execution
        if self.metrics.get('code_execution_success_rate', 100) < 80:
            recommendations.append("Code execution success rate is low. Improve sandbox safety and error handling.")

        # Recommend based on conversation patterns
        if insights['total_conversations'] > 100:
            recommendations.append("You have enough conversation data. Consider fine-tuning the model on your style.")

        return recommendations

    def format_learning_report(self):
        """Format learning insights as readable report"""
        insights = self.get_learning_insights()
        recommendations = self.get_improvement_recommendations()

        report = f"""
📈 AI LEARNING REPORT
=====================

Total Conversations: {insights['total_conversations']}
Average Response Length: {insights['avg_response_length']} characters
Code Execution Success Rate: {self.metrics.get('code_execution_success_rate', 0)}%
Average User Rating: {insights['avg_user_rating']}/5.0

MOST USED FEATURES:
{chr(10).join(f"  • {feature}: {count} times" for feature, count in insights['most_used_features'].items())}

IMPROVEMENT RECOMMENDATIONS:
{chr(10).join(f"  💡 {rec}" for rec in recommendations) if recommendations else "  ✅ No improvements needed"}

IMPROVEMENT AREAS FROM FEEDBACK:
{chr(10).join(f"  ⚠️  {area}" for area in insights['improvement_areas']) if insights['improvement_areas'] else "  ✅ All areas performing well"}
"""
        return report
