from conversation_history import ConversationHistory


def test_add_and_read(tmp_path):
    h = ConversationHistory(tmp_path / "sub" / "h.db")  # parent folder is created
    assert h.count_messages() == 0
    first = h.add_message("User", "hi")
    second = h.add_message("Assistant", "hello")
    assert second == first + 1
    assert h.count_messages() == 2
    msgs = h.get_all_messages()
    assert [(m["role"], m["content"]) for m in msgs] == [("User", "hi"), ("Assistant", "hello")]
    assert msgs[0]["timestamp"]


def test_last_n_and_limit(tmp_path):
    h = ConversationHistory(tmp_path / "h.db")
    for i in range(10):
        h.add_message("User", f"m{i}")
    assert [m["content"] for m in h.get_last_n_messages(3)] == ["m7", "m8", "m9"]
    assert [m["content"] for m in h.get_all_messages(limit=2)] == ["m8", "m9"]
    assert len(h.get_all_messages(limit=0)) == 10


def test_new_conversation_resets_context_only(tmp_path):
    h = ConversationHistory(tmp_path / "h.db")
    h.add_message("User", "old")
    h.start_new_conversation()
    assert h.get_last_n_messages(5) == []
    h.add_message("User", "new")
    assert [m["content"] for m in h.get_last_n_messages(5)] == ["new"]
    # the marker itself is hidden everywhere
    assert [m["content"] for m in h.get_all_messages()] == ["old", "new"]
    assert h.count_messages() == 2


def test_format_for_prompt_truncates(tmp_path):
    h = ConversationHistory(tmp_path / "h.db")
    text = h.format_for_prompt([{"role": "User", "content": "x" * 900}], max_chars=10)
    assert text == "User: " + "x" * 10 + "\n"


def test_clear_and_persistence(tmp_path):
    path = tmp_path / "h.db"
    ConversationHistory(path).add_message("User", "kept")
    assert ConversationHistory(path).count_messages() == 1
    h = ConversationHistory(path)
    assert h.clear_history() is True
    assert h.count_messages() == 0


def test_sql_injection_is_stored_as_text(tmp_path):
    h = ConversationHistory(tmp_path / "h.db")
    h.add_message("User", "'); DROP TABLE conversation_history; --")
    assert h.count_messages() == 1
