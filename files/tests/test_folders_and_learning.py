import json
import threading

import pytest

from autonomous_improver import AutonomousImprover
from folder_manager import FolderManager
from learning_system import LearningSystem
from self_analyzer import SelfAnalyzer


# ---------------- FolderManager

@pytest.fixture
def source(tmp_path):
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "main.py").write_text("print('hi')\n")
    (src / "pkg" / "util.py").write_text("def f():\n    return 1\n")
    (src / "logo.png").write_bytes(b"\x89PNG")
    return src


@pytest.fixture
def fm(tmp_path):
    return FolderManager(tmp_path / "ai_files")


def test_add_list_contents_read_delete(fm, source):
    ok, message = fm.add_folder(source, "proj")
    assert ok, message
    info = fm.list_all_folders()["proj"]
    assert info["file_count"] == 3 and info["uploaded_at"]

    files, error = fm.get_folder_contents("proj")
    assert error is None
    assert [f["path"] for f in files] == ["logo.png", "main.py", "pkg/util.py"]

    assert fm.read_file("proj", "pkg/util.py") == ("def f():\n    return 1\n", None)
    assert fm.read_file("proj", "logo.png") == ("[Binary file: logo.png]", None)
    assert fm.read_file("proj", "nope.py") == (None, "File not found: nope.py")
    assert fm.read_file("proj", "../../escape.txt") == (None, "Access denied: file outside folder")
    assert fm.read_file("other", "main.py")[1] == "Folder not found: other"

    assert fm.delete_folder("proj")[0] is True
    assert fm.delete_folder("proj") == (False, "Folder not found")
    assert not (fm.uploads_path / "proj").exists()


def test_registry_persists_and_survives_corruption(fm, source, tmp_path):
    fm.add_folder(source, "proj")
    assert "proj" in FolderManager(tmp_path / "ai_files").list_all_folders()
    fm.registry_path.write_text("{broken")
    assert FolderManager(tmp_path / "ai_files").list_all_folders() == {}


def test_tampered_registry_path_is_ignored(fm, source, tmp_path):
    fm.add_folder(source, "proj")
    victim = tmp_path / "victim"
    victim.mkdir()
    fm.folders["proj"]["path"] = str(victim)  # old registries stored a path
    fm.delete_folder("proj")
    assert victim.exists()


def test_add_folder_errors_and_replace(fm, source, tmp_path):
    assert fm.add_folder(tmp_path / "missing")[0] is False
    assert fm.add_folder(source, "..") == (False, "Invalid folder name")
    fm.add_folder(source, "proj")
    (source / "main.py").unlink()
    fm.add_folder(source, "proj")  # same name replaces the old copy
    assert fm.list_all_folders()["proj"]["file_count"] == 2
    assert fm.add_folder(source)[0] and "src" in fm.list_all_folders()  # default name


def test_summary_and_context(fm, source):
    fm.add_folder(source, "proj")
    summary = fm.get_folder_summary("proj")
    assert "Files: 3" in summary and "pkg/util.py" in summary
    assert fm.get_folder_summary("nope") == "Error: Folder not found: nope"

    context, error = fm.get_folder_context("proj")
    assert error is None
    assert "--- main.py ---\nprint('hi')" in context and "--- pkg/util.py ---" in context
    assert "PNG" not in context

    small, _ = fm.get_folder_context("proj", max_chars=5)
    assert "--- main.py ---\nprint" in small and "1 more text files not shown" in small
    assert fm.get_folder_context("nope") == (None, "Folder not found: nope")


