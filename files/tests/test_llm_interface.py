import pytest

from llm_interface import LLMInterface, LLMError


def make(url, **kwargs):
    return LLMInterface("mistral", 0.5, 100, url, **kwargs)


def test_connection_ok(fake_ollama):
    assert make(fake_ollama.url).test_connection() is True


def test_connection_refused():
    assert make("http://127.0.0.1:9").test_connection() is False


def test_generate_sends_options(fake_ollama):
    llm = make(fake_ollama.url, context_tokens=4096)
    assert llm.generate_response("hi") == "Hello from the fake model!"
    sent = fake_ollama.requests[-1]
    assert sent["model"] == "mistral" and sent["stream"] is False and sent["prompt"] == "hi"
    assert sent["options"] == {"temperature": 0.5, "num_predict": 100, "num_ctx": 4096}


def test_generate_strips_whitespace(fake_ollama):
    fake_ollama.reply = "  padded \n"
    assert make(fake_ollama.url).generate_response("x") == "padded"


def test_generate_http_error_raises_with_ollama_message(fake_ollama):
    fake_ollama.status, fake_ollama.error = 404, "model 'mistral' not found"
    with pytest.raises(LLMError, match="not found"):
        make(fake_ollama.url).generate_response("hi")


def test_generate_unreachable_raises():
    with pytest.raises(LLMError, match="Can't connect"):
        make("http://127.0.0.1:9").generate_response("hi")


def test_generate_timeout_raises(fake_ollama):
    fake_ollama.delay = 2
    with pytest.raises(LLMError, match="too long"):
        make(fake_ollama.url, timeout=1).generate_response("hi")


def test_stream_yields_tokens(fake_ollama):
    fake_ollama.reply = "one two three"
    tokens = list(make(fake_ollama.url).generate_response_stream("hi"))
    assert tokens == ["one", " two", " three"]
    assert fake_ollama.requests[-1]["stream"] is True


def test_stream_error_line_raises(fake_ollama):
    fake_ollama.stream_error = "out of memory"
    gen = make(fake_ollama.url).generate_response_stream("hi")
    assert next(gen) == "Hello"
    with pytest.raises(LLMError, match="out of memory"):
        list(gen)


def test_stream_http_error_raises(fake_ollama):
    fake_ollama.status = 500
    with pytest.raises(LLMError, match="500"):
        list(make(fake_ollama.url).generate_response_stream("hi"))


def test_stream_unreachable_raises():
    with pytest.raises(LLMError):
        list(make("http://127.0.0.1:9").generate_response_stream("hi"))


def test_test_model_prints(fake_ollama, capsys):
    make(fake_ollama.url).test_model()
    assert "Hello from the fake model!" in capsys.readouterr().out
    make("http://127.0.0.1:9").test_model()
    assert "✗" in capsys.readouterr().out
