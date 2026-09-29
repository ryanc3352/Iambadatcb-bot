import ast
from pathlib import Path
from datetime import datetime
import json

class SelfAnalyzer:
    """AI analyzes its own code and suggests improvements"""

    def __init__(self, project_root=".", data_dir="./backups"):
        self.project_root = Path(project_root)
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.analysis_log = Path(data_dir) / "analysis_log.json"
        self.code_metrics = {}
        self.load_analysis_log()

    def load_analysis_log(self):
        """Load previous analysis results"""
        self.code_metrics = {}
        try:
            if self.analysis_log.exists():
                with open(self.analysis_log, 'r', encoding='utf-8') as f:
                    self.code_metrics = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Could not read analysis log, starting fresh: {e}")

    def save_analysis_log(self):
        """Save analysis results"""
        with open(self.analysis_log, 'w', encoding='utf-8') as f:
            json.dump(self.code_metrics, f, indent=2)

    def analyze_file(self, file_path):
        """
        Analyze a Python file for:
        - Code quality
        - Performance issues
        - Missing features
        - Outdated patterns

        Returns analysis report
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                return None, "File not found"

            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()

            # Parse the code
            tree = ast.parse(code)

            analysis = {
                'file': str(file_path),
                'timestamp': datetime.now().isoformat(),
                'lines_of_code': len(code.split('\n')),
                'functions': [],
                'classes': [],
                'imports': [],
                'issues': [],
                'improvement_suggestions': []
            }

            # Extract functions
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis['functions'].append({
                        'name': node.name,
                        'line': node.lineno,
                        'docstring': ast.get_docstring(node) is not None
                    })

                if isinstance(node, ast.ClassDef):
                    analysis['classes'].append({
                        'name': node.name,
                        'line': node.lineno,
                        'methods': len([n for n in node.body if isinstance(n, ast.FunctionDef)])
                    })

                if isinstance(node, ast.Import):
                    for alias in node.names:
                        analysis['imports'].append(alias.name)

                if isinstance(node, ast.ImportFrom):
                    analysis['imports'].append(f"{node.module}")

            # Check for issues
            analysis['issues'] = self._check_code_issues(code, tree)
            analysis['improvement_suggestions'] = self._suggest_improvements(code, analysis)

            # Store metrics (saved once by analyze_all_files)
            self.code_metrics[file_path.name] = analysis

            return True, analysis

        except SyntaxError as e:
            return False, f"Syntax error: {str(e)}"
        except Exception as e:
            return False, f"Analysis error: {str(e)}"

    def _check_code_issues(self, code, tree):
        """Check for common code quality issues"""
        issues = []

        # Check for missing docstrings in functions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if ast.get_docstring(node) is None:
                    issues.append(f"Function '{node.name}' missing docstring")

            if isinstance(node, ast.ClassDef):
                if ast.get_docstring(node) is None:
                    issues.append(f"Class '{node.name}' missing docstring")

        # Check for long functions (over 50 lines)
        functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        for func in functions:
            func_lines = func.end_lineno - func.lineno if func.end_lineno else 0
            if func_lines > 50:
                issues.append(f"Function '{func.name}' is {func_lines} lines (consider refactoring)")

        # Check for bare `except:` (catches KeyboardInterrupt/SystemExit too)
        bare = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.type is None]
        if bare:
            issues.append(f"Bare 'except:' exception handling on lines {bare[:5]} (use specific exceptions)")

        return issues

    def _suggest_improvements(self, code, analysis):
        """Generate improvement suggestions"""
        suggestions = []

        # Suggest based on code size
        if analysis['lines_of_code'] > 500:
            suggestions.append("File is large - consider splitting into smaller modules")

        # Suggest based on number of functions
        if len(analysis['functions']) > 20:
            suggestions.append("Many functions - consider organizing into classes")

        # Check for duplicated imports
        if len(analysis['imports']) != len(set(analysis['imports'])):
            suggestions.append("Duplicate imports detected - consolidate imports")

        # Suggest error handling
        if 'try:' not in code:
            suggestions.append("Add error handling for robustness")

        # Suggest type hints
        if 'def ' in code and '->' not in code:
            suggestions.append("Add type hints to functions for clarity")

        # Suggest caching if many similar operations
        if code.count('for ') > 3 and code.count('in ') > 3:
            suggestions.append("Consider caching frequently accessed data")

        return suggestions

    def analyze_all_files(self):
        """Analyze all Python files in the project folder"""
        results = {}
        for path in sorted(self.project_root.glob("*.py")):
            success, analysis = self.analyze_file(path)
            results[path.name] = analysis if success else {'error': analysis}
        self.save_analysis_log()
        return results

    def get_improvement_plan(self, all_analyses=None):
        """Generate a prioritized improvement plan"""
        if all_analyses is None:
            all_analyses = self.analyze_all_files()

        plan = {
            'timestamp': datetime.now().isoformat(),
            'total_issues': 0,
            'high_priority': [],
            'medium_priority': [],
            'low_priority': [],
            'proposed_upgrades': []
        }

        for file_name, analysis in all_analyses.items():
            if isinstance(analysis, dict) and 'issues' in analysis:
                plan['total_issues'] += len(analysis['issues'])

                # Categorize by priority
                for issue in analysis['issues']:
                    if 'missing docstring' in issue:
                        plan['low_priority'].append(f"{file_name}: {issue}")
                    elif 'refactoring' in issue.lower():
                        plan['medium_priority'].append(f"{file_name}: {issue}")
                    elif 'except' in issue.lower():
                        plan['high_priority'].append(f"{file_name}: {issue}")

                # Improvement suggestions
                for suggestion in analysis.get('improvement_suggestions', []):
                    plan['proposed_upgrades'].append({
                        'file': file_name,
                        'suggestion': suggestion,
                        'priority': 'medium'
                    })

        return plan

    def get_code_quality_score(self, all_analyses=None):
        """Calculate overall code quality score (0-100)"""
        if all_analyses is None:
            all_analyses = self.analyze_all_files()

        total_issues = 0
        total_files = 0

        for analysis in all_analyses.values():
            if isinstance(analysis, dict) and 'issues' in analysis:
                total_issues += len(analysis['issues'])
                total_files += 1

        if total_files == 0:
            return 100

        # Score: 100 - (issues per file * 5)
        issues_per_file = total_issues / total_files
        score = max(0, 100 - (issues_per_file * 5))

        return round(score, 2)

    def format_analysis_report(self, all_analyses=None):
        """Format analysis as human-readable report"""
        if all_analyses is None:
            all_analyses = self.analyze_all_files()
        plan = self.get_improvement_plan(all_analyses)
        score = self.get_code_quality_score(all_analyses)

        report = f"""
📊 CODE QUALITY ANALYSIS REPORT
================================

Overall Code Quality Score: {score}/100

Total Issues Found: {plan['total_issues']}

HIGH PRIORITY ISSUES:
{chr(10).join(f"  🔴 {issue}" for issue in plan['high_priority'][:5]) if plan['high_priority'] else "  ✅ None"}

MEDIUM PRIORITY ISSUES:
{chr(10).join(f"  🟡 {issue}" for issue in plan['medium_priority'][:5]) if plan['medium_priority'] else "  ✅ None"}

LOW PRIORITY ISSUES:
{chr(10).join(f"  🟢 {issue}" for issue in plan['low_priority'][:5]) if plan['low_priority'] else "  ✅ None"}

PROPOSED UPGRADES:
{chr(10).join(f"  💡 {upgrade['file']}: {upgrade['suggestion']}" for upgrade in plan['proposed_upgrades'][:5]) if plan['proposed_upgrades'] else "  ✅ No upgrades needed"}
"""
        return report