def test_empty_folder_summary(fm, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    fm.add_folder(empty, "empty")
    assert fm.get_folder_summary("empty") == "Folder 'empty' is empty"


# ---------------- LearningSystem

def test_logging_insights_and_persistence(tmp_path):
    ls = LearningSystem(tmp_path)
    ls.log_conversation("hi", "hello there")
    ls.log_feature_usage("weather")
    ls.log_code_execution(True)
    ls.log_code_execution(False)
    ls.log_file_operation("write", True)
    ls.log_knowledge_base_query()
    ls.log_web_search()
    ls.log_feedback(7, 1, "too slow")

    insights = ls.get_learning_insights()
    assert insights["total_conversations"] == 1
    assert insights["avg_response_length"] == len("hello there")
    assert insights["avg_user_rating"] == 1
    assert insights["improvement_areas"] == ["too slow"]
    assert ls.metrics["code_execution_success_rate"] == 50.0
    assert ls.get_most_used_features()["code_execution"] == 2

    recommendations = ls.get_improvement_recommendations()
    assert any("satisfaction" in r for r in recommendations)
    assert any("success rate" in r for r in recommendations)
    report = ls.format_learning_report()
    assert "Total Conversations: 1" in report and "too slow" in report

    reloaded = LearningSystem(tmp_path)
    assert reloaded.metrics["web_searches"] == 1
    reloaded.log_feature_usage("brand_new_feature")  # loaded dict still counts new keys
    assert reloaded.get_most_used_features(top_k=10)["brand_new_feature"] == 1


def test_disabled_writes_nothing(tmp_path):
    ls = LearningSystem(tmp_path / "logs", enabled=False)
    ls.log_conversation("a", "b")
    assert not ls.learning_log.exists()


def test_old_or_corrupt_files(tmp_path):
    (tmp_path / "learning_log.json").write_text("{not json")
    (tmp_path / "performance_metrics.json").write_text(json.dumps({"web_searches": 5}))
    ls = LearningSystem(tmp_path)
    assert ls.learning_data["conversations"] == []
    ls.log_file_operation("read", True)  # key missing from the old file gets a default
    assert ls.metrics["web_searches"] == 5 and ls.metrics["file_operations_count"] == 1


def test_conversation_log_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(LearningSystem, "MAX_LOGGED_CONVERSATIONS", 3)
    ls = LearningSystem(tmp_path)
    for i in range(5):
        ls.log_conversation(f"q{i}", "a")
    assert [c["user_input"] for c in ls.learning_data["conversations"]] == ["q2", "q3", "q4"]
    assert ls.get_learning_insights()["total_conversations"] == 5


def test_parallel_logging_keeps_valid_json(tmp_path):
    ls = LearningSystem(tmp_path)

    def work():
        for _ in range(20):
            ls.log_feature_usage("x")
            ls.log_conversation("q", "a")

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    saved = json.loads(ls.learning_log.read_text())
    assert saved["feature_usage"]["x"] == 160
    assert ls.metrics["total_conversations"] == 160


# ---------------- SelfAnalyzer / AutonomousImprover

SAMPLE = '''
def documented():
    """Has a docstring"""
    return 1


def undocumented():
    try:
        return 1
    except:
        return 2


class Bare:
    pass
'''


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "sample.py").write_text(SAMPLE)
    long_body = "\n".join(f"    x{i} = {i}" for i in range(60))
    (root / "long.py").write_text(f'"""Long"""\n\ndef big():\n    """Big"""\n{long_body}\n')
    (root / "broken.py").write_text("def oops(:\n")
    return root


def test_analyze_file(project, tmp_path):
    analyzer = SelfAnalyzer(project, tmp_path / "logs")
    ok, analysis = analyzer.analyze_file(project / "sample.py")
    assert ok
    assert {f["name"] for f in analysis["functions"]} == {"documented", "undocumented"}
    issues = " | ".join(analysis["issues"])
    assert "Function 'undocumented' missing docstring" in issues
    assert "Class 'Bare' missing docstring" in issues
    assert "Bare 'except:'" in issues
    assert analyzer.analyze_file(project / "missing.py") == (None, "File not found")
    ok, message = analyzer.analyze_file(project / "broken.py")
    assert ok is False and message.startswith("Syntax error")


def test_plan_score_and_report(project, tmp_path):
    analyzer = SelfAnalyzer(project, tmp_path / "logs")
    analyses = analyzer.analyze_all_files()
    assert set(analyses) == {"sample.py", "long.py", "broken.py"} and "error" in analyses["broken.py"]
    plan = analyzer.get_improvement_plan(analyses)
    assert any("Bare 'except:'" in i for i in plan["high_priority"])
    assert any("long.py" in i and "refactoring" in i for i in plan["medium_priority"])
    assert any("missing docstring" in i for i in plan["low_priority"])
    score = analyzer.get_code_quality_score(analyses)
    assert 0 <= score < 100
    report = analyzer.format_analysis_report(analyses)
    assert f"Overall Code Quality Score: {score}/100" in report
    assert analyzer.analysis_log.exists()
    assert SelfAnalyzer(tmp_path / "empty_dir_missing", tmp_path / "l2").get_code_quality_score() == 100


def test_improver(project, tmp_path):
    analyzer = SelfAnalyzer(project, tmp_path / "logs")
    learner = LearningSystem(tmp_path / "logs")
    improver = AutonomousImprover(analyzer, learner)
    proposals = improver.analyze_and_propose()
    assert any(p["type"] == "bug_fix" for p in proposals)
    text = improver.format_improvement_suggestions(proposals)
    assert "AUTONOMOUS IMPROVEMENT SUGGESTIONS" in text and "BUG_FIX" in text


