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


def test_persistence(tmp_path):
    path = tmp_path / "h.db"
    ConversationHistory(path).add_message("User", "kept")
    assert ConversationHistory(path).count_messages() == 1


def test_sql_injection_is_stored_as_text(tmp_path):
    h = ConversationHistory(tmp_path / "h.db")
    h.add_message("User", "'); DROP TABLE conversation_history; --")
    assert h.count_messages() == 1


def test_chats_list_open_rename_delete(tmp_path):
    h = ConversationHistory(tmp_path / "h.db")
    first = h.current_conversation_id()
    h.add_message("User", "  What   is\nthe weather?  ")
    h.add_message("Assistant", "Sunny")
    second = h.start_new_conversation()
    assert second != first
    assert h.start_new_conversation() == second  # an empty chat is reused, not piled up
    assert h.get_last_n_messages(5) == []
    h.add_message("User", "x" * 100)

    chats = h.list_conversations()
    assert [c["id"] for c in chats] == [second, first]  # most recently used first
    assert chats[1]["title"] == "What is the weather?"
    assert chats[1]["message_count"] == 2 and chats[1]["updated"]
    assert len(chats[0]["title"]) == 60 and chats[0]["title"].endswith("…")

    # Reopening an old chat carries it on
    assert h.open_conversation(first)
    assert h.current_conversation_id() == first
    h.add_message("User", "And tomorrow?")
    assert [m["content"] for m in h.get_last_n_messages(5)][-2:] == ["Sunny", "And tomorrow?"]
    assert [c["id"] for c in h.list_conversations()] == [first, second]
    assert [m["content"] for m in h.get_conversation(second)["messages"]] == ["x" * 100]

    assert h.rename_conversation(first, "  Weather  chat ")
    assert h.get_conversation(first)["title"] == "Weather chat"
    assert h.rename_conversation(first, "")  # back to the first question
    assert h.get_conversation(first)["title"] == "What is the weather?"

    # Deleting another chat keeps the current one; deleting the current one starts a new chat
    assert len(h.delete_conversation(second)) == 1
    assert h.current_conversation_id() == first
    deleted = h.delete_conversation(first)
    assert len(deleted) == 3
    assert h.current_conversation_id() not in (first, second)
    assert h.list_conversations() == [] and h.count_messages() == 0

    for missing in (first, 12345):
        assert h.get_conversation(missing) is None
        assert not h.open_conversation(missing)
        assert not h.rename_conversation(missing, "x")
        assert h.delete_conversation(missing) is None


def test_old_history_is_split_into_chats(tmp_path):
    """Databases from before chats had ids: the 'new conversation' markers split them."""
    import sqlite3
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE conversation_history (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                     "role TEXT NOT NULL, content TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        rows = [("User", "first chat"), ("Assistant", "a1"), ("System", "--- new conversation ---"),
                ("System", "--- new conversation ---"), ("User", "second chat"), ("Assistant", "a2")]
        conn.executemany("INSERT INTO conversation_history (role, content) VALUES (?, ?)", rows)
    conn.close()

    h = ConversationHistory(path)
    chats = h.list_conversations()
    assert [c["title"] for c in chats] == ["second chat", "first chat"]
    assert h.current_conversation_id() == chats[0]["id"]  # carries on where it was
    assert [m["content"] for m in h.get_last_n_messages(5)] == ["second chat", "a2"]
    assert h.count_messages() == 4
    assert [c["title"] for c in ConversationHistory(path).list_conversations()] == ["second chat", "first chat"]


def test_old_history_ending_with_new_conversation(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE conversation_history (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                     "role TEXT NOT NULL, content TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.executemany("INSERT INTO conversation_history (role, content) VALUES (?, ?)",
                         [("User", "old"), ("System", "--- new conversation ---")])
    conn.close()
    h = ConversationHistory(path)
    assert h.get_last_n_messages(5) == []  # the new conversation stays empty
    assert [c["title"] for c in h.list_conversations()] == ["old"]
