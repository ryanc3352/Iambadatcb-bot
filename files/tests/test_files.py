"""Creating and adding files: the AI's Save cards, My Files, folder picking, Windows write errors."""
import io
import json

import pytest

import web_server as ws
from file_handler import FileHandler


@pytest.fixture
def client(fake_ollama):
    ws.conversation_history.start_new_conversation()
    for f in ws.file_handler.list_all_files():  # start each test with an empty ai_files
        ws.file_handler.delete_file(f["path"])
    return ws.app.test_client()


def sse_events(response):
    return [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data: ")]


# ---------------- FileHandler helpers

@pytest.mark.parametrize("raw,clean", [
    ("notes\\todo.txt", "notes/todo.txt"), ("/todo.txt", "todo.txt"), ("C:\\Users\\x\\list.txt", "Users/x/list.txt"),
    ("`shopping.txt`", "shopping.txt"), ("./a/./b.txt", "a/b.txt"), ('"quoted.md"', "quoted.md"),
])
def test_clean_relative_path(raw, clean):
    assert FileHandler.clean_relative_path(raw) == clean


@pytest.mark.parametrize("raw", ["", "a/../b.txt", "..", "user_uploads/x.txt", "folder_registry.json", "/"])
def test_clean_relative_path_rejects(raw):
    with pytest.raises(ValueError):
        FileHandler.clean_relative_path(raw)


def test_list_all_files_skips_internal(tmp_path):
    fh = FileHandler(tmp_path)
    fh.write_file("a.txt", "1")
    fh.write_file("sub/b.txt", "2")
    (tmp_path / "user_uploads" / "proj").mkdir(parents=True)
    (tmp_path / "user_uploads" / "proj" / "x.py").write_text("x")
    (tmp_path / "folder_registry.json").write_text("{}")
    assert {f["path"] for f in fh.list_all_files()} == {"a.txt", "sub/b.txt"}


# ---------------- the AI proposes a file, the user saves it

REPLY = "Here you go:\nSAVE_FILE: shopping/list.txt\n```\nmilk\neggs\n```\nAnything else?"


def test_chat_returns_files_to_save(client, fake_ollama):
    fake_ollama.reply = REPLY
    data = client.post("/api/chat", json={"message": "make me a shopping list file"}).get_json()
    assert data["files"] == [{"path": "shopping/list.txt", "content": "milk\neggs"}]
    assert data["has_code"] is False  # file contents are saved, not run

    done = sse_events(client.post("/api/chat-stream", json={"message": "again"}))[-1]
    assert done["files"] == [{"path": "shopping/list.txt", "content": "milk\neggs"}]


@pytest.mark.parametrize("reply,path", [
    ("SAVE_FILE: notes.md\n```markdown\n# Hi\n```", "notes.md"),
    ("**SAVE_FILE:** `todo.txt`\n\n```text\n- a\n```", "todo.txt"),
    ("SAVE_FILE: code\\app.py\n```python\nprint(1)\n```", "code/app.py"),
])
def test_save_block_variants(client, fake_ollama, reply, path):
    fake_ollama.reply = reply
    assert client.post("/api/chat", json={"message": "x"}).get_json()["files"][0]["path"] == path


def test_unsafe_save_paths_are_dropped(client, fake_ollama):
    fake_ollama.reply = "SAVE_FILE: ../../evil.txt\n```\nx\n```\nSAVE_FILE: ok.txt\n```\ny\n```"
    assert [f["path"] for f in client.post("/api/chat", json={"message": "x"}).get_json()["files"]] == ["ok.txt"]


def test_save_list_download_delete(client):
    saved = client.post("/api/files/save", json={"path": "shopping/list.txt", "content": "milk\neggs 🥚"}).get_json()
    assert saved == {"success": True, "path": "shopping/list.txt", "message": "✅ Saved shopping/list.txt in your ai_files folder"}
    assert [f["path"] for f in client.get("/api/files").get_json()["files"]] == ["shopping/list.txt"]
    assert client.get("/api/stats").get_json()["files"] == 1

    download = client.get("/api/files/download?path=shopping/list.txt")
    assert download.status_code == 200 and download.get_data(as_text=True) == "milk\neggs 🥚"
    assert "attachment" in download.headers["Content-Disposition"]

    assert client.delete("/api/files?path=shopping/list.txt").get_json()["success"]
    assert client.delete("/api/files?path=shopping/list.txt").status_code == 404
    assert client.get("/api/files/download?path=shopping/list.txt").status_code == 404


@pytest.mark.parametrize("payload,status", [
    ({"path": "../x.txt", "content": "x"}, 400), ({"path": "user_uploads/x", "content": "x"}, 400),
    ({"path": "a.txt"}, 400), ({"path": "", "content": "x"}, 400),
    ({"path": "big.txt", "content": "x" * 1_000_001}, 400),
])
def test_save_rejects(client, payload, status):
    assert client.post("/api/files/save", json=payload).status_code == status


def test_download_rejects_traversal(client):
    assert client.get("/api/files/download?path=../../config.py").status_code == 400


def test_existing_files_are_shown_to_the_model(client, fake_ollama):
    client.post("/api/files/save", json={"path": "shopping.txt", "content": "milk\nbread"})
    client.post("/api/chat", json={"message": "add eggs to shopping.txt"})
    prompt = fake_ollama.last_prompt
    assert "Current content of shopping.txt:\n```\nmilk\nbread\n```" in prompt
    client.post("/api/chat", json={"message": "which files do I have?"})
    assert "The user's saved files (in their ai_files folder): shopping.txt" in fake_ollama.last_prompt
    client.post("/api/chat", json={"message": "tell me a joke"})
    assert "The user's saved files (in their" not in fake_ollama.last_prompt


def test_windows_write_errors_get_a_hint(client, monkeypatch):
    def blocked(path, content):
        raise PermissionError(13, "Access is denied", path)
    monkeypatch.setattr(ws.file_handler, "write_file", blocked)
    response = client.post("/api/files/save", json={"path": "a.txt", "content": "x"})
    assert response.status_code == 500 and "Controlled folder access" in response.get_json()["error"]

    def our_check(path, content):
        raise PermissionError("Cannot access files outside the folder")
    monkeypatch.setattr(ws.file_handler, "write_file", our_check)
    response = client.post("/api/files/save", json={"path": "a.txt", "content": "x"})
    assert response.status_code == 403 and "Controlled" not in response.get_json()["error"]


# ---------------- adding a folder without zipping it

def test_upload_folder_files(client, fake_ollama):
    files = [(io.BytesIO(b"print('main')\n"), "myproj/main.py"),
             (io.BytesIO(b"# Notes\n"), "myproj/docs/notes.md"),
             (io.BytesIO(b"secret"), "myproj/.git/config"),
             (io.BytesIO(b"x"), "myproj/node_modules/lib.js"),
             (io.BytesIO(b"evil"), "myproj/../../evil.txt")]
    response = client.post("/api/folders/upload-files", data={"files": files, "folder_name": "myproj"},
                           content_type="multipart/form-data").get_json()
    assert response["success"] and response["files"] == 2, response
    paths = {f["path"] for f in client.get("/api/folders/myproj/contents").get_json()["files"]}
    assert paths == {"main.py", "docs/notes.md"}  # '..' paths and tool folders are skipped

    client.post("/api/chat/with-folder", json={"message": "what does main.py print?", "folder_name": "myproj"})
    assert "--- main.py ---\nprint('main')" in fake_ollama.last_prompt
    client.delete("/api/folders/myproj/delete")


def test_upload_folder_files_errors(client):
    assert client.post("/api/folders/upload-files", data={}, content_type="multipart/form-data").status_code == 400
    only_skipped = client.post("/api/folders/upload-files",
                               data={"files": [(io.BytesIO(b"x"), "p/.git/HEAD")]}, content_type="multipart/form-data")
    assert only_skipped.status_code == 400


def test_more_document_types(client):
    upload = client.post("/api/knowledge-base/upload",
                         data={"file": (io.BytesIO(b"name,age\nSam,30\n"), "people.csv")},
                         content_type="multipart/form-data").get_json()
    assert upload["success"], upload
    client.delete("/api/knowledge-base/delete/people.csv")
