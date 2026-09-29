"""The terminal chat (python main.py) uses the same answers and memory as the web page."""
import main
import services as sv


def run(monkeypatch, capsys, *typed):
    answers = iter(typed)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    main.main()
    return capsys.readouterr().out


def test_terminal_chat(fake_ollama, monkeypatch, capsys):
    sv.conversation_history.start_new_conversation()
    fake_ollama.reply = "Hi there!"
    before = sv.conversation_history.count_messages()
    out = run(monkeypatch, capsys, "hello", "", "stats", "new", "exit")
    assert "AI: Hi there!" in out and "Started a new conversation." in out
    assert f"Total messages stored: {before + 2}" in out
    assert "🧮 Calculator" not in fake_ollama.last_prompt
    run(monkeypatch, capsys, "what is 1234*5678?", "exit")
    assert "🧮 Calculator results" in fake_ollama.last_prompt  # same prompt as the web page


def test_terminal_chat_without_ollama(monkeypatch, capsys):
    monkeypatch.setattr(sv.llm_interface, "test_connection", lambda: False)
    assert "Ollama isn't running" in run(monkeypatch, capsys)
