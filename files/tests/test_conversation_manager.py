from conversation_manager import ConversationManager


def test_session_crud(tmp_path):
    m = ConversationManager(tmp_path / "s.db")
    first = m.create_session("First", "a,b")
    second = m.create_session("Second")
    sessions = m.get_all_sessions()
    assert [s["name"] for s in sessions] == ["Second", "First"]  # newest first
    assert sessions[1]["tags"] == "a,b" and sessions[1]["created_at"]

    assert m.update_session_name(first, "Renamed") is True
    assert m.update_session_name(999, "Nope") is False
    assert {s["name"] for s in m.get_all_sessions()} == {"Renamed", "Second"}

    assert m.delete_session(second) is True
    assert m.delete_session(second) is False
    assert len(m.get_all_sessions()) == 1
