"""Creating and adding files: the AI's Save cards, My Files, folder picking, Windows write errors."""
import io
import json

import pytest

import web_server as ws
import file_offers
import services as sv
from file_handler import FileHandler


@pytest.fixture
def client(fake_ollama):
    sv.conversation_history.start_new_conversation()
    for f in sv.file_handler.list_all_files():  # start each test with an empty ai_files
        sv.file_handler.delete_file(f["path"])
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


def test_files_are_saved_exactly_as_written_even_on_windows(tmp_path, monkeypatch):
    """Windows turns \\n into \\r\\n when writing text; saved files must match what the AI wrote."""
    import pathlib
    real = pathlib.Path.write_text

    def windows_write_text(self, data, encoding=None, errors=None, newline=None):
        if newline is None:  # what text mode does on Windows
            data, newline = data.replace("\n", "\r\n"), ""
        return real(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(pathlib.Path, "write_text", windows_write_text)
    fh = FileHandler(tmp_path)
    fh.write_file("list.txt", "milk\neggs\n")
    assert (tmp_path / "list.txt").read_bytes() == b"milk\neggs\n"


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
    assert data["files"] == [{"path": "shopping/list.txt", "content": "milk\neggs", "exists": False}]
    assert data["has_code"] is False  # file contents are saved, not run

    done = sse_events(client.post("/api/chat-stream", json={"message": "again"}))[-1]
    assert done["files"] == [{"path": "shopping/list.txt", "content": "milk\neggs", "exists": False}]


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
    assert saved["success"] and saved["path"] == "shopping/list.txt"
    assert saved["message"] == f"✅ Saved shopping/list.txt (on your PC: {sv.file_handler.allowed_directory / 'shopping/list.txt'})"
    assert [f["path"] for f in client.get("/api/files").get_json()["files"]] == ["shopping/list.txt"]
    assert client.get("/api/stats").get_json()["files"] == 1

    download = client.get("/api/files/download?path=shopping/list.txt")
    body, disposition = download.get_data(as_text=True), download.headers["Content-Disposition"]
    download.close()  # the file stays open until then, and Windows can't delete an open file
    assert download.status_code == 200 and body == "milk\neggs 🥚"
    assert "attachment" in disposition

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
    assert "(the complete list: no other files exist there" in fake_ollama.last_prompt
    assert "clicked Save): shopping.txt\n" in fake_ollama.last_prompt
    client.post("/api/chat", json={"message": "tell me a joke"})
    assert "Files saved in the user's ai_files folder" not in fake_ollama.last_prompt


def test_windows_write_errors_get_a_hint(client, monkeypatch):
    def blocked(path, content):
        raise PermissionError(13, "Access is denied", path)
    monkeypatch.setattr(sv.file_handler, "write_file", blocked)
    response = client.post("/api/files/save", json={"path": "a.txt", "content": "x"})
    assert response.status_code == 500 and "Controlled folder access" in response.get_json()["error"]

    def our_check(path, content):
        raise PermissionError("Cannot access files outside the folder")
    monkeypatch.setattr(sv.file_handler, "write_file", our_check)
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


# ---------------- models that won't write SAVE_FILE blocks (mistral: "I can't create files, but you can...")

@pytest.mark.parametrize("message,expected", [
    ("make me a shopping list file", True),
    ("Can you create a file with my todo list?", True),
    ("save this as notes.md", True),
    ("add eggs to shopping.txt", True),
    ("write a poem and save it", True),
    ("put that in a txt", True),
    ("save my shopping list", True),
    ("how do I create a file in python?", False),
    ("what is in shopping.txt?", False),
    ("I want to save money", False),
    ("write a python function that adds two numbers", False),
    ("tell me a joke", False),
])
def test_wants_file(message, expected):
    assert file_offers.wants_file(message) is expected


REFUSAL = ("I'm sorry, but I can't create files on your computer. You can create a file named "
           "`shopping.txt` in Notepad and paste this:\n```\nmilk\neggs\n```\nThen save it.")


def test_refusal_still_offers_the_file(client, fake_ollama):
    fake_ollama.reply = REFUSAL
    data = client.post("/api/chat", json={"message": "make me a shopping list file"}).get_json()
    assert data["files"] == [{"path": "shopping.txt", "content": "milk\neggs", "exists": False}]
    assert data["has_code"] is False  # a list to save, not code to run
    done = sse_events(client.post("/api/chat-stream", json={"message": "make me a shopping list file"}))[-1]
    assert done["files"] == data["files"]


def test_refusal_without_code_block_keeps_only_the_content(client, fake_ollama):
    client.post("/api/files/save", json={"path": "notes.txt", "content": "old"})
    fake_ollama.reply = "I can't create files, but here's your list:\n- milk\n- eggs\nYou can copy this into a text file."
    files = client.post("/api/chat", json={"message": "make a file with milk and eggs"}).get_json()["files"]
    assert files == [{"path": "notes_2.txt", "content": "- milk\n- eggs", "exists": False}]  # not over notes.txt


@pytest.mark.parametrize("reply", [
    "Sure! What should the file contain?",                # a question back: nothing to save yet
    "I'm sorry, I can't create files on your computer.",  # only the refusal
])
def test_nothing_to_offer(client, fake_ollama, reply):
    fake_ollama.reply = reply
    assert client.post("/api/chat", json={"message": "create a file"}).get_json()["files"] == []


def test_only_file_requests_get_an_offer(client, fake_ollama):
    fake_ollama.reply = "```python\nprint(1 + 2)\n```"
    data = client.post("/api/chat", json={"message": "write a python function that adds two numbers"}).get_json()
    assert data["files"] == [] and data["has_code"] is True


def test_folder_listing_is_not_saved_but_names_the_file(client, fake_ollama):
    fake_ollama.reply = ("Done! Your folder now looks like this:\n```\n./ai_files/\n├── encrypt.py\n"
                         "└── file_encryptor.py\n```\nHere is the code:\n```python\nprint('secret')\n```")
    files = client.post("/api/chat", json={"message": "create a file that encrypts text"}).get_json()["files"]
    assert files == [{"path": "file_encryptor.py", "content": "print('secret')", "exists": False}]


def test_existing_file_is_flagged(client, fake_ollama):
    client.post("/api/files/save", json={"path": "shopping.txt", "content": "milk"})
    fake_ollama.reply = "SAVE_FILE: ai_files/shopping.txt\n```\nmilk\neggs\n```"
    files = client.post("/api/chat", json={"message": "add eggs to shopping.txt"}).get_json()["files"]
    assert files == [{"path": "shopping.txt", "content": "milk\neggs", "exists": True}]


def test_file_requests_end_with_a_reminder(client, fake_ollama):
    client.post("/api/chat", json={"message": "make me a shopping list file"})
    assert fake_ollama.last_prompt.endswith(f"{file_offers.FILE_REQUEST_NOTE}\n\nUser: make me a shopping list file\nAssistant:")
    for message in ("how do I create a file in python?", "tell me a joke"):
        client.post("/api/chat", json={"message": message})
        assert file_offers.FILE_REQUEST_NOTE not in fake_ollama.last_prompt


def test_model_is_told_which_files_really_exist(client, fake_ollama):
    client.post("/api/chat", json={"message": "what's in my folder?"})
    assert "The user's ai_files folder is empty: no files have been saved yet." in fake_ollama.last_prompt
    # After the model offered a file, the real list is shown even when the user doesn't mention files
    fake_ollama.reply = "SAVE_FILE: plan.txt\n```\nstep 1\n```"
    client.post("/api/chat", json={"message": "make a plan file"})
    client.post("/api/files/save", json={"path": "real.txt", "content": "x"})
    fake_ollama.reply = "ok"
    client.post("/api/chat", json={"message": "thanks, what now?"})
    assert "(the complete list: no other files exist there" in fake_ollama.last_prompt
    assert "clicked Save): real.txt\n" in fake_ollama.last_prompt


@pytest.mark.parametrize("raw,clean", [("ai_files/notes.txt", "notes.txt"), ("./ai_files/a/b.py", "a/b.py"),
                                       ("ai_files", "ai_files")])
def test_paths_inside_ai_files_are_not_nested(raw, clean):
    assert FileHandler.clean_relative_path(raw) == clean


def test_changed_copy_goes_back_into_the_saved_file(client, fake_ollama):
    client.post("/api/files/save", json={"path": "main.py", "content": "print('old')"})
    fake_ollama.reply = "Fixed:\nSAVE_FILE: main_fixed.py\n```python\nprint('new')\n```"
    files = client.post("/api/chat", json={"message": "fix the bug in main.py"}).get_json()["files"]
    assert files == [{"path": "main.py", "content": "print('new')", "exists": True}]
    # ...unless the user asks for a new file
    files = client.post("/api/chat", json={"message": "save the fix as a new file"}).get_json()["files"]
    assert files[0]["path"] == "main_fixed.py"


def test_existing_original():
    existing = {"main.py", "game/level.py", "notes.txt"}
    assert file_offers.existing_original("new_main.py", existing) == "main.py"
    assert file_offers.existing_original("game/level_v2.py", existing) == "game/level.py"
    assert file_offers.existing_original("report_2024.txt", existing) == "report_2024.txt"
    assert file_offers.existing_original("main_fixed.py", existing, "create another file for the fix") == "main_fixed.py"
    assert file_offers.existing_original("main_fixed.py", existing, "call it main_fixed.py") == "main_fixed.py"


def test_unnamed_change_goes_to_the_file_the_chat_is_about(client, fake_ollama):
    client.post("/api/files/save", json={"path": "snake.py", "content": "print('snake')"})
    fake_ollama.reply = "Here it is."
    client.post("/api/chat", json={"message": "look at snake.py"})
    fake_ollama.reply = "I can't edit files, but here is the new code:\n```python\nprint('faster snake')\n```"
    files = client.post("/api/chat", json={"message": "make the file faster"}).get_json()["files"]
    assert files == [{"path": "snake.py", "content": "print('faster snake')", "exists": True}]
